# Status

**Phase:** v1 implemented; copied onto this machine; unit tests passing.

**Completed**

- Spec at `docs/spec.md` (successor to the 2026-08-18 skill-vet design).
- Stdlib `skill/scripts/inventory.py` with Claude/Codex adapters, MCP/plugin candidates, compatibility, local/live catalogs.
- Agent protocol in `skill/SKILL.md`.
- Isolated `unittest` suite (`python3 -m unittest tests.test_inventory`) — 32 passing.
- README / LICENSE / `ai_agent.md` / `docs/decisions.md`.
- Copied `skill/` to `~/.claude/skills/installornot` and `~/.codex/skills/installornot` (directories, not symlinks).
- Smoke: existing `graphify` → `exact_name` shortlist, 29 broken-symlink health entries; uninstalled marketplace plugin `ralph-loop` → `works`, empty shortlist, local catalogs from 2 sources.

**Next**

- Public git remote when the maintainer wants it published.
- Cursor adapter (deferred).
- Optional v2 hook around Claude `/plugin install` and Codex `skill-installer`.
