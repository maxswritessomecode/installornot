agent_tool: Cursor
agent_model: Cursor Grok 4.6
agent_config_path: ~/.cursor/
created_date: 2026-08-31
purpose: Public pre-install checker for Claude Code and Codex CLI skills, MCPs, and plugins.

# Contributors (agents)
# Original author is the agent above. Later agent sessions are recorded here so a
# Cursor session can see what changed hands and read docs/decisions.md for the why.
- agent_tool: Claude Code
  agent_model: Claude Sonnet 5.5 (claude-sonnet-5-5)
  agent_config_path: ~/.claude/
  worked_on: 2026-10-11
  scope: v0.2.0 review and hardening (MCP discovery, hook overlap, bundled-text scan, wider shortlist). See docs/decisions.md entry "2026-10-11".
