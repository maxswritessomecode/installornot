# Decisions

## 2026-08-31 — Public name is installornot, not skill-vet

The Aug 18 design used `skill-vet`. The shipping product covers skills, MCPs, and plugins, and the repo folder is `installornot`. Keep that name in the skill frontmatter, CLI version string, and install path.

## 2026-08-31 — Copy install, never default to symlink

29 of 37 entries in a real `~/.claude/skills/` were dangling symlinks after a target move. Public install uses copy (`npx skills add … --copy` and `install.sh`), not symlink.

## 2026-08-31 — Stdlib only at runtime

No PyPI dependency for the scanner. Catalog live-fetch uses `urllib`. Tests use `unittest` so `python3 -m unittest` works without pytest.

## 2026-08-31 — Live catalogs are allowlisted and opt-in

`--catalogs local` is the default (on-disk marketplace clones). `--catalogs live` may GET only the two URLs listed in `docs/spec.md`. Catalog payloads are untrusted data. No Smithery crawl.

## 2026-08-31 — Self-exclusion must not wipe personal skills

When the script is copied to `~/.claude/skills/installornot/scripts/inventory.py`, the parent of the skill dir is the personal skills root. Only exclude the development repo when the path is `<repo>/skills/installornot/scripts/inventory.py` (detected via sibling `docs/spec.md`). Always exclude the skill directory that contains this script.

## 2026-08-31 — Project discovery skips harness config dirs

Walking ancestors for `.claude/skills` from a cwd under `$HOME` would otherwise re-scan `~/.claude/skills` as a "project" root and double-count broken-symlink health. Skip roots that resolve to `$CLAUDE_CONFIG_DIR/skills` or `$CODEX_HOME/skills`.

## 2026-08-31 — Cursor adapter deferred

Discovery is split into Claude and Codex adapters so a Cursor adapter can be added later without changing the verdict protocol.

## 2026-09-01 — Purpose shortlist for same-job different names

Name match and 6-word shingles miss products that do the same job in different words (claude-mem vs TencentDB Agent Memory). The scanner stays stdlib-only: a small job-trigger table, two hits per side. The script still does not assign `redundant` / `partial_overlap`; it only puts the row on the shortlist as `match_reason: purpose`.

## 2026-09-01 — One-command install, standard `skills/` layout

`npx skills add` only discovers `skills/<name>/SKILL.md` (or repo-root `SKILL.md`). The old `skill/` directory was invisible to that CLI. Moved the payload to `skills/installornot/` and added `install.sh` plus a Claude marketplace manifest. Public install prefers `npx skills add … -g --copy -y` or `curl …/install.sh | bash`. `--copy` stays the default so we do not recreate the dangling-symlink failure mode.
