# Status

**Phase:** v1 shipped; install path simplified 2026-09-01.

**Completed**

- Spec at `docs/spec.md`.
- Stdlib scanner at `skills/installornot/scripts/inventory.py`.
- Agent protocol in `skills/installornot/SKILL.md`.
- Isolated tests (`python3 -m unittest tests.test_inventory tests.test_install`).
- Public repo: https://github.com/maxswritessomecode/installornot
- One-command install: `npx skills add maxswritessomecode/installornot -g --copy -y` or `install.sh`.
- Claude marketplace manifest at `.claude-plugin/`.

**Next**

- Cursor adapter (deferred).
- Optional v2 hook around Claude `/plugin install` and Codex `skill-installer`.
