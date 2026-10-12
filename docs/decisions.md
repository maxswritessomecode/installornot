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

## 2026-10-11 — Review fixes: inventory what actually conflicts (v0.2.0)

A dry run on a real machine showed v0.1.0 missed the conflicts that mattered. Changes, each with a test:

- **MCP discovery reads Claude's real state file.** `~/.claude.json` (or `$CLAUDE_CONFIG_DIR/.claude.json`): top-level `mcpServers` plus `projects.<cwd or ancestor>.mcpServers`. Only server name, command/url and env *names* are read. `claude_mcp_config.json` is kept for back-compat. Plugin-bundled MCPs (`.mcp.json`, `plugin.json#mcpServers`) are inventoried too.
- **Hooks are compared, not inventoried.** Two plugins hooking the same event both fire (the claude-mem vs remember case). A `hook_overlap` section lists shared events and owners, including hooks in `settings.json` layers. Hooks are not shortlist rows because many plugins share events and one-verdict-per-row would drown the report.
- **Commands and agents are inventory kinds.** Plugin ones are namespaced `plugin:name` (that is how they are invoked), so only personal/project commands collide by bare name. A candidate skill named like an installed command is an exact-name hit.
- **Plugin and directory candidates are scanned in full.** Bundled `SKILL.md` bodies, hooks, scripts and other text files (existing size/count/symlink bounds) feed suspicious-pattern, command, URL and new `risky_actions` checks (git push/commit, osascript, sudo, scheduler, agent-config edits, package installs). Before, only `plugin.json` was scanned. Nothing is executed.
- **Shortlist: bigger job table plus `similar_text`.** `JOB_TRIGGERS` now covers 11 jobs described by what they do, not product names. A stdlib Jaccard ranker (>=4 shared content tokens, >=0.20) catches reworded same-job pairs. Still deterministic, no embeddings.
- **Settings layering.** `enabledPlugins` and `hooks` are read from user, user-local and every project ancestor's `.claude/settings*.json`; nearer wins.
- **Dedupe by (kind, name, content hash)**, so one skill copied to `~/.claude`, `~/.codex` and `~/.agents` is one entry with several sources. Same name with different content stays separate. `~/.agents/skills` is now scanned (install.sh writes there).
- **Platform version probe** (`claude --version`, `codex --version`, 3 s timeout, best effort). Unknown version now yields `adapter_status: unknown` and a `warnings` entry instead of a hard-coded "supported". `INSTALLORNOT_NO_VERSION_PROBE=1` turns it off (tests set it).
- **`deep_inspection` counts the whole shortlist**, since any entry can end in an action-bearing verdict.
- **Frontmatter**: folded/literal scalars (`>-`, `|`) and quotes collapse to plain text; CRLF handled.
- **SKILL.md** gains Step 3b (hook overlap, risky actions, and a check of the user's own CLAUDE.md/AGENTS.md rules) and a compact report format. Rule comparison is agent work on purpose: rules are free text.
- **install.sh** gains `--claude-only`; unknown flags are rejected; dead `-z` check removed. Default stays all three dirs for public users.

## 2026-10-11 — Pairwise compare mode (`--compare-path`)

Asking "check these two plugins" previously gave two independent reports and no A-vs-B result. The script now accepts a second candidate and returns `compare`: B's own record, A matched against B (reusing `shortlist()` by shaping B and its bundled items like inventory rows), hook-event overlap between them, and B checked against the installed set. The agent reports A vs installed, B vs installed, and A vs B separately so a conflict between the two is never hidden by neither conflicting with the machine. Same path twice, or a missing second path, is fatal. SKILL.md also now tells the agent to `git clone --depth 1` URLs into a temp dir (a single page fetch misses bundled hooks/scripts) and never into a skills dir.
