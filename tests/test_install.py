"""install.sh copies into isolated homes. Never the real ~/.claude or ~/.codex."""

from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
INSTALL = REPO / "install.sh"


class TestInstallScript(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["HOME"] = str(self.home)
        env["CLAUDE_CONFIG_DIR"] = str(self.home / ".claude")
        env["CODEX_HOME"] = str(self.home / ".codex")
        return env

    def test_local_checkout_copies_not_symlink(self):
        proc = subprocess.run(
            ["bash", str(INSTALL)],
            capture_output=True,
            text=True,
            env=self._env(),
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        dest = self.home / ".claude" / "skills" / "installornot"
        self.assertTrue((dest / "SKILL.md").is_file())
        self.assertTrue((dest / "scripts" / "inventory.py").is_file())
        self.assertFalse(dest.is_symlink())
        self.assertTrue((self.home / ".codex" / "skills" / "installornot" / "SKILL.md").is_file())
        self.assertTrue((self.home / ".agents" / "skills" / "installornot" / "SKILL.md").is_file())
        self.assertNotIn("downloading", proc.stdout)

    def test_replaces_dangling_symlink(self):
        dest = self.home / ".claude" / "skills" / "installornot"
        dest.parent.mkdir(parents=True)
        dest.symlink_to("/nonexistent/installornot-missing")
        proc = subprocess.run(
            ["bash", str(INSTALL)],
            capture_output=True,
            text=True,
            env=self._env(),
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertFalse(dest.is_symlink())
        self.assertTrue((dest / "SKILL.md").is_file())

    def test_refuses_old_python(self):
        env = self._env()
        stub_dir = self.home / "bin"
        stub_dir.mkdir()
        stub = stub_dir / "python3"
        stub.write_text("#!/bin/sh\nexec python3 -c 'import sys; sys.version_info = (3, 9, 0); import runpy' 2>/dev/null; exit 1\n")
        # Simpler: a python that reports 3.9 via -c check by wrapping false for our checker.
        stub.write_text(
            "#!/bin/sh\n"
            "if [ \"$1\" = \"-c\" ]; then\n"
            "  case \"$2\" in\n"
            "    *3, 11*) exit 1 ;;\n"
            "    *) exit 0 ;;\n"
            "  esac\n"
            "fi\n"
            "echo 3.9.0\n"
        )
        stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
        env["PATH"] = f"{stub_dir}{os.pathsep}{env.get('PATH', '')}"
        proc = subprocess.run(
            ["bash", str(INSTALL)],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("3.11", proc.stderr)


if __name__ == "__main__":
    unittest.main()
