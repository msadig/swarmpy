#!/usr/bin/env python3
"""Regression tests for swarmpy.

Run:
  python3 test.py
  uv run --script test.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
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
        self.assertIn("logs", result.stdout)

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

    def test_workflows_json_empty_project(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            result = self.run_swarmpy("workflows", "--json", "-p", str(project))
            payload = json.loads(result.stdout)
            self.assertEqual(payload, {"project": str(project.resolve()), "workflows": []})

    def test_workflows_json_includes_default_first(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            swarmforge_dir = project / "swarmforge"
            swarmforge_dir.mkdir(parents=True)
            (swarmforge_dir / "swarmforge.conf").write_text("window logger none none\n")

            result = self.run_swarmpy("workflows", "--json", "-p", str(project))
            payload = json.loads(result.stdout)
            self.assertEqual(len(payload["workflows"]), 1)
            self.assertEqual(payload["workflows"][0]["name"], "default")
            self.assertEqual(payload["workflows"][0]["path"], str(swarmforge_dir.resolve()))
            self.assertEqual(payload["workflows"][0]["configFile"], str((swarmforge_dir / "swarmforge.conf").resolve()))

    def test_workflows_json_order_matches_human_output(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            swarmforge_dir = project / "swarmforge"
            swarmforge_dir.mkdir(parents=True)
            (swarmforge_dir / "swarmforge.conf").write_text("window logger none none\n")
            self.run_swarmpy("init", str(project), "-w", "development")
            self.run_swarmpy("init", str(project), "-w", "content")

            human = self.run_swarmpy("workflows", "-p", str(project))
            human_names = [line.split()[0] for line in human.stdout.splitlines()[1:]]

            machine = self.run_swarmpy("workflows", "--json", "-p", str(project))
            payload = json.loads(machine.stdout)
            json_names = [workflow["name"] for workflow in payload["workflows"]]

            self.assertEqual(human_names, json_names)

    def test_sessions_json_returns_machine_readable_state(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            self.run_swarmpy("init", str(project), "-w", "ops")

            sessions_file = project / ".swarmforge" / "ops" / "sessions.tsv"
            sessions_file.parent.mkdir(parents=True)
            sessions_file.write_text("1\tarchitect\tswarmpy-test-ops\tarchitect\tArchitect\tclaude\n")

            result = self.run_swarmpy("sessions", "--json", "-p", str(project), "-w", "ops")
            payload = json.loads(result.stdout)

            self.assertEqual(payload["project"], str(project.resolve()))
            self.assertEqual(payload["workflow"], "ops")
            self.assertEqual(len(payload["sessions"]), 1)
            self.assertEqual(
                payload["sessions"][0],
                {
                    "index": "1",
                    "role": "architect",
                    "session": "swarmpy-test-ops",
                    "window": "architect",
                    "target": "swarmpy-test-ops:architect",
                    "display": "Architect",
                    "agent": "claude",
                    "running": False,
                },
            )

    def test_sessions_json_missing_file_returns_structured_error(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            self.run_swarmpy("init", str(project), "-w", "ops")

            result = subprocess.run(
                [sys.executable, str(SWARM), "sessions", "--json", "-p", str(project), "-w", "ops"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=test_env(),
                check=False,
            )

            payload = json.loads(result.stdout)
            expected_sessions_file = (project.resolve() / ".swarmforge" / "ops" / "sessions.tsv").resolve()
            self.assertEqual(result.returncode, 1)
            self.assertEqual(payload["project"], str(project.resolve()))
            self.assertEqual(payload["workflow"], "ops")
            self.assertEqual(payload["sessions"], [])
            self.assertEqual(payload["error"], f"Sessions file not found: {expected_sessions_file}")
            self.assertEqual(result.stderr, "")

    def test_sessions_without_json_missing_file_still_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            self.run_swarmpy("init", str(project), "-w", "ops")

            result = subprocess.run(
                [sys.executable, str(SWARM), "sessions", "-p", str(project), "-w", "ops"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=test_env(),
                check=False,
            )

            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout, "")
            self.assertIn("Sessions file not found:", result.stderr)

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
    def test_launch_can_use_shared_workflow_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            self.run_swarmpy("init", str(project), "-w", "ops")

            workflow_dir = project / "swarmforge" / "workflows" / "ops"
            (workflow_dir / "swarmforge.conf").write_text("window worker none master\nwindow logger none none\n")

            try:
                self.run_swarmpy("launch", str(project), "-w", "ops", "--worktree", "nightly")
                expected_session = f"swarmpy-{project.name.lower()}-ops"
                sessions = self.run_swarmpy("sessions", "-p", str(project), "-w", "ops")
                self.assertIn(f"{expected_session}:worker", sessions.stdout)
                self.assertTrue((project / ".worktrees" / "ops" / "nightly" / ".git").exists())
            finally:
                subprocess.run(
                    [sys.executable, str(SWARM), "cleanup", "-p", str(project), "-w", "ops"],
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=test_env(),
                    check=False,
                )

    @unittest.skipIf(shutil.which("tmux") is None, "tmux is required for launch/notify integration test")
    def test_logger_workflow_launch_notify_log_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            self.run_swarmpy("init", str(project), "-w", "ops")

            workflow_dir = project / "swarmforge" / "workflows" / "ops"
            (workflow_dir / "swarmforge.conf").write_text("window logger none none\nwindow observer none none\n")

            try:
                self.run_swarmpy("launch", str(project), "-w", "ops")
                expected_session = f"swarmpy-{project.name.lower()}-ops"
                sessions = self.run_swarmpy("sessions", "-p", str(project), "-w", "ops")
                self.assertIn(f"{expected_session}:logger", sessions.stdout)
                self.assertIn(f"{expected_session}:observer", sessions.stdout)
                self.assertIn("running", sessions.stdout)

                tmux_sessions = subprocess.run(
                    ["tmux", "list-sessions", "-F", "#{session_name}: #{session_windows}"],
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=True,
                )
                self.assertIn(f"{expected_session}: 2", tmux_sessions.stdout)

                self.run_swarmpy("notify", "logger", "hello", "ops", "-p", str(project), "-w", "ops")
                self.run_swarmpy("log", "tester", "log", "entry", "-p", str(project), "-w", "ops")

                log_file = project / "logs" / "ops" / "agent_messages.log"
                log_text = log_file.read_text()
                self.assertIn(f"[{expected_session}:logger] hello ops", log_text)
                self.assertIn("[tester] log entry", log_text)

                logs = self.run_swarmpy("logs", "-n", "2", "-p", str(project), "-w", "ops")
                self.assertIn(f"[{expected_session}:logger] hello ops", logs.stdout)
                self.assertIn("[tester] log entry", logs.stdout)

                log_path = self.run_swarmpy("logs", "--path", "-p", str(project), "-w", "ops")
                self.assertEqual(Path(log_path.stdout.strip()).resolve(), log_file.resolve())

                pane_path = self.run_swarmpy("logs", "--pane", "logger", "--path", "-p", str(project), "-w", "ops")
                pane_log_file = project / "logs" / "ops" / "panes" / "logger.log"
                self.assertEqual(Path(pane_path.stdout.strip()).resolve(), pane_log_file.resolve())

                time.sleep(0.2)
                pane_logs = self.run_swarmpy("logs", "--pane", "logger", "-n", "20", "-p", str(project), "-w", "ops")
                self.assertTrue(pane_log_file.is_file())
                self.assertIn("hello ops", pane_logs.stdout)

                all_pane_paths = self.run_swarmpy("logs", "--all-panes", "--path", "-p", str(project), "-w", "ops")
                self.assertIn(str((project / "logs" / "ops" / "panes" / "logger.log").resolve()), str(Path(all_pane_paths.stdout.splitlines()[0]).resolve()))
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
