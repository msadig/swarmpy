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

import swarm as swarmpy_module

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
            self.assertEqual(payload["workflows"][0]["config_file"], str((swarmforge_dir / "swarmforge.conf").resolve()))

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

    @unittest.skipIf(
        any(shutil.which(name) is None for name in ("uv", "git", "tmux")),
        "uv, git, and tmux must all be on PATH for the doctor happy-path test",
    )
    def test_doctor_json_reports_required_dependencies(self) -> None:
        result = self.run_swarmpy("doctor", "--json")
        payload = json.loads(result.stdout)

        self.assertTrue(payload["ok"])
        self.assertIsNone(payload["project"])
        self.assertIsNone(payload["workflow"])
        self.assertEqual(
            [dep["name"] for dep in payload["dependencies"]],
            ["uv", "git", "tmux", "claude", "codex", "opencode", "pi", "swarmpy"],
        )
        for name in ("uv", "git", "tmux"):
            entry = next(d for d in payload["dependencies"] if d["name"] == name)
            self.assertTrue(entry["required"])
            self.assertTrue(entry["found"])
            self.assertIsNotNone(entry["path"])
        for name in ("claude", "codex", "opencode", "pi", "swarmpy"):
            entry = next(d for d in payload["dependencies"] if d["name"] == name)
            self.assertFalse(entry["required"])
            self.assertIn("path", entry)
            self.assertIn("version", entry)

    def test_doctor_json_marks_required_missing_when_path_empty(self) -> None:
        env = test_env()
        env["PATH"] = ""
        result = subprocess.run(
            [sys.executable, str(SWARM), "doctor", "--json"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            check=False,
        )
        payload = json.loads(result.stdout)

        self.assertEqual(result.returncode, 1)
        self.assertFalse(payload["ok"])
        self.assertEqual(
            [dep["name"] for dep in payload["dependencies"]],
            ["uv", "git", "tmux", "claude", "codex", "opencode", "pi", "swarmpy"],
        )
        for dep in payload["dependencies"]:
            self.assertFalse(dep["found"])
            self.assertIsNone(dep["path"])
            self.assertIsNone(dep["version"])

    def test_doctor_json_project_aware_marks_configured_agents_required(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            self.run_swarmpy("init", str(project), "-w", "ops")

            workflow_dir = project / "swarmforge" / "workflows" / "ops"
            (workflow_dir / "swarmforge.conf").write_text(
                "window architect claude master\nwindow coder codex coder\n"
            )

            result = self.run_swarmpy("doctor", "--json", "-p", str(project), "-w", "ops", env=test_env())
            payload = json.loads(result.stdout)

            self.assertEqual(payload["project"], str(project.resolve()))
            self.assertEqual(payload["workflow"], "ops")
            self.assertNotIn("error", payload)
            entries = {dep["name"]: dep for dep in payload["dependencies"]}
            self.assertTrue(entries["claude"]["required"])
            self.assertTrue(entries["codex"]["required"])

    def test_doctor_json_project_aware_marks_opencode_required(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            self.run_swarmpy("init", str(project), "-w", "ops")

            workflow_dir = project / "swarmforge" / "workflows" / "ops"
            (workflow_dir / "swarmforge.conf").write_text(
                "window architect opencode master\nwindow coder pi coder\n"
            )

            result = self.run_swarmpy("doctor", "--json", "-p", str(project), "-w", "ops", env=test_env())
            payload = json.loads(result.stdout)

            self.assertEqual(payload["project"], str(project.resolve()))
            self.assertEqual(payload["workflow"], "ops")
            entries = {dep["name"]: dep for dep in payload["dependencies"]}
            self.assertTrue(entries["opencode"]["required"])
            self.assertTrue(entries["pi"]["required"])

    def test_opencode_launch_uses_interactive_tui(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            self.run_swarmpy("init", str(project), "-w", "ops")

            paths = swarmpy_module.paths_for(project, "ops")
            config = swarmpy_module.WindowConfig(
                index=1,
                role="architect",
                agent="opencode",
                worktree_name="master",
                session="swarmpy-test-ops",
                window="architect",
                display="Architect",
                worktree_path=project.resolve(),
            )

            paths.prompts_dir.mkdir(parents=True)
            prompt_file = swarmpy_module.write_agent_instruction_file(paths, "architect")
            prompt_text = prompt_file.read_text()
            command = swarmpy_module.build_agent_command(paths, config, prompt_file)

            self.assertIn("Workflow settings have already been sourced", prompt_text)
            self.assertNotIn("Workflow settings are in", prompt_text)
            self.assertIn("opencode ", command)
            self.assertIn("OPENCODE_PERMISSION=", command)
            self.assertIn('"*.env":"allow"', command)
            self.assertIn("--prompt", command)
            self.assertNotIn("opencode run", command)

    def test_doctor_json_project_aware_tolerates_malformed_config_lines(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            self.run_swarmpy("init", str(project), "-w", "ops")

            workflow_dir = project / "swarmforge" / "workflows" / "ops"
            (workflow_dir / "swarmforge.conf").write_text(
                "# comment line, must be ignored\n"
                "window architect claude master\n"
                "not-a-window-directive\n"
                "window coder codex\n"
                "window reviewer codex reviewer\n"
                "window weird unsupported-agent master\n"
            )

            result = subprocess.run(
                [sys.executable, str(SWARM), "doctor", "--json", "-p", str(project), "-w", "ops"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=test_env(),
                check=False,
            )
            payload = json.loads(result.stdout)

            self.assertNotIn("error", payload)
            self.assertEqual(payload["project"], str(project.resolve()))
            self.assertEqual(payload["workflow"], "ops")
            entries = {dep["name"]: dep for dep in payload["dependencies"]}
            self.assertTrue(entries["claude"]["required"])
            self.assertTrue(entries["codex"]["required"])

    def test_inspect_json_returns_workflow_state(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            self.run_swarmpy("init", str(project), "-w", "ops")

            workflow_dir = project / "swarmforge" / "workflows" / "ops"
            (workflow_dir / "swarmforge.conf").write_text(
                "window architect claude master\n"
                "window coder codex coder\n"
                "window reviewer codex reviewer\n"
                "window logger none none\n"
            )
            (workflow_dir / "coder.prompt").write_text("coder\n")
            (workflow_dir / "reviewer.prompt").write_text("reviewer\n")

            result = self.run_swarmpy("inspect", "--json", "-p", str(project), "-w", "ops")
            payload = json.loads(result.stdout)

            project_id = project.name.lower()
            session = f"swarmpy-{project_id}-ops"
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["project"], {"id": project_id, "path": str(project.resolve())})
            workflow_keys = payload["workflow"]
            self.assertEqual(workflow_keys["name"], "ops")
            self.assertEqual(workflow_keys["session"], session)
            self.assertFalse(workflow_keys["running"])
            self.assertEqual(workflow_keys["config_file"], str((workflow_dir / "swarmforge.conf").resolve()))
            self.assertEqual(workflow_keys["settings_file"], str((workflow_dir / "settings.env").resolve()))
            self.assertEqual(workflow_keys["constitution_file"], str((workflow_dir / "constitution.prompt").resolve()))
            self.assertEqual(workflow_keys["state_dir"], str((project / ".swarmforge" / "ops").resolve()))
            self.assertEqual(workflow_keys["logs_dir"], str((project / "logs" / "ops").resolve()))

            self.assertEqual([role["role"] for role in payload["roles"]], ["architect", "coder", "reviewer", "logger"])
            for role in payload["roles"]:
                self.assertEqual(
                    list(role.keys()),
                    ["index", "role", "agent", "worktree", "worktree_path", "window", "target", "running", "prompt_file", "pane_log"],
                )
                self.assertFalse(role["running"])
                self.assertEqual(role["target"], f"{session}:{role['window']}")
                self.assertEqual(role["pane_log"], str((project / "logs" / "ops" / "panes" / f"{role['role']}.log").resolve()))
                if role["role"] == "logger":
                    self.assertIsNone(role["prompt_file"])
                else:
                    self.assertEqual(role["prompt_file"], str((workflow_dir / f"{role['role']}.prompt").resolve()))

            self.assertEqual(payload["message_log"], str((project / "logs" / "ops" / "agent_messages.log").resolve()))

    def test_inspect_json_missing_config_returns_structured_error(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            self.run_swarmpy("init", str(project), "-w", "ops")

            workflow_dir = project / "swarmforge" / "workflows" / "ops"
            (workflow_dir / "swarmforge.conf").unlink()

            result = subprocess.run(
                [sys.executable, str(SWARM), "inspect", "--json", "-p", str(project), "-w", "ops"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=test_env(),
                check=False,
            )
            payload = json.loads(result.stdout)

            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stderr, "")
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["project"]["id"], project.name.lower())
            self.assertEqual(payload["workflow"]["name"], "ops")
            self.assertEqual(payload["workflow"]["session"], f"swarmpy-{project.name.lower()}-ops")
            self.assertNotIn("running", payload["workflow"])
            self.assertNotIn("roles", payload)
            self.assertNotIn("message_log", payload)
            self.assertIn(str((workflow_dir / "swarmforge.conf").resolve()), payload["error"])

    def test_inspect_json_missing_constitution_returns_structured_error(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            self.run_swarmpy("init", str(project), "-w", "ops")

            workflow_dir = project / "swarmforge" / "workflows" / "ops"
            (workflow_dir / "constitution.prompt").unlink()

            result = subprocess.run(
                [sys.executable, str(SWARM), "inspect", "--json", "-p", str(project), "-w", "ops"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=test_env(),
                check=False,
            )
            payload = json.loads(result.stdout)

            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stderr, "")
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["project"]["id"], project.name.lower())
            self.assertEqual(payload["workflow"]["name"], "ops")
            self.assertEqual(payload["workflow"]["session"], f"swarmpy-{project.name.lower()}-ops")
            self.assertNotIn("running", payload["workflow"])
            self.assertNotIn("roles", payload)
            self.assertNotIn("message_log", payload)
            self.assertIn(str((workflow_dir / "constitution.prompt").resolve()), payload["error"])

    def test_inspect_json_running_false_when_tmux_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            self.run_swarmpy("init", str(project), "-w", "ops")

            env = test_env()
            env["PATH"] = ""
            result = subprocess.run(
                [sys.executable, str(SWARM), "inspect", "--json", "-p", str(project), "-w", "ops"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                check=False,
            )
            payload = json.loads(result.stdout)

            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stderr, "")
            self.assertTrue(payload["ok"])
            self.assertFalse(payload["workflow"]["running"])
            for role in payload["roles"]:
                self.assertFalse(role["running"])

    def test_inspect_human_default_summary(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            self.run_swarmpy("init", str(project), "-w", "ops")

            result = self.run_swarmpy("inspect", "-p", str(project), "-w", "ops")
            self.assertIn(str(project.resolve()), result.stdout)
            self.assertIn("[ops]", result.stdout)
            self.assertIn(f"swarmpy-{project.name.lower()}-ops", result.stdout)
            for role in ("architect", "coder", "reviewer", "logger"):
                self.assertIn(role, result.stdout)

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
