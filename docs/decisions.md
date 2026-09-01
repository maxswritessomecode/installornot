# Decisions

## 2026-08-31 — Public name is installornot, not skill-vet

The Aug 18 design used `skill-vet`. The shipping product covers skills, MCPs, and plugins, and the repo folder is `installornot`. Keep that name in the skill frontmatter, CLI version string, and install path.

## 2026-08-31 — Copy install, never default to symlink

29 of 37 entries in a real `~/.claude/skills/` were dangling symlinks after a target move. Public docs tell people to `cp -R skill …/installornot`. Symlink is a documented development option only.

## 2026-08-31 — Stdlib only at runtime

No PyPI dependency for the scanner. Catalog live-fetch uses `urllib`. Tests use `unittest` so `python3 -m unittest` works without pytest.

## 2026-08-31 — Live catalogs are allowlisted and opt-in

`--catalogs local` is the default (on-disk marketplace clones). `--catalogs live` may GET only the two URLs listed in `docs/spec.md`. Catalog payloads are untrusted data. No Smithery crawl.

## 2026-08-31 — Self-exclusion must not wipe personal skills

When the script is copied to `~/.claude/skills/installornot/scripts/inventory.py`, the parent of the skill dir is the personal skills root. Only exclude the development repo when the path is `<repo>/skill/scripts/inventory.py`. Always exclude the skill directory that contains this script.

## 2026-08-31 — Project discovery skips harness config dirs

Walking ancestors for `.claude/skills` from a cwd under `$HOME` would otherwise re-scan `~/.claude/skills` as a "project" root and double-count broken-symlink health. Skip roots that resolve to `$CLAUDE_CONFIG_DIR/skills` or `$CODEX_HOME/skills`.

## 2026-08-31 — Cursor adapter deferred

Discovery is split into Claude and Codex adapters so a Cursor adapter can be added later without changing the verdict protocol.
