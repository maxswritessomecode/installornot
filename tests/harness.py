"""Build isolated Claude/Codex config trees for tests. Never touch the real homes."""

from __future__ import annotations

import json
import os
from pathlib import Path


def write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def skill_md(name: str, description: str, extra_keys: str = "") -> str:
    extra = f"\n{extra_keys.rstrip()}" if extra_keys else ""
    return (
        f"---\nname: {name}\ndescription: {description}{extra}\n---\n\n"
        f"# {name}\n\nBody for {name}.\n"
    )


def make_claude_home(root: Path, *, enabled: dict | None = None) -> Path:
    claude = root / ".claude"
    claude.mkdir(parents=True)
    write(
        claude / "settings.json",
        json.dumps({"enabledPlugins": enabled or {}}, indent=2),
    )
    write(claude / "claude_mcp_config.json", json.dumps({"mcpServers": {}}, indent=2))
    write(claude / "plugins" / "installed_plugins.json", json.dumps({"version": 2, "plugins": {}}, indent=2))
    (claude / "skills").mkdir()
    (claude / "plugins" / "cache").mkdir()
    (claude / "plugins" / "marketplaces").mkdir()
    return claude


def add_personal_skill(claude: Path, name: str, description: str, extra_keys: str = "") -> Path:
    return write(
        claude / "skills" / name / "SKILL.md",
        skill_md(name, description, extra_keys),
    )


def add_broken_symlink(claude: Path, name: str, target: str = "/nonexistent/installornot-missing") -> Path:
    link = claude / "skills" / name
    link.symlink_to(target)
    return link


def add_claude_plugin(
    claude: Path,
    *,
    key: str,
    install_path: Path,
    version: str = "1.0.0",
    enabled: bool = True,
) -> None:
    manifest = json.loads((claude / "plugins" / "installed_plugins.json").read_text())
    manifest["plugins"][key] = [
        {
            "scope": "user",
            "installPath": str(install_path),
            "version": version,
        }
    ]
    write(claude / "plugins" / "installed_plugins.json", json.dumps(manifest, indent=2))
    settings = json.loads((claude / "settings.json").read_text())
    settings.setdefault("enabledPlugins", {})[key] = enabled
    write(claude / "settings.json", json.dumps(settings, indent=2))


def add_plugin_skill(install_path: Path, name: str, description: str, *, upstream: bool = False) -> Path:
    rel = Path("skills") / name / ("upstream" if upstream else "") / "SKILL.md"
    if upstream:
        rel = Path("skills") / name / "upstream" / "SKILL.md"
    else:
        rel = Path("skills") / name / "SKILL.md"
    return write(install_path / rel, skill_md(name, description))


def add_plugin_manifest(install_path: Path, name: str, description: str, version: str = "1.0.0") -> Path:
    return write(
        install_path / ".claude-plugin" / "plugin.json",
        json.dumps({"name": name, "description": description, "version": version}, indent=2),
    )


def add_mcp(claude: Path, name: str, command: str, env_names: list[str] | None = None) -> None:
    cfg = json.loads((claude / "claude_mcp_config.json").read_text())
    entry: dict = {"command": command, "args": []}
    if env_names:
        entry["env"] = {k: f"secret-{k}" for k in env_names}
    cfg["mcpServers"][name] = entry
    write(claude / "claude_mcp_config.json", json.dumps(cfg, indent=2))


def add_marketplace(claude: Path, slug: str, plugins: list[dict]) -> Path:
    return write(
        claude / "plugins" / "marketplaces" / slug / ".claude-plugin" / "marketplace.json",
        json.dumps({"name": slug, "plugins": plugins}, indent=2),
    )


def make_codex_home(root: Path) -> Path:
    codex = root / ".codex"
    codex.mkdir(parents=True)
    write(codex / "config.toml", "model = \"test\"\n")
    (codex / "skills").mkdir()
    (codex / "skills" / ".system").mkdir()
    (codex / "plugins" / "cache").mkdir(parents=True)
    return codex


def add_codex_skill(codex: Path, name: str, description: str, *, system: bool = False) -> Path:
    base = codex / "skills" / ".system" / name if system else codex / "skills" / name
    return write(base / "SKILL.md", skill_md(name, description))


def add_codex_plugin(
    codex: Path,
    *,
    plugin: str,
    marketplace: str,
    versions: list[str],
    skill_name: str,
    description: str,
    enabled: bool = True,
) -> None:
    existing = (codex / "config.toml").read_text()
    existing += (
        f'\n[plugins."{plugin}@{marketplace}"]\n'
        f"enabled = {'true' if enabled else 'false'}\n"
    )
    write(codex / "config.toml", existing)
    cache = codex / "plugins" / "cache" / marketplace / plugin
    for ver in versions:
        add_plugin_skill(cache / ver, skill_name, description)
        add_plugin_manifest(cache / ver, plugin, description, ver)


def add_codex_mcp(codex: Path, name: str, command: str, env_names: list[str] | None = None) -> None:
    existing = (codex / "config.toml").read_text()
    existing += f"\n[mcp_servers.{name}]\ncommand = \"{command}\"\n"
    if env_names:
        existing += "[mcp_servers.{name}.env]\n".format(name=name)
        for k in env_names:
            existing += f'{k} = "secret-{k}"\n'
    write(codex / "config.toml", existing)


def make_project(root: Path, *, claude_skill: tuple[str, str] | None = None, git: bool = True) -> Path:
    proj = root / "project"
    proj.mkdir()
    if git:
        (proj / ".git").mkdir()
    if claude_skill:
        write(proj / ".claude" / "skills" / claude_skill[0] / "SKILL.md", skill_md(*claude_skill))
    (proj / "src" / "deep" / "path").mkdir(parents=True)
    return proj


def env_for(home: Path, claude: Path, codex: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["CLAUDE_CONFIG_DIR"] = str(claude)
    env["CODEX_HOME"] = str(codex)
    env.pop("INSTALLORNOT_CLAUDE_CONFIG_DIR", None)
    return env
