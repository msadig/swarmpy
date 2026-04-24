#!/usr/bin/env python3
"""Regression tests for swarmpy.

Run:
  python3 test.py
  uv run --script test.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SWARM = ROOT / "swarm.py"


def test_env() -> dict[str, str]:
    env = os.environ.copy()
    # Make git commits deterministic in temporary repos even on machines without
    # global git user config.
    env.setdefault("GIT_AUTHOR_NAME", "swarmpy tests")
    env.setdefault("GIT_AUTHOR_EMAIL", "tests@swarmpy.local")
    env.setdefault("GIT_COMMITTER_NAME", "swarmpy tests")
    env.setdefault("GIT_COMMITTER_EMAIL", "tests@swarmpy.local")
    return env


class SwarmPyTests(unittest.TestCase):
    def run_swarmpy(self, *args: str, cwd: Path | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SWARM), *args],
            cwd=cwd,
            env=env or test_env(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )

    def test_help_lists_friendly_commands(self) -> None:
        result = self.run_swarmpy("--help")
        self.assertIn("install", result.stdout)
        self.assertIn("init", result.stdout)
        self.assertIn("workflows", result.stdout)
        self.assertIn("notify", result.stdout)

    def test_init_creates_multiple_workflows_with_settings(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            self.run_swarmpy("init", str(project), "-w", "development")
            self.run_swarmpy("init", str(project), "-w", "content")

            dev = project / "swarmforge" / "workflows" / "development"
            content = project / "swarmforge" / "workflows" / "content"

            for workflow_dir in [dev, content]:
                self.assertTrue((workflow_dir / "swarmforge.conf").is_file())
                self.assertTrue((workflow_dir / "settings.env").is_file())
                self.assertTrue((workflow_dir / "constitution.prompt").is_file())
                self.assertTrue((workflow_dir / "architect.prompt").is_file())
                self.assertTrue((workflow_dir / "coder.prompt").is_file())
                self.assertTrue((workflow_dir / "reviewer.prompt").is_file())

            result = self.run_swarmpy("workflows", "-p", str(project))
            self.assertIn("development", result.stdout)
            self.assertIn("content", result.stdout)

    def test_install_creates_global_swarmpy_symlink(self) -> None:
        if shutil.which("uv") is None:
            self.skipTest("uv is required to execute the installed shebang symlink")

        with tempfile.TemporaryDirectory() as td:
            bin_dir = Path(td)
            self.run_swarmpy("install", "--bin-dir", str(bin_dir))
            installed = bin_dir / "swarmpy"
            self.assertTrue(installed.is_symlink())
            self.assertEqual(installed.resolve(), SWARM)

            result = subprocess.run(
                [str(installed), "--help"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )
            self.assertIn("Single-file Python/uv SwarmForge runner", result.stdout)

    @unittest.skipIf(shutil.which("tmux") is None, "tmux is required for launch/notify integration test")
    def test_logger_workflow_launch_notify_log_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            self.run_swarmpy("init", str(project), "-w", "ops")

            workflow_dir = project / "swarmforge" / "workflows" / "ops"
            (workflow_dir / "swarmforge.conf").write_text("window logger none none\nwindow observer none none\n")

            try:
                self.run_swarmpy("launch", str(project), "-w", "ops")
                sessions = self.run_swarmpy("sessions", "-p", str(project), "-w", "ops")
                self.assertIn("swarmpy-ops:logger", sessions.stdout)
                self.assertIn("swarmpy-ops:observer", sessions.stdout)
                self.assertIn("running", sessions.stdout)

                tmux_sessions = subprocess.run(
                    ["tmux", "list-sessions", "-F", "#{session_name}: #{session_windows}"],
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=True,
                )
                self.assertIn("swarmpy-ops: 2", tmux_sessions.stdout)

                self.run_swarmpy("notify", "logger", "hello", "ops", "-p", str(project), "-w", "ops")
                self.run_swarmpy("log", "tester", "log", "entry", "-p", str(project), "-w", "ops")

                log_file = project / "logs" / "ops" / "agent_messages.log"
                log_text = log_file.read_text()
                self.assertIn("[swarmpy-ops:logger] hello ops", log_text)
                self.assertIn("[tester] log entry", log_text)
            finally:
                subprocess.run(
                    [sys.executable, str(SWARM), "cleanup", "-p", str(project), "-w", "ops"],
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=test_env(),
                    check=False,
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
