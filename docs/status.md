# Status

**Phase:** v0.2.0 hardening done locally (review fixes); not yet pushed or installed.

**Completed**

- Spec at `docs/spec.md`.
- Stdlib scanner at `skills/installornot/scripts/inventory.py`.
- Agent protocol in `skills/installornot/SKILL.md`.
- Isolated tests (`python3 -B -m unittest tests.test_inventory tests.test_install`), 58 passing.
- Public repo: https://github.com/maxswritessomecode/installornot
- One-command install: `npx skills add maxswritessomecode/installornot -g --copy -y` or `install.sh` (`--claude-only` available).
- Claude marketplace manifest at `.claude-plugin/`.
- 2026-10-11 review fixes: real MCP files, hook overlap, full-text candidate scan, wider purpose shortlist, settings layering, copy dedupe, version probe. See `docs/decisions.md`.

**Next**

- Commit and push v0.2.0 (needs owner go-ahead).
- Install copy to `~/.claude/skills/installornot` and run the end-to-end check from a fresh session.
- Cursor adapter (deferred).
- Optional v2 hook around Claude `/plugin install` and Codex `skill-installer`.
