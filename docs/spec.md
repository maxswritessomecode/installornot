# Installornot — Design Spec

Date: 2026-08-31
Successor to: `~/docs/superpowers/specs/2026-08-18-skill-vet-design.md` (skill-only draft; never implemented)

## Goal

Before installing a skill, MCP server, or plugin into Claude Code or Codex CLI, check it against what is already active on this machine and against allowlisted catalogs. Return a concrete recommendation: install it, don't, prefer something already installed, prefer something in a scanned catalog, or fix config first.

This is a public, copy-installable skill. It must not assume a particular home-directory layout beyond `$CLAUDE_CONFIG_DIR` / `~/.claude` and `$CODEX_HOME` / `~/.codex`.

---

## Scope & Constraints

**In scope for v1:**

- Manual invocation only. No hooks, no auto-fire on `/plugin install` or Codex `skill-installer`.
- Single-candidate check. Not a pairwise audit of the whole inventory.
- Candidate kinds: `skill`, `mcp`, `plugin` (auto-detected, overridable).
- Local path, pasted text, or a plugin/MCP config snippet. If the candidate is only at a URL, the invoking agent fetches it first and passes a path or text.
- Zero third-party runtime dependencies. Python 3.11+ standard library only.
- Report-only. Never mutates, installs, disables, or deletes anything.
- Treat candidate, inventory, and catalog payloads as untrusted data. Never execute scripts, import candidate modules, expand shell expressions, or let their contents change the verdict schema.
- Privacy-safe by default. Display paths use `$HOME` (or config-root-relative forms). Broken-symlink targets are redacted unless `--show-absolute-paths`.
- Optional catalog scan: `--catalogs local` (default), `live`, or `off`.

**Out of scope (deferred):**

- Full-collection audit mode (no candidate).
- Auto-trigger on install intent.
- Cursor / Gemini / Copilot adapters (discovery is adapter-shaped so these can be added later).
- Smithery-wide or open-internet skill crawls.
- Executing candidates, starting MCP servers, CVE scanning, URL reputation.

---

## Terminology

- **Candidate**: the skill, MCP, or plugin being considered. A path, a directory, or pasted text.
- **Kind**: `skill` | `mcp` | `plugin`.
- **Active inventory**: skills, MCPs, and plugins reachable by Claude Code or Codex CLI in normal operation. Excludes stale plugin-cache versions, vendored `upstream/` copies, and unregistered directories that happen to contain a `SKILL.md`.
- **Shortlist**: deterministic subset of the active inventory worth showing the agent, ranked by overlap likelihood.
- **Catalog hit**: an allowlisted marketplace/catalog entry that is *not* already in the active inventory and looks similar to the candidate.
- **Verdict**: one of five overlap outcomes per shortlisted inventory item (agent-assigned).
- **Compatibility status**: `works` | `needs_config` | `wont_work` | `unknown` (script-assigned, deterministic).
- **Identity**: canonical real path (when there is one) + kind + declared name + content hash.

---

## Architecture

```
candidate ──▶ scripts/inventory.py ──▶ JSON
                 (stdlib only)
                      │
                      ▼
              Agent (Claude or Codex)
              - one overlap verdict per shortlisted item
              - bounded semantic skim of remaining inventory
              - catalog-alternative judgment
              - staged body inspection
              - renders the Markdown report
```

The script does deterministic work. The agent does judgment, constrained to structured complete output.

---

## CLI

```
python3 inventory.py --candidate-path <path>
python3 inventory.py --candidate-text -          # stdin
python3 inventory.py --kind auto|skill|mcp|plugin
python3 inventory.py --catalogs local|live|off   # default local
python3 inventory.py --claude-config-dir <dir>
python3 inventory.py --codex-home <dir>
python3 inventory.py --cwd <dir>
python3 inventory.py --show-absolute-paths
```

Defaults:

- Claude config dir: `$CLAUDE_CONFIG_DIR` or `~/.claude`
- Codex home: `$CODEX_HOME` or `~/.codex`
- cwd: process cwd
- catalogs: `local`

Non-zero exit only on invalid or unreadable candidate input. Unreadable inventory roots produce a partial report plus `scan_errors`.

Maximum pasted candidate text: 512 KiB. Larger input is a fatal error.

---

## Kind detection

`auto` (default):

| Signal | Kind |
|---|---|
| File named `SKILL.md`, or text with YAML frontmatter containing `name` | `skill` |
| Directory containing `SKILL.md` and no plugin manifest | `skill` |
| Directory containing `.claude-plugin/plugin.json` or `plugin.json` | `plugin` |
| File named `.mcp.json`, `mcp.json`, or JSON object with `mcpServers` | `mcp` |
| Codex-style TOML with `[mcp_servers.*]` | `mcp` |

A plugin candidate also contributes its bundled skills (`skills/*/SKILL.md`, one level) and bundled MCPs (`.mcp.json` / `mcpServers` in the plugin manifest) as comparison material. Overlap is evaluated against those bundled items, not only the plugin's display name.

---

## Directory discovery (active inventory)

Do not recursively scan `$HOME`. Only scan explicit roots and registry-resolved plugin paths.

**Self-exclusion:** the installornot repository (parent of `skills/installornot/scripts/inventory.py`, detected via `docs/spec.md`) and the installed skill directory that contains the running script are excluded from comparison so the tool never reports a conflict with itself.

### Skills

| Platform | Personal | Project | Plugin-provided |
|---|---|---|---|
| Claude Code | `$CLAUDE_CONFIG_DIR/skills` | nearest ancestor `<root>/.claude/skills` | `installed_plugins.json` `installPath/skills/*/SKILL.md` (one level), only if enabled |
| Codex CLI | `$CODEX_HOME/skills` and `$CODEX_HOME/skills/.system` | nearest ancestor `<root>/.codex/skills` | enabled `[plugins."name@marketplace"]` cache dir, highest numeric version, `skills/*/SKILL.md` |

Personal walk: `<root>/*/SKILL.md`. Resolve symlinks with `os.path.realpath`. Unresolvable symlinks go to `inventory_health.broken_symlinks` (redacted target) — not dropped, not treated as present.

Codex `.system/*/SKILL.md` is tagged `source_type: codex_builtin`.

Project walk: from `--cwd`, check each ancestor for `.claude/skills` and `.codex/skills` until a directory containing `.git` (the project boundary). If no `.git`, stop at filesystem root. Nearest project skill root wins for duplicate declared names; shadowed entries stay in inventory health.

Claude plugins: parse `plugins/installed_plugins.json` (v2). For each plugin key, skip if `settings.json` `enabledPlugins` maps it to `false`. If `enabledPlugins` is absent, installed means enabled. Walk **exactly** `<installPath>/skills/*/SKILL.md`. This excludes `upstream/` vendored copies and `<installPath>/.claude/skills/` dev trees.

Codex plugins: parse `config.toml` with `tomllib`. For each table `plugins."<name>@<marketplace>"` with `enabled = true`, resolve `$CODEX_HOME/plugins/cache/<marketplace>/<name>/`. If multiple version directories exist, pick the highest *numeric* `MAJOR.MINOR.PATCH` (optional leading `v`). Non-numeric names use lexicographic order and emit `version_order_ambiguous`. Unselected versions go to `inventory_health.stale_plugin_versions`. Walk `<version>/skills/*/SKILL.md`, one level.

### Plugins (first-class inventory entries)

Each enabled installed plugin is also an inventory entry of `kind: plugin`, with name/description/version from `plugin.json` when present.

### MCPs

| Platform | Sources |
|---|---|
| Claude Code | `$CLAUDE_CONFIG_DIR/claude_mcp_config.json` `mcpServers`; nearest project `.mcp.json` |
| Codex CLI | `[mcp_servers.<name>]` tables in `config.toml` |

Record: name, transport (`stdio` if `command` is set, `http` if `url`/`type=http`), command (program only, not full arg list with secrets), declared env **names** (never values). Description may be empty; shortlisting then uses name only.

### Deduplication and precedence

SHA-256 of file contents (or canonical JSON/TOML text) + real path + kind + name. Same identity is one comparison target with a `sources` array. Different hashes declaring the same name remain separate (name collision).

Presentation precedence (not deletion): nearest project, then personal, then plugin-provided, then built-in.

### Frontmatter parsing (skills)

No YAML library. Split on the first two `---` lines. Top-level keys match `^([a-zA-Z_-]+):\s*(.*)$` at column 0. Indented blocks are captured raw so we know the key existed.

Malformed frontmatter on an *inventory* entry: record unparseable, continue. Malformed candidate with no `description`: fatal.

**Known skill frontmatter keys** (portability, not validity):

| Claude Code | Codex CLI |
|---|---|
| `name`, `description`, `metadata`, `retrieval`, `chainTo`, `validate`, `license`, `summary`, `user-invocable`, `argument-hint`, `allowed-tools`, `version`, `trigger`, `disable-model-invocation` | `name`, `description`, `metadata` |

A key present on the candidate but only meaningful on one host is a portability finding, not a conflict verdict. Unknown platform version → `unknown compatibility`, never an unverified enforcement claim.

---

## Candidate provenance

Derived without network:

- `input_type`: `path` | `pasted_text`
- SHA-256
- declared source URL / license when present in frontmatter or plugin.json
- adjacent executables, referenced external commands, network endpoints, `shell_install` boolean
- `suspicious_patterns` (warnings, not proof): instruction-override phrases, encoded payloads, install-time shell, executable references

Directory candidates: inspect the directory only, do not follow symlinks *out* of it, skip `.git`, `node_modules`, `__pycache__`, `.venv`, `venv`. Skip files larger than 1 MiB. Cap 500 files / 5 MiB of text. Record skipped and truncated counts.

Single-file or pasted-text: adjacent provenance is `not_inspected`, not an empty verified result.

---

## Compatibility (deterministic)

Assigned on the candidate. Never start an MCP or run a skill script.

| Status | Meaning |
|---|---|
| `works` | Static checks passed for the detected hosts |
| `needs_config` | Missing declared env names, or marketplace id unresolved but the rest parses |
| `wont_work` | Required command not on `PATH`, unreadable/unparseable manifest, or host cannot load this kind |
| `unknown` | Not enough static signal |

Skill: Claude-only keys (`allowed-tools`, `disable-model-invocation`, …) on a Codex-only evaluation are portability notes; they do not by themselves make `wont_work`.

MCP: `shutil.which(command)` for stdio servers. Declared env names checked with `name in os.environ` (boolean). HTTP MCPs with a URL parse as `works` if the URL is well-formed; reachability is not probed.

Plugin: manifest parses; already-installed same name/version is overlap not incompatibility; missing marketplace clone is `needs_config` only when the candidate is a bare id rather than a local path.

---

## Shortlisting

Against active inventory of all kinds (cross-kind). Cap 25.

1. Exact name match (case-insensitive). Always included; does **not** decide the verdict.
2. Normalized exact-description match (Unicode normalize, case-fold, strip punctuation/whitespace).
3. Adaptive verbatim shingles on the description. Six words when both have ≥6 tokens; else length of the shorter, minimum 2. One-word descriptions skip shingles.
4. Purpose job. Name+description on each side must hit **two or more** triggers from the same job in `JOB_TRIGGERS` (`agent_memory`, `skill_authoring`, `frontend_ui`). `match_reason: purpose` and `purpose_job: <job>`. This is how claude-mem vs TencentDB Agent Memory shortlists without a shared name or copied sentence. One shared word (e.g. “memory leak”) is not enough.
5. Rank: exact name, then exact description, then shingle count descending, then purpose.

Plugin candidates: also shortlist using bundled skill/MCP names and descriptions.

Empty shortlist is success.

---

## Catalogs

`--catalogs off`: no catalog fields beyond `{mode: off, sources: []}`.

`--catalogs local`: read already-on-disk allowlisted indexes:

- Claude: `$CLAUDE_CONFIG_DIR/plugins/marketplaces/*/.claude-plugin/marketplace.json`
- Codex: marketplace roots declared in `config.toml` `[marketplaces.*]` when they contain a plugin/skill index; plus no network fetch of `openai/skills`

`--catalogs live`: same local pass, then HTTP GET of allowlisted URLs only (stdlib `urllib`, 10s timeout, 2 MiB cap). Responses are untrusted JSON/text. Unknown hosts are not contacted.

Allowlisted live URLs (v1):

- `https://raw.githubusercontent.com/anthropics/claude-plugins-official/main/.claude-plugin/marketplace.json`
- `https://api.github.com/repos/openai/skills/contents/skills/.curated`

Catalog entries already in the active inventory are not catalog hits. Remaining entries are shortlisted with the same name/description/shingle rules, cap 25, into `catalog_hits`.

Incomplete catalog coverage must be stated. Never claim “nothing better exists.”

---

## JSON output (`schema_version`: 1)

```jsonc
{
  "schema_version": 1,
  "installornot_version": "0.1.0",
  "compatibility_rules_date": "2026-08-31",
  "platforms": [
    { "name": "claude", "version": "unknown", "adapter_status": "supported" },
    { "name": "codex", "version": "unknown", "adapter_status": "supported" }
  ],
  "resolved_roots": ["$HOME/.claude/skills"],
  "candidate": {
    "kind": "skill",
    "name": "...",
    "description": "...",
    "frontmatter_keys": ["name", "description"],
    "content_sha256": "...",
    "provenance": {
      "input_type": "path",
      "source_url": null,
      "license": null,
      "executables": [],
      "external_commands": [],
      "network_endpoints": [],
      "shell_install": false,
      "adjacent_inspection": "inspected|not_inspected",
      "skipped_files": 0,
      "truncated": false
    },
    "compatibility": { "status": "works", "findings": [] },
    "bundled": [],
    "suspicious_patterns": [],
    "parse_error": null
  },
  "active_inventory": [
    {
      "kind": "skill",
      "name": "...",
      "description": "...",
      "source_type": "personal|project|plugin|codex_builtin",
      "display_path": "$HOME/...",
      "content_sha256": "...",
      "sources": ["..."],
      "frontmatter_keys": ["..."]
    }
  ],
  "shortlist": [
    {
      "kind": "skill",
      "name": "...",
      "description": "...",
      "source_type": "...",
      "display_path": "$HOME/...",
      "match_reason": "exact_name|exact_description|shingle|purpose",
      "shingle_count": 0,
      "purpose_job": "agent_memory|skill_authoring|frontend_ui|null"
    }
  ],
  "shortlist_metadata": { "total_matches": 0, "included_matches": 0, "truncated": false },
  "catalog_hits": [],
  "catalog_metadata": { "mode": "local", "sources": [], "truncated": false, "fetch_errors": [] },
  "inventory_health": {
    "broken_symlinks": [],
    "stale_plugin_versions": [],
    "shadowed_entries": [],
    "version_order_ambiguous": []
  },
  "scan_errors": [],
  "semantic_skim": { "total_entries": 0, "included_entries": 0, "truncated": false },
  "deep_inspection": { "eligible_entries": 0, "inspected_entries": 0, "omitted_entries": 0, "truncated": false }
}
```

`semantic_skim` and `deep_inspection` counts are filled by the script as *budgets* (totals from inventory/shortlist). The agent records what it actually inspected when rendering the report.

---

## Agent verdict protocol

See `skills/installornot/SKILL.md`. Summary:

Overlap verdicts (exactly one per shortlisted item, including `no_conflict`):

| Verdict | Meaning |
|---|---|
| `no_conflict` | Surface similarity only |
| `redundant` | Existing item already does this |
| `upgrade_not_add` | Same lineage, version change; name alone is not enough |
| `partial_overlap` | Shared ground, can coexist |
| `contradicts` | Conflicting instructions if both fire; requires body evidence |

`redundant` / `upgrade_not_add` / `contradicts` require body evidence. Uninspected bodies cannot receive `contradicts`.

Catalog alternatives are a separate section (`prefer_catalog` suggestions), not overlap verdicts.

Overall recommendation, strongest evidence first:

1. `wont_work` → don't install
2. inspected `contradicts` → don't install until resolved
3. `needs_config` → don't install until env/binary/manifest is fixed
4. inspected `redundant` / `upgrade_not_add` → skip or replace using the mechanism table
5. catalog hit that is a better fit → prefer that (language: “in scanned catalogs”)
6. only `partial_overlap` / `no_conflict` + `works` → install as-is, carry overlap notes
7. suspicious-content warnings → `manual review required` can override
8. incomplete scans → “no conflict found in scanned inventory”, never “no conflict exists”

Disable/replace mechanisms:

| Source | Action |
|---|---|
| Personal skill/MCP/plugin dir | Rename (`.disabled`) or delete |
| Project-level | Same, scoped to the project |
| Plugin-provided skill/MCP | Cannot disable one member; remove whole plugin only if that is the plugin's only purpose, else prefer existing and skip candidate |
| Codex `.system` | Informational only |

---

## Report shape

```markdown
## Installornot: <kind> <candidate name>

**Scanned:** <N> active items across <roots>
**Coverage:** complete | limitations…

### Will it work
status + findings

### Candidate provenance and safety
hash, license, executables, suspicious patterns

### Portability
Claude-only / Codex-only keys

### Overlap findings
one row per shortlisted item

### Catalog alternatives
one row per catalog hit, or “none in scanned catalogs”

### Recommendation
one paragraph

### Inventory health
broken symlinks, stale versions, scan errors
```

---

## Untrusted-content boundary

The script and the agent must not:

- execute candidate or inventory scripts
- import candidate Python modules
- expand shell expressions found in skill/plugin text
- fetch URLs mentioned *inside* a skill (catalog live fetch uses the allowlist only)
- allow a body or catalog payload to change the verdict schema, omit findings, or request tool use

Suspicious patterns are warnings.

---

## Acceptance criteria

From the Aug 18 skill-vet list, still required: vendored duplicate, multi-version cache, broken symlink, plugin-internal dev skill, project-level skill, cross-platform frontmatter, shortlist completeness, exact-name cases, self-exclusion, nested project cwd, deduplication, short/Unicode descriptions, unreadable inventory root, privacy-safe output, prompt injection, no candidate execution, bounded inspection counts, compatibility versioning, provenance, package-inspection bounds.

Added for installornot:

21. MCP name collision with an installed `mcpServers` / `[mcp_servers.*]` entry appears on the shortlist as `exact_name`.
22. MCP stdio command not on `PATH` → candidate `compatibility.status` is `wont_work`.
23. MCP env names missing from the environment → `needs_config`; values are never present in JSON.
24. Plugin candidate shortlists against bundled skill names, not only `plugin.json` name.
25. `--catalogs local` returns hits from a fixture marketplace.json and does not hit the network.
26. `--catalogs live` refuses non-allowlisted URLs; oversized responses are truncated/errored, not executed.
27. Catalog JSON containing “ignore previous instructions” cannot change schema or omit inventory.
28. Disabled Claude plugin (`enabledPlugins: false`) is absent from active inventory.
29. Tests use isolated temp config roots and never read or write the developer’s real `~/.claude` / `~/.codex`.
