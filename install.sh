#!/usr/bin/env bash
# Copy installornot into Claude Code, Codex, and ~/.agents skill dirs.
# Copy, never symlink. Safe to re-run. Python 3.11+ required.
#   bash install.sh                 all three dirs (default)
#   bash install.sh --claude-only   only $CLAUDE_CONFIG_DIR/skills (or ~/.claude/skills)
set -euo pipefail

CLAUDE_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --claude-only) CLAUDE_ONLY=1 ;;
    -h|--help) sed -n '2,6p' "$0"; exit 0 ;;
    *) echo "installornot: unknown option: $arg" >&2; exit 2 ;;
  esac
done

REPO_SLUG="${INSTALLORNOT_REPO:-maxswritessomecode/installornot}"
REPO_REF="${INSTALLORNOT_REF:-master}"
SKILL_NAME="installornot"

need_python() {
  if ! command -v python3 >/dev/null 2>&1; then
    echo "installornot: python3 not found. Python 3.11+ is required." >&2
    exit 1
  fi
  if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
    echo "installornot: Python 3.11+ required (found $(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:3])))'))." >&2
    exit 1
  fi
}

copy_skill() {
  local src="$1" dest="$2"
  mkdir -p "$(dirname "$dest")"
  if [ -L "$dest" ]; then
    rm -f "$dest"
  fi
  rm -rf "$dest"
  cp -R "$src" "$dest"
  echo "installed $dest"
}

need_python

SCRIPT_DIR=""
if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi

SRC=""
CLEANUP=""
if [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/skills/${SKILL_NAME}/SKILL.md" ]; then
  SRC="$SCRIPT_DIR/skills/${SKILL_NAME}"
else
  tmp="$(mktemp -d)"
  CLEANUP="$tmp"
  archive="https://github.com/${REPO_SLUG}/archive/refs/heads/${REPO_REF}.tar.gz"
  echo "downloading ${archive}"
  curl -fsSL "$archive" | tar -xz -C "$tmp"
  extracted="$tmp/$(basename "$REPO_SLUG")-${REPO_REF}/skills/${SKILL_NAME}"
  if [ ! -f "$extracted/SKILL.md" ]; then
    echo "installornot: downloaded archive did not contain skills/${SKILL_NAME}/SKILL.md" >&2
    rm -rf "$CLEANUP"
    exit 1
  fi
  SRC="$extracted"
fi

HOME="${HOME:-$(python3 -c 'import pathlib; print(pathlib.Path.home())')}"
CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
CODEX_DIR="${CODEX_HOME:-$HOME/.codex}"

copy_skill "$SRC" "$CLAUDE_DIR/skills/$SKILL_NAME"
if [ "$CLAUDE_ONLY" -eq 0 ]; then
  copy_skill "$SRC" "$CODEX_DIR/skills/$SKILL_NAME"
  copy_skill "$SRC" "$HOME/.agents/skills/$SKILL_NAME"
fi

if [ -n "$CLEANUP" ]; then
  rm -rf "$CLEANUP"
fi

echo
echo "Done. New Claude Code or Codex session (or a new turn) so it loads."
echo "Then check a candidate:"
echo "  python3 ${CLAUDE_DIR}/skills/${SKILL_NAME}/scripts/inventory.py --candidate-path ./SKILL.md"
echo "  python3 ${CLAUDE_DIR}/skills/${SKILL_NAME}/scripts/inventory.py --candidate-path ./mcp.json"
