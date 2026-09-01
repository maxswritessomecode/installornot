# Installornot

You found a skill or an MCP. Before you dump it into Claude Code or Codex, point this at the files.

It answers three questions, in this order:

1. Will it even run on this machine? (binary on `PATH`, required env *names* present — not values, not a live ping)
2. Does it collide with something you already have?
3. Do you already have something that does the same job?

It never installs, disables, or deletes anything. Python 3.11. No pip.

## Check a candidate

After install, from anywhere:

```bash
# skill
python3 ~/.claude/skills/installornot/scripts/inventory.py --candidate-path ./SKILL.md

# MCP config
python3 ~/.claude/skills/installornot/scripts/inventory.py --candidate-path ./mcp.json

# plugin directory (plugin.json / .claude-plugin/)
python3 ~/.claude/skills/installornot/scripts/inventory.py --candidate-path ./some-plugin
```

Or, in a Claude Code / Codex session, drop the path and ask:

> Will this work with what I already have?

Read **Will it work** in the report: `works`, `needs_config`, or `wont_work`. Missing `uv` or `npx` is `wont_work`. An env var name that isn't set is `needs_config`. We do not start the server to find out.

If the thing is only a URL, fetch it first. This script will not.

## Install

```bash
npx skills add maxswritessomecode/installornot -g --copy -y
```

No Node:

```bash
curl -fsSL https://raw.githubusercontent.com/maxswritessomecode/installornot/master/install.sh | bash
```

`--copy` on purpose. Symlinks to a clone that later moves is how you get a skills directory full of dead links.

Then start a new session (or a new turn).

Other ways (plugin marketplace, Codex skill-installer, `cp -R`) are in the details below if you need them.

<details>
<summary>Claude plugin, Codex installer, manual copy</summary>

```bash
claude plugin marketplace add maxswritessomecode/installornot
claude plugin install installornot@installornot
```

In Codex: install from `github.com/maxswritessomecode/installornot` path `skills/installornot`.

```bash
cp -R skills/installornot "$HOME/.claude/skills/installornot"
cp -R skills/installornot "$HOME/.codex/skills/installornot"
```

`CLAUDE_CONFIG_DIR` and `CODEX_HOME` override those homes.

</details>

## Tests

```bash
python3 -m unittest tests.test_inventory tests.test_install
```

Those tests build fake config dirs. They do not read yours.

Spec: [docs/spec.md](docs/spec.md)
