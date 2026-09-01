# Installornot

Before you install a skill, MCP, or plugin into **Claude Code** or **Codex**, check whether it will run, whether it conflicts with what you already have, and whether a better match is already sitting in a catalog.

Report-only. Python 3.11+, no pip packages.

## Install

One command. Copies into Claude Code and Codex (no symlinks):

```bash
npx skills add maxswritessomecode/installornot -g --copy -y
```

No Node? Same result:

```bash
curl -fsSL https://raw.githubusercontent.com/maxswritessomecode/installornot/master/install.sh | bash
```

Or tell the agent you already have:

> Install the skill from https://github.com/maxswritessomecode/installornot

Then start a new session (or a new turn).

<details>
<summary>Claude plugin, Codex skill-installer, manual copy</summary>

Claude Code plugin:

```bash
claude plugin marketplace add maxswritessomecode/installornot
claude plugin install installornot@installornot
```

Codex built-in installer (path basename is `installornot`):

```text
Install from github.com/maxswritessomecode/installornot path skills/installornot
```

Manual copy (`CLAUDE_CONFIG_DIR` / `CODEX_HOME` override the defaults):

```bash
cp -R skills/installornot "$HOME/.claude/skills/installornot"
cp -R skills/installornot "$HOME/.codex/skills/installornot"
```

</details>

## Use

Ask:

> Vet this before I install it

and pass a `SKILL.md`, a plugin directory, or an `mcp.json`. Or run the scanner:

```bash
python3 skills/installornot/scripts/inventory.py --candidate-path ./path/to/SKILL.md
python3 skills/installornot/scripts/inventory.py --candidate-path ./plugin-dir --kind plugin
python3 skills/installornot/scripts/inventory.py --catalogs local   # default
```

`--catalogs live` only requests the two allowlisted catalog URLs in the spec. The script does not fetch candidate URLs — fetch those first if needed.

## What it checks

1. **What you have** — skills, MCPs, and plugins the running harness can actually see.
2. **Will it work / will it conflict** — command on `PATH`, declared env *names* (never values), frontmatter portability, overlap.
3. **Do you need it** — skip if something active already covers it; otherwise suggest a better match from scanned catalogs.

## Tests

```bash
python3 -m unittest tests.test_inventory tests.test_install
```

Tests use throwaway config trees. They do not touch your real `~/.claude` or `~/.codex`.

## Spec

[docs/spec.md](docs/spec.md)
