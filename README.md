# Installornot

Pre-install checker for **Claude Code** and **Codex CLI**. Before you add a skill, MCP server, or plugin, it inventories what is already active, reports whether the candidate will run, whether it conflicts, and whether a better match is already installed or sitting in a scanned catalog.

Report-only. It never installs, disables, or deletes anything. Python 3.11+ standard library only — no pip packages, no model downloads.

## Install (copy, do not symlink)

Symlinks break when the clone moves. Copy the `skill/` directory into the host skill root and rename it `installornot`:

**Claude Code**

```bash
cp -R skill "$HOME/.claude/skills/installornot"
```

If you use `CLAUDE_CONFIG_DIR`, copy into `"$CLAUDE_CONFIG_DIR/skills/installornot"` instead.

**Codex CLI**

```bash
cp -R skill "$HOME/.codex/skills/installornot"
```

If you use `CODEX_HOME`, copy into `"$CODEX_HOME/skills/installornot"` instead.

After copying, start a new session (or a new turn) so the host can see the skill.

## Use

Ask the agent to vet a candidate, or run the scanner yourself:

```bash
python3 skill/scripts/inventory.py --candidate-path ./path/to/SKILL.md
python3 skill/scripts/inventory.py --candidate-path ./path/to/plugin-dir
python3 skill/scripts/inventory.py --candidate-path ./mcp.json --kind mcp
python3 skill/scripts/inventory.py --catalogs local   # default; on-disk marketplaces only
python3 skill/scripts/inventory.py --catalogs live    # allowlisted HTTP catalogs
python3 skill/scripts/inventory.py --catalogs off
```

The script prints one JSON object. The skill (`SKILL.md`) tells the agent how to turn that into a recommendation.

`--catalogs live` only requests:

- `https://raw.githubusercontent.com/anthropics/claude-plugins-official/main/.claude-plugin/marketplace.json`
- `https://api.github.com/repos/openai/skills/contents/skills/.curated`

Candidate URLs are not fetched by the script. If the thing you want to install is only on the network, fetch it first and pass a path or `--candidate-text -`.

## What it checks

1. **What you have** — skills, MCPs, and plugins actually reachable by Claude Code or Codex, not a recursive home-directory glob of `SKILL.md` files.
2. **Will it work / will it conflict** — command on `PATH`, declared env *names* present (values are never printed), frontmatter portability, name/description overlap.
3. **Do you need it** — skip if something active already covers it; otherwise suggest a better match from scanned catalogs.

## Tests

```bash
python3 -m unittest tests.test_inventory
```

Tests build throwaway config trees. They do not read or write your real `~/.claude` or `~/.codex`.

## Spec

See [docs/spec.md](docs/spec.md).
