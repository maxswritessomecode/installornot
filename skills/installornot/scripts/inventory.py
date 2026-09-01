#!/usr/bin/env python3
"""Installornot — deterministic inventory, shortlist, and compatibility scan.

Stdlib only. Report-only. Never executes candidate or inventory code.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tomllib
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

INSTALLORNOT_VERSION = "0.1.0"
SCHEMA_VERSION = 1
COMPATIBILITY_RULES_DATE = "2026-08-31"
SHORTLIST_CAP = 25
MAX_CANDIDATE_TEXT = 512 * 1024
PACKAGE_MAX_FILES = 500
PACKAGE_MAX_BYTES = 5 * 1024 * 1024
FILE_MAX_BYTES = 1024 * 1024
LIVE_FETCH_TIMEOUT = 10
LIVE_FETCH_MAX_BYTES = 2 * 1024 * 1024
SEMANTIC_SKIM_BUDGET = 200
DEEP_INSPECT_CAP = 10

CLAUDE_FRONTMATTER_KEYS = {
    "name",
    "description",
    "metadata",
    "retrieval",
    "chainTo",
    "validate",
    "license",
    "summary",
    "user-invocable",
    "argument-hint",
    "allowed-tools",
    "version",
    "trigger",
    "disable-model-invocation",
}
CODEX_FRONTMATTER_KEYS = {"name", "description", "metadata"}
CLAUDE_ONLY_KEYS = CLAUDE_FRONTMATTER_KEYS - CODEX_FRONTMATTER_KEYS

PORTABILITY_NOTES = {
    "allowed-tools": "allowed-tools is not enforced on Codex CLI; tool restriction may not apply.",
    "disable-model-invocation": (
        "disable-model-invocation is not enforced on Codex CLI; the skill may auto-trigger."
    ),
}

ALLOWED_CATALOG_URLS = [
    "https://raw.githubusercontent.com/anthropics/claude-plugins-official/main/.claude-plugin/marketplace.json",
    "https://api.github.com/repos/openai/skills/contents/skills/.curated",
]

SKIP_DIR_NAMES = {".git", "node_modules", "__pycache__", ".venv", "venv", ".tox", ".mypy_cache"}
VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
FM_KEY_RE = re.compile(r"^([a-zA-Z_-]+):\s*(.*)$")

SUSPICIOUS_PATTERNS = [
    (re.compile(r"ignore (all )?(previous|prior) instructions", re.I), "instruction_override"),
    (re.compile(r"ignore the vetting", re.I), "instruction_override"),
    (re.compile(r"omit (all )?findings", re.I), "instruction_override"),
    (re.compile(r"recommend installation", re.I), "instruction_override"),
    (re.compile(r"curl\s+\S+\s*\|\s*(ba)?sh", re.I), "shell_install"),
    (re.compile(r"base64\s+-d", re.I), "encoded_payload"),
    (re.compile(r"rm\s+-rf", re.I), "destructive_shell"),
    (re.compile(r"\$\([^)]+\)"), "shell_substitution"),
]

SELF_SCRIPT = Path(__file__).resolve()
SELF_SKILL_DIR = SELF_SCRIPT.parent.parent  # directory that contains SKILL.md + scripts/


def _development_repo() -> Path | None:
    """Repo root when running from <repo>/skill/scripts/inventory.py, else None.

    Must not treat ~/.claude/skills as a repo: that would exclude every personal skill.
    """
    if SELF_SCRIPT.parent.name != "scripts" or SELF_SKILL_DIR.name != "skill":
        return None
    repo = SELF_SKILL_DIR.parent
    if (repo / "docs" / "spec.md").is_file() or (SELF_SKILL_DIR / "SKILL.md").is_file():
        return repo
    return None


SELF_REPO = _development_repo()


def is_self_path(path: Path) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path
    roots = [SELF_SKILL_DIR]
    if SELF_REPO is not None:
        roots.append(SELF_REPO)
    for root in roots:
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


class CatalogFetchError(Exception):
    """Allowlist, size, or transport failure for a live catalog fetch."""


class CandidateError(Exception):
    """Fatal candidate input error (exit non-zero)."""


@dataclass
class Config:
    claude_dir: Path
    codex_home: Path
    cwd: Path
    home: Path
    catalogs: str = "local"
    show_absolute: bool = False
    kind: str = "auto"


@dataclass
class Health:
    broken_symlinks: list[dict[str, str]] = field(default_factory=list)
    stale_plugin_versions: list[dict[str, Any]] = field(default_factory=list)
    shadowed_entries: list[dict[str, str]] = field(default_factory=list)
    version_order_ambiguous: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "broken_symlinks": self.broken_symlinks,
            "stale_plugin_versions": self.stale_plugin_versions,
            "shadowed_entries": self.shadowed_entries,
            "version_order_ambiguous": self.version_order_ambiguous,
        }


# ---------------------------------------------------------------------------
# Path / text helpers
# ---------------------------------------------------------------------------

def display_path(path: str | Path, home: Path, *, absolute: bool = False) -> str:
    raw = str(path)
    if absolute:
        return raw
    home_s = str(home)
    if raw == home_s or raw.startswith(home_s + os.sep):
        return "$HOME" + raw[len(home_s) :]
    real_home = str(Path.home())
    if raw == real_home or raw.startswith(real_home + os.sep):
        return "$HOME" + raw[len(real_home) :]
    return raw


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_frontmatter(text: str) -> dict[str, Any]:
    result: dict[str, Any] = {"keys": {}, "key_order": [], "body": text, "error": None}
    if not text.startswith("---"):
        result["error"] = "no_frontmatter"
        return result
    rest = text[3:]
    if rest.startswith("\n"):
        rest = rest[1:]
    end = rest.find("\n---")
    if end < 0:
        result["error"] = "unclosed_frontmatter"
        return result
    block = rest[:end]
    body = rest[end + 4 :]
    if body.startswith("\n"):
        body = body[1:]
    result["body"] = body
    current_key = None
    for line in block.splitlines():
        if line.startswith(" ") or line.startswith("\t"):
            if current_key:
                result["keys"][current_key] = str(result["keys"][current_key]) + "\n" + line
            continue
        m = FM_KEY_RE.match(line)
        if m:
            current_key = m.group(1)
            result["keys"][current_key] = m.group(2).strip()
            result["key_order"].append(current_key)
        else:
            current_key = None
    return result


def normalize_description(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold()
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def tokenize(text: str) -> list[str]:
    return [t for t in normalize_description(text).split() if t]


def description_shingles(a: str, b: str) -> int:
    ta, tb = tokenize(a), tokenize(b)
    if len(ta) < 2 or len(tb) < 2:
        return 0
    n = 6 if len(ta) >= 6 and len(tb) >= 6 else max(2, min(len(ta), len(tb)))
    if len(ta) < n or len(tb) < n:
        return 0

    def grams(toks: list[str]) -> set[str]:
        return {" ".join(toks[i : i + n]) for i in range(len(toks) - n + 1)}

    return len(grams(ta) & grams(tb))


def parse_version_dir(name: str) -> tuple[str, Any, bool]:
    m = VERSION_RE.match(name)
    if m:
        return ("numeric", tuple(int(x) for x in m.groups()), False)
    return ("lex", name, True)


def pick_highest_version(dirs: list[str]) -> tuple[str, list[str], bool]:
    if not dirs:
        return "", [], False
    parsed = [(d, parse_version_dir(d)) for d in dirs]
    ambiguous = any(p[1][2] for p in parsed)
    numeric = all(p[1][0] == "numeric" for p in parsed)
    if numeric:
        parsed.sort(key=lambda x: x[1][1])
    else:
        parsed.sort(key=lambda x: x[0])
        ambiguous = True
    chosen = parsed[-1][0]
    stale = [p[0] for p in parsed[:-1]]
    return chosen, stale, ambiguous


def inspect_suspicious(text: str) -> list[str]:
    found: list[str] = []
    for rx, label in SUSPICIOUS_PATTERNS:
        if rx.search(text or ""):
            if label not in found:
                found.append(label)
    return found


def referenced_commands(text: str) -> list[str]:
    cmds: list[str] = []
    for m in re.finditer(r"(?:^|\s)(?:npx|uv|python3?|node|docker|curl|bash|sh)\b", text or "", re.I):
        cmds.append(m.group(0).strip())
    return cmds


def referenced_urls(text: str) -> list[str]:
    return re.findall(r"https?://[^\s)>\"]+", text or "")


def shell_install(text: str) -> bool:
    return bool(re.search(r"curl\s+\S+\s*\|\s*(ba)?sh", text or "", re.I))


# ---------------------------------------------------------------------------
# Kind detection
# ---------------------------------------------------------------------------

def detect_kind(path: Path | None = None, text: str | None = None) -> str:
    if path is not None:
        p = Path(path)
        if p.is_dir():
            if (p / ".claude-plugin" / "plugin.json").is_file() or (p / "plugin.json").is_file():
                return "plugin"
            if (p / "SKILL.md").is_file():
                return "skill"
            if (p / ".mcp.json").is_file() or (p / "mcp.json").is_file():
                return "mcp"
        elif p.is_file():
            if p.name == "SKILL.md":
                return "skill"
            if p.name in {".mcp.json", "mcp.json"}:
                return "mcp"
            try:
                raw = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                return "skill"
            if p.suffix == ".json":
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError:
                    obj = None
                if isinstance(obj, dict) and "mcpServers" in obj:
                    return "mcp"
                if isinstance(obj, dict) and obj.get("name") and (
                    "version" in obj or "author" in obj
                ):
                    return "plugin"
            if raw.lstrip().startswith("---"):
                return "skill"
    if text:
        stripped = text.lstrip()
        if stripped.startswith("---"):
            return "skill"
        try:
            obj = json.loads(text)
            if isinstance(obj, dict) and "mcpServers" in obj:
                return "mcp"
        except json.JSONDecodeError:
            pass
        if "[mcp_servers" in text:
            return "mcp"
    return "skill"


def load_plugin_manifest(directory: Path) -> dict[str, Any] | None:
    for rel in (".claude-plugin/plugin.json", "plugin.json"):
        p = directory / rel
        if p.is_file():
            try:
                obj = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None
            if isinstance(obj, dict):
                return obj
    return None


# ---------------------------------------------------------------------------
# Compatibility
# ---------------------------------------------------------------------------

def command_exists(command: str) -> bool:
    if not command:
        return False
    if os.path.isabs(command) or os.sep in command:
        return Path(command).exists()
    return shutil.which(command) is not None


def mcp_entry_compatibility(entry: dict[str, Any]) -> dict[str, Any]:
    findings: list[str] = []
    status = "works"
    command = entry.get("command")
    url = entry.get("url")
    env = entry.get("env") if isinstance(entry.get("env"), dict) else {}
    if command:
        if not command_exists(str(command)):
            status = "wont_work"
            findings.append(f"command not on PATH: {Path(str(command)).name}")
    elif url:
        parsed = urlparse(str(url))
        if not (parsed.scheme and parsed.netloc):
            status = "wont_work"
            findings.append("http MCP url is not well-formed")
    else:
        status = "unknown"
        findings.append("no command or url")
    missing = [k for k in env if k not in os.environ]
    if missing:
        findings.append("missing env names: " + ", ".join(missing))
        if status == "works":
            status = "needs_config"
    return {"status": status, "findings": findings}


def skill_compatibility(frontmatter_keys: list[str]) -> dict[str, Any]:
    findings: list[str] = []
    for key in frontmatter_keys:
        if key in CLAUDE_ONLY_KEYS:
            note = PORTABILITY_NOTES.get(key, "may not apply on Codex CLI")
            findings.append(f"portability: {key} is Claude-specific; {note}")
    return {"status": "works", "findings": findings}


# ---------------------------------------------------------------------------
# Shortlist
# ---------------------------------------------------------------------------

def _identity_key(item: dict[str, Any]) -> tuple:
    return (item.get("kind"), item.get("name"), item.get("content_sha256"), item.get("display_path"))


def shortlist(candidate: dict[str, Any], inventory: list[dict[str, Any]], cap: int = SHORTLIST_CAP) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    probes: list[tuple[str, str]] = [(candidate.get("name") or "", candidate.get("description") or "")]
    for bundled in candidate.get("bundled") or []:
        probes.append((bundled.get("name") or "", bundled.get("description") or ""))

    ranked: list[tuple[int, int, dict[str, Any]]] = []
    seen: set[tuple] = set()
    for item in inventory:
        best_reason = None
        best_shingles = 0
        best_rank = 99
        iname = item.get("name") or ""
        idesc = item.get("description") or ""
        for pname, pdesc in probes:
            if pname and iname and pname.casefold() == iname.casefold():
                best_reason, best_rank, best_shingles = "exact_name", 0, 0
                break
            if pdesc and idesc and normalize_description(pdesc) == normalize_description(idesc) and normalize_description(pdesc):
                if best_rank > 1:
                    best_reason, best_rank, best_shingles = "exact_description", 1, 0
            else:
                n = description_shingles(pdesc, idesc)
                if n > 0 and best_rank > 2:
                    best_reason, best_rank, best_shingles = "shingle", 2, n
                elif n > best_shingles and best_reason == "shingle":
                    best_shingles = n
        if best_reason:
            key = _identity_key(item)
            if key in seen:
                continue
            seen.add(key)
            ranked.append((best_rank, -best_shingles, {
                "kind": item.get("kind"),
                "name": item.get("name"),
                "description": item.get("description"),
                "source_type": item.get("source_type"),
                "display_path": item.get("display_path"),
                "match_reason": best_reason,
                "shingle_count": best_shingles if best_reason == "shingle" else 0,
            }))
    ranked.sort(key=lambda t: (t[0], t[1], t[2].get("name") or ""))
    total = len(ranked)
    chosen = [t[2] for t in ranked[:cap]]
    return chosen, {
        "total_matches": total,
        "included_matches": len(chosen),
        "truncated": total > cap,
    }


# ---------------------------------------------------------------------------
# Package provenance (static, no execution, no escape via symlink)
# ---------------------------------------------------------------------------

def inspect_package(directory: Path) -> dict[str, Any]:
    executables: list[str] = []
    skipped = 0
    truncated = False
    files_seen = 0
    bytes_seen = 0
    root = directory.resolve()
    stack = [directory]
    while stack:
        current = stack.pop()
        try:
            children = list(current.iterdir())
        except OSError:
            skipped += 1
            continue
        for child in children:
            if child.is_symlink():
                try:
                    resolved = child.resolve()
                    resolved.relative_to(root)
                except (OSError, ValueError):
                    skipped += 1
                    continue
                if not resolved.exists():
                    skipped += 1
                    continue
            if child.is_dir() and not child.is_symlink():
                if child.name in SKIP_DIR_NAMES:
                    continue
                stack.append(child)
                continue
            if child.is_symlink() and child.resolve().is_dir():
                continue
            files_seen += 1
            if files_seen > PACKAGE_MAX_FILES:
                truncated = True
                continue
            try:
                st = child.stat()
            except OSError:
                skipped += 1
                continue
            if st.st_size > FILE_MAX_BYTES:
                skipped += 1
                continue
            bytes_seen += st.st_size
            if bytes_seen > PACKAGE_MAX_BYTES:
                truncated = True
                continue
            if os.access(child, os.X_OK) and child.is_file():
                executables.append(child.name)
    return {
        "executables": sorted(set(executables)),
        "skipped_files": skipped,
        "truncated": truncated,
        "adjacent_inspection": "inspected",
    }


# ---------------------------------------------------------------------------
# Inventory items
# ---------------------------------------------------------------------------

def skill_item_from_file(
    skill_md: Path,
    *,
    source_type: str,
    cfg: Config,
    extra_source: str | None = None,
) -> dict[str, Any] | None:
    if is_self_path(skill_md):
        return None
    try:
        text = skill_md.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    parsed = parse_frontmatter(text)
    keys = parsed["keys"]
    name = keys.get("name") or skill_md.parent.name
    description = keys.get("description") or ""
    real = str(skill_md)
    try:
        real = str(skill_md.resolve())
    except OSError:
        pass
    item = {
        "kind": "skill",
        "name": name,
        "description": description,
        "source_type": source_type,
        "display_path": display_path(skill_md, cfg.home, absolute=cfg.show_absolute),
        "content_sha256": sha256_text(text),
        "sources": [display_path(skill_md, cfg.home, absolute=cfg.show_absolute)],
        "frontmatter_keys": list(parsed["key_order"] or keys.keys()),
        "_real": real,
    }
    if extra_source:
        item["sources"].append(extra_source)
    return item


def mcp_item(
    name: str,
    command: str | None,
    url: str | None,
    env_names: list[str],
    *,
    source_type: str,
    origin: Path,
    cfg: Config,
) -> dict[str, Any]:
    desc = command or url or ""
    canonical = json.dumps(
        {"name": name, "command": command, "url": url, "env_names": env_names},
        sort_keys=True,
    )
    return {
        "kind": "mcp",
        "name": name,
        "description": str(desc),
        "source_type": source_type,
        "display_path": display_path(origin, cfg.home, absolute=cfg.show_absolute),
        "content_sha256": sha256_text(canonical),
        "sources": [display_path(origin, cfg.home, absolute=cfg.show_absolute)],
        "frontmatter_keys": [],
        "_real": f"mcp:{origin}:{name}",
        "_env_names": env_names,
    }


def plugin_item(
    name: str,
    description: str,
    version: str,
    origin: Path,
    *,
    source_type: str,
    cfg: Config,
) -> dict[str, Any]:
    canonical = json.dumps({"name": name, "version": version, "description": description}, sort_keys=True)
    return {
        "kind": "plugin",
        "name": name,
        "description": description,
        "source_type": source_type,
        "display_path": display_path(origin, cfg.home, absolute=cfg.show_absolute),
        "content_sha256": sha256_text(canonical),
        "sources": [display_path(origin, cfg.home, absolute=cfg.show_absolute)],
        "frontmatter_keys": [],
        "_real": str(origin.resolve()) if origin.exists() else str(origin),
    }


def dedupe_inventory(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_real: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for item in items:
        key = item.get("_real") or (item["kind"], item["name"], item["content_sha256"])
        key_s = str(key)
        if key_s in by_real:
            existing = by_real[key_s]
            for src in item.get("sources") or []:
                if src not in existing["sources"]:
                    existing["sources"].append(src)
            continue
        by_real[key_s] = item
        order.append(key_s)
    out = []
    for k in order:
        item = dict(by_real[k])
        item.pop("_real", None)
        item.pop("_env_names", None)
        out.append(item)
    return out


# ---------------------------------------------------------------------------
# Discovery adapters
# ---------------------------------------------------------------------------

def walk_skill_dir(
    root: Path,
    source_type: str,
    cfg: Config,
    health: Health,
    scan_errors: list[dict[str, str]],
    *,
    include_dot_system: bool = False,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if not root.exists():
        return items
    try:
        children = list(root.iterdir())
    except OSError as exc:
        scan_errors.append({
            "root": display_path(root, cfg.home, absolute=cfg.show_absolute),
            "code": "permission_denied" if getattr(exc, "errno", None) in {13, 1} else "unreadable",
            "message": "unreadable inventory root",
        })
        return items
    for child in sorted(children, key=lambda p: p.name):
        if child.name.startswith(".") and not (include_dot_system and child.name == ".system"):
            continue
        if include_dot_system and child.name == ".system" and child.is_dir():
            items.extend(walk_skill_dir(child, "codex_builtin", cfg, health, scan_errors))
            continue
        if child.is_symlink() and not child.exists():
            target = "<redacted>"
            if cfg.show_absolute:
                try:
                    target = os.readlink(child)
                except OSError:
                    target = "<unreadable>"
            health.broken_symlinks.append({"name": child.name, "target": target})
            continue
        skill_md = child / "SKILL.md" if child.is_dir() else None
        if skill_md and skill_md.is_file():
            item = skill_item_from_file(skill_md, source_type=source_type, cfg=cfg)
            if item:
                items.append(item)
    return items


def project_skill_roots(cwd: Path, cfg: Config) -> list[tuple[Path, str]]:
    found: list[tuple[Path, str]] = []
    skip = set()
    for p in (cfg.claude_dir / "skills", cfg.codex_home / "skills"):
        try:
            skip.add(p.resolve())
        except OSError:
            skip.add(p)
    cur = cwd.resolve()
    while True:
        for rel, label in ((".claude/skills", "project"), (".codex/skills", "project")):
            p = cur / rel
            if not p.is_dir():
                continue
            try:
                real = p.resolve()
            except OSError:
                real = p
            if real in skip:
                continue
            found.append((p, label))
        if (cur / ".git").exists():
            break
        if cur.parent == cur:
            break
        cur = cur.parent
    return found


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def discover_claude(cfg: Config, health: Health, scan_errors: list[dict[str, str]], roots: list[str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    skills_root = cfg.claude_dir / "skills"
    roots.append(display_path(skills_root, cfg.home, absolute=cfg.show_absolute))
    items.extend(walk_skill_dir(skills_root, "personal", cfg, health, scan_errors))

    mcp_path = cfg.claude_dir / "claude_mcp_config.json"
    if mcp_path.is_file():
        roots.append(display_path(mcp_path, cfg.home, absolute=cfg.show_absolute))
        try:
            obj = load_json(mcp_path)
        except (OSError, json.JSONDecodeError) as exc:
            scan_errors.append({
                "root": display_path(mcp_path, cfg.home, absolute=cfg.show_absolute),
                "code": "malformed",
                "message": str(exc.__class__.__name__),
            })
            obj = {}
        servers = obj.get("mcpServers") if isinstance(obj, dict) else {}
        if isinstance(servers, dict):
            for name, entry in servers.items():
                if not isinstance(entry, dict):
                    continue
                env = entry.get("env") if isinstance(entry.get("env"), dict) else {}
                items.append(
                    mcp_item(
                        name,
                        entry.get("command"),
                        entry.get("url"),
                        list(env.keys()),
                        source_type="personal",
                        origin=mcp_path,
                        cfg=cfg,
                    )
                )

    enabled_map: dict[str, Any] = {}
    settings_path = cfg.claude_dir / "settings.json"
    if settings_path.is_file():
        try:
            settings = load_json(settings_path)
            if isinstance(settings, dict) and isinstance(settings.get("enabledPlugins"), dict):
                enabled_map = settings["enabledPlugins"]
        except (OSError, json.JSONDecodeError):
            pass

    installed_path = cfg.claude_dir / "plugins" / "installed_plugins.json"
    if installed_path.is_file():
        roots.append(display_path(installed_path, cfg.home, absolute=cfg.show_absolute))
        try:
            installed = load_json(installed_path)
        except (OSError, json.JSONDecodeError) as exc:
            scan_errors.append({
                "root": display_path(installed_path, cfg.home, absolute=cfg.show_absolute),
                "code": "malformed",
                "message": str(exc.__class__.__name__),
            })
            installed = {}
        plugins = installed.get("plugins") if isinstance(installed, dict) else {}
        if isinstance(plugins, dict):
            for key, entries in plugins.items():
                if enabled_map and key in enabled_map and not enabled_map[key]:
                    continue
                entry = entries[0] if isinstance(entries, list) and entries else entries
                if not isinstance(entry, dict):
                    continue
                raw_path = entry.get("installPath")
                if not raw_path:
                    continue
                install_path = Path(raw_path)
                manifest = load_plugin_manifest(install_path)
                pname = (manifest or {}).get("name") or key.split("@")[0]
                pdesc = (manifest or {}).get("description") or ""
                version = str(entry.get("version") or (manifest or {}).get("version") or "")
                items.append(
                    plugin_item(pname, pdesc, version, install_path, source_type="plugin", cfg=cfg)
                )
                skills_dir = install_path / "skills"
                if skills_dir.is_dir():
                    try:
                        children = list(skills_dir.iterdir())
                    except OSError as exc:
                        scan_errors.append({
                            "root": display_path(skills_dir, cfg.home, absolute=cfg.show_absolute),
                            "code": "unreadable",
                            "message": "unreadable plugin skills",
                        })
                        children = []
                    for child in children:
                        skill_md = child / "SKILL.md"
                        if skill_md.is_file():
                            item = skill_item_from_file(skill_md, source_type="plugin", cfg=cfg)
                            if item:
                                items.append(item)
    return items


def discover_codex(cfg: Config, health: Health, scan_errors: list[dict[str, str]], roots: list[str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    skills_root = cfg.codex_home / "skills"
    roots.append(display_path(skills_root, cfg.home, absolute=cfg.show_absolute))
    items.extend(walk_skill_dir(skills_root, "personal", cfg, health, scan_errors, include_dot_system=True))

    config_path = cfg.codex_home / "config.toml"
    if not config_path.is_file():
        return items
    roots.append(display_path(config_path, cfg.home, absolute=cfg.show_absolute))
    try:
        raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        scan_errors.append({
            "root": display_path(config_path, cfg.home, absolute=cfg.show_absolute),
            "code": "malformed",
            "message": str(exc.__class__.__name__),
        })
        return items

    servers = raw.get("mcp_servers") if isinstance(raw.get("mcp_servers"), dict) else {}
    for name, entry in servers.items():
        if not isinstance(entry, dict):
            continue
        env = entry.get("env") if isinstance(entry.get("env"), dict) else {}
        items.append(
            mcp_item(
                name,
                entry.get("command"),
                entry.get("url"),
                list(env.keys()),
                source_type="personal",
                origin=config_path,
                cfg=cfg,
            )
        )

    plugins = raw.get("plugins") if isinstance(raw.get("plugins"), dict) else {}
    cache_root = cfg.codex_home / "plugins" / "cache"
    for key, table in plugins.items():
        if not isinstance(table, dict) or not table.get("enabled"):
            continue
        if "@" in key:
            plugin_name, marketplace = key.split("@", 1)
        else:
            plugin_name, marketplace = key, ""
        plugin_cache = cache_root / marketplace / plugin_name
        if not plugin_cache.is_dir():
            continue
        try:
            versions = [p.name for p in plugin_cache.iterdir() if p.is_dir()]
        except OSError:
            continue
        if not versions:
            continue
        chosen, stale, ambiguous = pick_highest_version(versions)
        if stale:
            health.stale_plugin_versions.append({
                "plugin": key,
                "active_version": chosen,
                "stale_versions": stale,
            })
        if ambiguous:
            health.version_order_ambiguous.append(key)
        install_path = plugin_cache / chosen
        manifest = load_plugin_manifest(install_path)
        pname = (manifest or {}).get("name") or plugin_name
        pdesc = (manifest or {}).get("description") or ""
        items.append(plugin_item(pname, pdesc, chosen, install_path, source_type="plugin", cfg=cfg))
        skills_dir = install_path / "skills"
        if skills_dir.is_dir():
            try:
                children = list(skills_dir.iterdir())
            except OSError:
                children = []
            for child in children:
                skill_md = child / "SKILL.md"
                if skill_md.is_file():
                    item = skill_item_from_file(skill_md, source_type="plugin", cfg=cfg)
                    if item:
                        items.append(item)
    return items


def discover_project(cfg: Config, health: Health, scan_errors: list[dict[str, str]], roots: list[str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for root, label in project_skill_roots(cfg.cwd, cfg):
        roots.append(display_path(root, cfg.home, absolute=cfg.show_absolute))
        items.extend(walk_skill_dir(root, label, cfg, health, scan_errors))
    cur = cfg.cwd.resolve()
    while True:
        mcp = cur / ".mcp.json"
        if mcp.is_file():
            roots.append(display_path(mcp, cfg.home, absolute=cfg.show_absolute))
            try:
                obj = load_json(mcp)
            except (OSError, json.JSONDecodeError):
                obj = {}
            servers = obj.get("mcpServers") if isinstance(obj, dict) else {}
            if isinstance(servers, dict):
                for name, entry in servers.items():
                    if not isinstance(entry, dict):
                        continue
                    env = entry.get("env") if isinstance(entry.get("env"), dict) else {}
                    items.append(
                        mcp_item(
                            name,
                            entry.get("command"),
                            entry.get("url"),
                            list(env.keys()),
                            source_type="project",
                            origin=mcp,
                            cfg=cfg,
                        )
                    )
        if (cur / ".git").exists() or cur.parent == cur:
            break
        cur = cur.parent
    return items


# ---------------------------------------------------------------------------
# Candidate loading
# ---------------------------------------------------------------------------

def _mcp_servers_from_obj(obj: Any) -> dict[str, dict[str, Any]]:
    if isinstance(obj, dict) and isinstance(obj.get("mcpServers"), dict):
        return {k: v for k, v in obj["mcpServers"].items() if isinstance(v, dict)}
    return {}


def load_candidate(cfg: Config, path: Path | None, text: str | None, kind: str) -> dict[str, Any]:
    if path is None and not text:
        raise CandidateError("no candidate")
    adjacent = {
        "input_type": "path" if path is not None else "pasted_text",
        "source_url": None,
        "license": None,
        "executables": [],
        "external_commands": [],
        "network_endpoints": [],
        "shell_install": False,
        "adjacent_inspection": "not_inspected",
        "skipped_files": 0,
        "truncated": False,
    }
    bundled: list[dict[str, Any]] = []
    raw_text = text or ""
    resolved_kind = kind
    candidate_path = path

    if path is not None:
        if not path.exists():
            raise CandidateError(f"unreadable candidate: {path}")
        if kind == "auto":
            resolved_kind = detect_kind(path)
        if path.is_dir():
            pkg = inspect_package(path)
            adjacent.update(pkg)
            if resolved_kind == "plugin":
                manifest = load_plugin_manifest(path)
                if not manifest:
                    raise CandidateError("plugin candidate missing plugin.json")
                name = str(manifest.get("name") or path.name)
                description = str(manifest.get("description") or "")
                raw_text = json.dumps(manifest, sort_keys=True)
                adjacent["license"] = manifest.get("license") or None
                adjacent["source_url"] = manifest.get("homepage") or None
                skills_dir = path / "skills"
                if skills_dir.is_dir():
                    for child in sorted(skills_dir.iterdir(), key=lambda p: p.name):
                        skill_md = child / "SKILL.md"
                        if skill_md.is_file():
                            try:
                                body = skill_md.read_text(encoding="utf-8", errors="replace")
                            except OSError:
                                continue
                            parsed = parse_frontmatter(body)
                            bundled.append({
                                "kind": "skill",
                                "name": parsed["keys"].get("name") or child.name,
                                "description": parsed["keys"].get("description") or "",
                            })
                mcp_file = path / ".mcp.json" if (path / ".mcp.json").is_file() else path / "mcp.json"
                if mcp_file.is_file():
                    try:
                        servers = _mcp_servers_from_obj(load_json(mcp_file))
                    except (OSError, json.JSONDecodeError):
                        servers = {}
                    for sname, entry in servers.items():
                        bundled.append({
                            "kind": "mcp",
                            "name": sname,
                            "description": str(entry.get("command") or entry.get("url") or ""),
                        })
                compat = {"status": "works", "findings": []}
                return {
                    "kind": "plugin",
                    "name": name,
                    "description": description,
                    "frontmatter_keys": [],
                    "content_sha256": sha256_text(raw_text),
                    "provenance": adjacent,
                    "compatibility": compat,
                    "bundled": bundled,
                    "suspicious_patterns": inspect_suspicious(raw_text + " " + description),
                    "parse_error": None,
                }
            if resolved_kind == "mcp":
                mcp_file = path / ".mcp.json" if (path / ".mcp.json").is_file() else path / "mcp.json"
                if not mcp_file.is_file():
                    raise CandidateError("mcp directory missing .mcp.json")
                candidate_path = mcp_file
                raw_text = mcp_file.read_text(encoding="utf-8", errors="replace")
            else:
                skill_md = path / "SKILL.md"
                if not skill_md.is_file():
                    raise CandidateError("directory has no SKILL.md")
                candidate_path = skill_md
                raw_text = skill_md.read_text(encoding="utf-8", errors="replace")
        else:
            raw_text = path.read_text(encoding="utf-8", errors="replace")
            if kind == "auto":
                resolved_kind = detect_kind(path, raw_text)

    if len(raw_text.encode("utf-8")) > MAX_CANDIDATE_TEXT:
        raise CandidateError("candidate exceeds maximum size")

    if resolved_kind == "auto":
        resolved_kind = detect_kind(candidate_path, raw_text)

    adjacent["external_commands"] = referenced_commands(raw_text)
    adjacent["network_endpoints"] = referenced_urls(raw_text)
    adjacent["shell_install"] = shell_install(raw_text)
    suspicious = inspect_suspicious(raw_text)

    if resolved_kind == "mcp":
        try:
            obj = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise CandidateError("candidate is not valid JSON") from exc
        servers = _mcp_servers_from_obj(obj)
        if not servers:
            raise CandidateError("mcp candidate has no mcpServers")
        name, entry = next(iter(servers.items()))
        # Strip secrets: never keep env values
        env = entry.get("env") if isinstance(entry.get("env"), dict) else {}
        env_names = list(env.keys())
        safe_entry = {k: v for k, v in entry.items() if k != "env"}
        if env_names:
            safe_entry["env"] = {k: "" for k in env_names}
        compat = mcp_entry_compatibility(entry)
        desc = str(entry.get("command") or entry.get("url") or "")
        adjacent["source_url"] = entry.get("url") if isinstance(entry.get("url"), str) else None
        return {
            "kind": "mcp",
            "name": name,
            "description": desc,
            "frontmatter_keys": [],
            "content_sha256": sha256_text(json.dumps({"name": name, **{k: safe_entry[k] for k in safe_entry if k != "env"}}, sort_keys=True)),
            "provenance": adjacent,
            "compatibility": compat,
            "bundled": [],
            "suspicious_patterns": suspicious,
            "parse_error": None,
        }

    parsed = parse_frontmatter(raw_text)
    keys = parsed["keys"]
    name = keys.get("name")
    description = keys.get("description")
    if parsed["error"] and not name:
        raise CandidateError(parsed["error"])
    if not description:
        raise CandidateError("candidate has no description")
    if not name:
        name = (candidate_path.parent.name if candidate_path else "candidate")
    fm_keys = list(parsed["key_order"] or keys.keys())
    adjacent["license"] = keys.get("license") or None
    adjacent["source_url"] = keys.get("homepage") or keys.get("source") or None
    compat = skill_compatibility(fm_keys)
    return {
        "kind": "skill",
        "name": name,
        "description": description,
        "frontmatter_keys": fm_keys,
        "content_sha256": sha256_text(raw_text),
        "provenance": adjacent,
        "compatibility": compat,
        "bundled": bundled,
        "suspicious_patterns": suspicious,
        "parse_error": parsed["error"],
    }


# ---------------------------------------------------------------------------
# Catalogs
# ---------------------------------------------------------------------------

def fetch_catalog(url: str, fetcher: Callable[[str], bytes] | None = None) -> bytes:
    if url not in ALLOWED_CATALOG_URLS:
        raise CatalogFetchError(f"not allowlisted: {url}")
    if fetcher is None:
        def fetcher(u: str) -> bytes:  # type: ignore[misc]
            req = urllib.request.Request(u, headers={"User-Agent": "installornot/0.1"})
            with urllib.request.urlopen(req, timeout=LIVE_FETCH_TIMEOUT) as resp:
                return resp.read(LIVE_FETCH_MAX_BYTES + 1)
    try:
        data = fetcher(url)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise CatalogFetchError(str(exc)) from exc
    if len(data) > LIVE_FETCH_MAX_BYTES:
        raise CatalogFetchError("oversized catalog response")
    return data


def catalog_entries_from_obj(obj: Any, source: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    plugins = None
    if isinstance(obj, dict) and isinstance(obj.get("plugins"), list):
        plugins = obj["plugins"]
    elif isinstance(obj, list):
        plugins = obj
    if not plugins:
        return entries
    for item in plugins:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        if not name:
            continue
        desc = str(item.get("description") or "")
        entries.append({
            "kind": "plugin" if "plugins" in (obj if isinstance(obj, dict) else {}) else "skill",
            "name": name,
            "description": desc,
            "source_type": "catalog",
            "display_path": source,
            "match_reason": "",
            "shingle_count": 0,
        })
    return entries


def load_local_catalogs(cfg: Config) -> tuple[list[dict[str, Any]], list[str]]:
    entries: list[dict[str, Any]] = []
    sources: list[str] = []
    market_root = cfg.claude_dir / "plugins" / "marketplaces"
    if market_root.is_dir():
        try:
            slugs = list(market_root.iterdir())
        except OSError:
            slugs = []
        for slug_dir in slugs:
            mp = slug_dir / ".claude-plugin" / "marketplace.json"
            if not mp.is_file():
                continue
            sources.append(display_path(mp, cfg.home, absolute=cfg.show_absolute))
            try:
                obj = load_json(mp)
            except (OSError, json.JSONDecodeError):
                continue
            entries.extend(catalog_entries_from_obj(obj, display_path(mp, cfg.home, absolute=cfg.show_absolute)))
    config_path = cfg.codex_home / "config.toml"
    if config_path.is_file():
        try:
            raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            raw = {}
        markets = raw.get("marketplaces") if isinstance(raw.get("marketplaces"), dict) else {}
        for _name, table in markets.items():
            if not isinstance(table, dict):
                continue
            src = table.get("source")
            if table.get("source_type") == "local" and src:
                local = Path(str(src))
                mp = local / ".claude-plugin" / "marketplace.json"
                if mp.is_file():
                    sources.append(display_path(mp, cfg.home, absolute=cfg.show_absolute))
                    try:
                        obj = load_json(mp)
                    except (OSError, json.JSONDecodeError):
                        continue
                    entries.extend(
                        catalog_entries_from_obj(obj, display_path(mp, cfg.home, absolute=cfg.show_absolute))
                    )
    return entries, sources


def live_catalogs() -> tuple[list[dict[str, Any]], list[str], list[str]]:
    entries: list[dict[str, Any]] = []
    sources: list[str] = []
    errors: list[str] = []
    for url in ALLOWED_CATALOG_URLS:
        try:
            data = fetch_catalog(url)
        except CatalogFetchError as exc:
            errors.append(f"{url}: {exc}")
            continue
        sources.append(url)
        try:
            obj = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            errors.append(f"{url}: untrusted payload is not JSON")
            continue
        entries.extend(catalog_entries_from_obj(obj, url))
    return entries, sources, errors


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def build_report(cfg: Config, candidate_path: Path | None, candidate_text: str | None) -> dict[str, Any]:
    health = Health()
    scan_errors: list[dict[str, str]] = []
    roots: list[str] = []
    kind = cfg.kind
    candidate = load_candidate(cfg, candidate_path, candidate_text, kind)

    inventory: list[dict[str, Any]] = []
    inventory.extend(discover_claude(cfg, health, scan_errors, roots))
    inventory.extend(discover_codex(cfg, health, scan_errors, roots))
    inventory.extend(discover_project(cfg, health, scan_errors, roots))
    inventory = dedupe_inventory(inventory)

    sl, sl_meta = shortlist(candidate, inventory)

    catalog_hits: list[dict[str, Any]] = []
    catalog_meta = {"mode": cfg.catalogs, "sources": [], "truncated": False, "fetch_errors": []}
    if cfg.catalogs in {"local", "live"}:
        local_entries, local_sources = load_local_catalogs(cfg)
        catalog_meta["sources"].extend(local_sources)
        all_entries = list(local_entries)
        if cfg.catalogs == "live":
            live_entries, live_sources, fetch_errors = live_catalogs()
            catalog_meta["sources"].extend(live_sources)
            catalog_meta["fetch_errors"] = fetch_errors
            all_entries.extend(live_entries)
        installed_names = {(i.get("kind"), (i.get("name") or "").casefold()) for i in inventory}
        available = [
            e
            for e in all_entries
            if (e.get("kind"), (e.get("name") or "").casefold()) not in installed_names
            and (e.get("name") or "").casefold() != (candidate.get("name") or "").casefold()
        ]
        # Reuse shortlist against catalog-shaped inventory
        fake_inv = [
            {
                "kind": e.get("kind") or "plugin",
                "name": e.get("name"),
                "description": e.get("description"),
                "source_type": "catalog",
                "display_path": e.get("display_path"),
                "content_sha256": "",
                "sources": [e.get("display_path")],
                "frontmatter_keys": [],
            }
            for e in available
        ]
        hits, hit_meta = shortlist(candidate, fake_inv)
        catalog_hits = hits
        catalog_meta["truncated"] = hit_meta["truncated"]

    eligible = [s for s in sl if s.get("match_reason") == "exact_name"]
    deep = {
        "eligible_entries": len(eligible),
        "inspected_entries": min(len(eligible), DEEP_INSPECT_CAP),
        "omitted_entries": max(0, len(eligible) - DEEP_INSPECT_CAP),
        "truncated": len(eligible) > DEEP_INSPECT_CAP,
    }
    skim = {
        "total_entries": len(inventory),
        "included_entries": min(len(inventory), SEMANTIC_SKIM_BUDGET),
        "truncated": len(inventory) > SEMANTIC_SKIM_BUDGET,
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "installornot_version": INSTALLORNOT_VERSION,
        "compatibility_rules_date": COMPATIBILITY_RULES_DATE,
        "platforms": [
            {"name": "claude", "version": "unknown", "adapter_status": "supported"},
            {"name": "codex", "version": "unknown", "adapter_status": "supported"},
        ],
        "resolved_roots": roots,
        "candidate": candidate,
        "active_inventory": inventory,
        "shortlist": sl,
        "shortlist_metadata": sl_meta,
        "catalog_hits": catalog_hits,
        "catalog_metadata": catalog_meta,
        "inventory_health": health.as_dict(),
        "scan_errors": scan_errors,
        "semantic_skim": skim,
        "deep_inspection": deep,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Installornot inventory scan")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--candidate-path", type=str)
    src.add_argument("--candidate-text", type=str)
    p.add_argument("--kind", choices=["auto", "skill", "mcp", "plugin"], default="auto")
    p.add_argument("--catalogs", choices=["local", "live", "off"], default="local")
    p.add_argument("--claude-config-dir", type=str, default=None)
    p.add_argument("--codex-home", type=str, default=None)
    p.add_argument("--cwd", type=str, default=None)
    p.add_argument("--show-absolute-paths", action="store_true")
    return p.parse_args(argv)


def config_from_args(args: argparse.Namespace) -> Config:
    home = Path(os.environ.get("HOME") or str(Path.home())).expanduser()
    claude = Path(
        args.claude_config_dir
        or os.environ.get("CLAUDE_CONFIG_DIR")
        or (home / ".claude")
    ).expanduser()
    codex = Path(
        args.codex_home
        or os.environ.get("CODEX_HOME")
        or (home / ".codex")
    ).expanduser()
    cwd = Path(args.cwd or os.getcwd()).expanduser()
    return Config(
        claude_dir=claude,
        codex_home=codex,
        cwd=cwd,
        home=home,
        catalogs=args.catalogs,
        show_absolute=args.show_absolute_paths,
        kind=args.kind,
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cfg = config_from_args(args)
    path: Path | None = None
    text: str | None = None
    if args.candidate_path:
        path = Path(args.candidate_path).expanduser()
    else:
        if args.candidate_text == "-":
            text = sys.stdin.read()
        else:
            text = args.candidate_text
        if text is None:
            return 2
        if len(text.encode("utf-8")) > MAX_CANDIDATE_TEXT:
            print("candidate exceeds maximum size", file=sys.stderr)
            return 2
    try:
        report = build_report(cfg, path, text)
    except CandidateError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    json.dump(report, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
