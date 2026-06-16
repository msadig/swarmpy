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

    # ------------------------------------------------------------------
    # validate --json (#3)
    # ------------------------------------------------------------------

    def _pinned_path_dir(self, parent: Path) -> Path:
        """Build a directory of symlinks to only uv/tmux/git (no claude/codex).

        On systems where /opt/homebrew/bin contains git, tmux, AND codex, simply
        adding the parent dir to PATH would still expose codex. Symlinking each
        tool individually into a fresh directory isolates the pin so claude /
        codex are deterministically missing — mirrors the doctor PATH=""
        precedent for env-controlled warning assertions.
        """
        bindir = parent / "_pinned_bin"
        bindir.mkdir()
        for tool in ("uv", "tmux", "git"):
            src = shutil.which(tool)
            if src is not None:
                (bindir / tool).symlink_to(src)
        return bindir

    def _run_validate(
        self,
        *args: str,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SWARM), "validate", *args],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env or test_env(),
            check=False,
        )

    def test_validate_ok_on_default_init(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            self.run_swarmpy("init", str(project), "-w", "development")

            env = test_env()
            env["PATH"] = str(self._pinned_path_dir(project))
            result = self._run_validate("--json", "-p", str(project), "-w", "development", env=env)
            payload = json.loads(result.stdout)

            self.assertEqual(result.returncode, 0)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["errors"], [])
            self.assertEqual(payload["project"], str(project.resolve()))
            self.assertEqual(payload["workflow"], "development")
            # Default init configures architect=claude, coder=codex, reviewer=codex.
            # With PATH pinned to only uv/tmux/git, exactly two unique missing
            # backends → exactly two warnings, both backend_not_installed.
            self.assertEqual(len(payload["warnings"]), 2)
            warning_codes = sorted(w["code"] for w in payload["warnings"])
            self.assertEqual(warning_codes, ["backend_not_installed", "backend_not_installed"])
            warning_agents = sorted(
                w["message"].split("'")[1] for w in payload["warnings"]
            )
            self.assertEqual(warning_agents, ["claude", "codex"])

    def test_validate_human_ok(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            self.run_swarmpy("init", str(project), "-w", "development")

            env = test_env()
            result = self._run_validate("-p", str(project), "-w", "development", env=env)
            self.assertEqual(result.returncode, 0)
            # When all backends are present (typical dev box) the human path
            # prints "OK". When some backend is missing, the header and warning
            # lines are still emitted; either way the workflow header line lands
            # on stdout. Assert the header invariance.
            self.assertIn("Workflow: development", result.stdout)

    def test_validate_missing_config(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            result = self._run_validate("--json", "-p", str(project), "-w", "ops")
            payload = json.loads(result.stdout)

            self.assertEqual(result.returncode, 1)
            self.assertFalse(payload["ok"])
            self.assertEqual(len(payload["errors"]), 1)
            self.assertEqual(payload["errors"][0]["code"], "missing_config")

    def test_validate_missing_constitution(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            self.run_swarmpy("init", str(project), "-w", "ops")
            workflow_dir = project / "swarmforge" / "workflows" / "ops"
            (workflow_dir / "constitution.prompt").unlink()

            result = self._run_validate("--json", "-p", str(project), "-w", "ops")
            payload = json.loads(result.stdout)

            self.assertEqual(result.returncode, 1)
            self.assertFalse(payload["ok"])
            codes = [e["code"] for e in payload["errors"]]
            self.assertIn("missing_constitution", codes)

    def test_validate_missing_role_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            self.run_swarmpy("init", str(project), "-w", "ops")
            workflow_dir = project / "swarmforge" / "workflows" / "ops"
            (workflow_dir / "coder.prompt").unlink()

            result = self._run_validate("--json", "-p", str(project), "-w", "ops")
            payload = json.loads(result.stdout)

            self.assertEqual(result.returncode, 1)
            self.assertFalse(payload["ok"])
            missing = [e for e in payload["errors"] if e["code"] == "missing_role_prompt"]
            self.assertEqual(len(missing), 1)
            self.assertTrue(missing[0]["path"].endswith("coder.prompt"))
            self.assertIsInstance(missing[0]["line"], int)

    def test_validate_duplicate_role(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            self.run_swarmpy("init", str(project), "-w", "ops")
            workflow_dir = project / "swarmforge" / "workflows" / "ops"
            (workflow_dir / "swarmforge.conf").write_text(
                "window architect claude master\n"
                "window architect claude master\n"
            )

            result = self._run_validate("--json", "-p", str(project), "-w", "ops")
            payload = json.loads(result.stdout)

            self.assertEqual(result.returncode, 1)
            codes = [e["code"] for e in payload["errors"]]
            self.assertIn("duplicate_role", codes)

    def test_validate_duplicate_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            self.run_swarmpy("init", str(project), "-w", "ops")
            workflow_dir = project / "swarmforge" / "workflows" / "ops"
            (workflow_dir / "coder.prompt").write_text("coder\n")
            (workflow_dir / "reviewer.prompt").write_text("reviewer\n")
            (workflow_dir / "swarmforge.conf").write_text(
                "window coder codex shared\n"
                "window reviewer codex shared\n"
            )

            result = self._run_validate("--json", "-p", str(project), "-w", "ops")
            payload = json.loads(result.stdout)

            self.assertEqual(result.returncode, 1)
            codes = [e["code"] for e in payload["errors"]]
            self.assertIn("duplicate_worktree", codes)

    def test_validate_invalid_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            self.run_swarmpy("init", str(project), "-w", "ops")
            workflow_dir = project / "swarmforge" / "workflows" / "ops"
            (workflow_dir / "swarmforge.conf").write_text(
                "window architect claude foo/bar\n"
            )

            result = self._run_validate("--json", "-p", str(project), "-w", "ops")
            payload = json.loads(result.stdout)

            self.assertEqual(result.returncode, 1)
            codes = [e["code"] for e in payload["errors"]]
            self.assertIn("invalid_worktree", codes)

    def test_validate_invalid_line(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            self.run_swarmpy("init", str(project), "-w", "ops")
            workflow_dir = project / "swarmforge" / "workflows" / "ops"
            (workflow_dir / "swarmforge.conf").write_text(
                "window architect claude\n"  # 3 fields, not 4
            )

            result = self._run_validate("--json", "-p", str(project), "-w", "ops")
            payload = json.loads(result.stdout)

            self.assertEqual(result.returncode, 1)
            codes = [e["code"] for e in payload["errors"]]
            self.assertIn("invalid_line", codes)
            self.assertNotIn("empty_config", codes)

    def test_validate_unsupported_agent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            self.run_swarmpy("init", str(project), "-w", "ops")
            workflow_dir = project / "swarmforge" / "workflows" / "ops"
            (workflow_dir / "swarmforge.conf").write_text(
                "window architect gpt5 master\n"
            )

            result = self._run_validate("--json", "-p", str(project), "-w", "ops")
            payload = json.loads(result.stdout)

            self.assertEqual(result.returncode, 1)
            codes = [e["code"] for e in payload["errors"]]
            self.assertIn("unsupported_agent", codes)
            self.assertNotIn("empty_config", codes)

    def test_validate_collects_multiple_errors(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            self.run_swarmpy("init", str(project), "-w", "ops")
            workflow_dir = project / "swarmforge" / "workflows" / "ops"
            # Delete coder.prompt so the third line triggers missing_role_prompt
            # alongside the duplicate_role on line 2.
            (workflow_dir / "coder.prompt").unlink()
            (workflow_dir / "swarmforge.conf").write_text(
                "window architect claude master\n"
                "window architect claude master\n"
                "window coder codex coder\n"
            )

            result = self._run_validate("--json", "-p", str(project), "-w", "ops")
            payload = json.loads(result.stdout)

            self.assertEqual(result.returncode, 1)
            self.assertGreaterEqual(len(payload["errors"]), 2)
            codes = [e["code"] for e in payload["errors"]]
            self.assertIn("duplicate_role", codes)
            self.assertIn("missing_role_prompt", codes)

    def test_validate_does_not_mutate_state(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            self.run_swarmpy("init", str(project), "-w", "ops")

            for marker in (".swarmforge/ops/sessions.tsv", ".worktrees", "logs/ops/agent_messages.log"):
                self.assertFalse((project / marker).exists(), f"pre-validate: {marker} should not exist")

            self._run_validate("--json", "-p", str(project), "-w", "ops")

            # validate must not create any of these runtime artifacts.
            self.assertFalse((project / ".swarmforge" / "ops" / "sessions.tsv").exists())
            self.assertFalse((project / ".worktrees").exists())
            self.assertFalse((project / "logs" / "ops" / "agent_messages.log").exists())

    def test_validate_does_not_require_tmux(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            self.run_swarmpy("init", str(project), "-w", "ops")

            env = test_env()
            env["PATH"] = ""  # drop tmux (and everything else)
            result = self._run_validate("--json", "-p", str(project), "-w", "ops", env=env)
            payload = json.loads(result.stdout)

            # Default init has no errors, so ok: true even with PATH empty.
            self.assertEqual(result.returncode, 0)
            self.assertTrue(payload["ok"])

    def test_parse_config_still_fails_on_first_error(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            self.run_swarmpy("init", str(project), "-w", "ops")
            workflow_dir = project / "swarmforge" / "workflows" / "ops"
            # Three distinct errors at three distinct line numbers:
            # line 1: invalid_line (3 fields)
            # line 2: duplicate_role (architect appears again)
            # line 3: unsupported_agent
            (workflow_dir / "swarmforge.conf").write_text(
                "window architect claude\n"
                "window architect claude master\n"
                "window coder gpt5 coder\n"
            )

            result = subprocess.run(
                [sys.executable, str(SWARM), "launch", str(project), "-w", "ops"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=test_env(),
                check=False,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("Invalid config line 1: window architect claude", result.stderr)
            self.assertNotIn("Duplicate role", result.stderr)
            self.assertNotIn("Unsupported agent", result.stderr)

    def test_validate_empty_config_only_for_truly_empty_file(self) -> None:
        # (a) truly empty (only comments and blanks) → empty_config
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            self.run_swarmpy("init", str(project), "-w", "ops")
            workflow_dir = project / "swarmforge" / "workflows" / "ops"
            (workflow_dir / "swarmforge.conf").write_text("# only a comment\n\n# blank above\n")

            result = self._run_validate("--json", "-p", str(project), "-w", "ops")
            payload = json.loads(result.stdout)

            self.assertEqual(result.returncode, 1)
            codes = [e["code"] for e in payload["errors"]]
            self.assertEqual(codes, ["empty_config"])

        # (b) one well-formed line whose role prompt is missing → missing_role_prompt
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            self.run_swarmpy("init", str(project), "-w", "ops")
            workflow_dir = project / "swarmforge" / "workflows" / "ops"
            (workflow_dir / "coder.prompt").unlink()
            (workflow_dir / "swarmforge.conf").write_text("window coder codex coder\n")

            result = self._run_validate("--json", "-p", str(project), "-w", "ops")
            payload = json.loads(result.stdout)

            self.assertEqual(result.returncode, 1)
            codes = [e["code"] for e in payload["errors"]]
            self.assertIn("missing_role_prompt", codes)
            self.assertNotIn("empty_config", codes)

        # (c) one malformed line → invalid_line (no empty_config companion)
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            self.run_swarmpy("init", str(project), "-w", "ops")
            workflow_dir = project / "swarmforge" / "workflows" / "ops"
            (workflow_dir / "swarmforge.conf").write_text("window architect claude\n")

            result = self._run_validate("--json", "-p", str(project), "-w", "ops")
            payload = json.loads(result.stdout)

            self.assertEqual(result.returncode, 1)
            codes = [e["code"] for e in payload["errors"]]
            self.assertIn("invalid_line", codes)
            self.assertNotIn("empty_config", codes)

    def test_validate_warning_does_not_fail(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            self.run_swarmpy("init", str(project), "-w", "development")

            env = test_env()
            env["PATH"] = str(self._pinned_path_dir(project))
            result = self._run_validate("--json", "-p", str(project), "-w", "development", env=env)
            payload = json.loads(result.stdout)

            self.assertEqual(result.returncode, 0)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["errors"], [])
            self.assertGreaterEqual(len(payload["warnings"]), 1)

    def test_validate_emits_backend_not_installed_warning(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            self.run_swarmpy("init", str(project), "-w", "ops")
            workflow_dir = project / "swarmforge" / "workflows" / "ops"
            (workflow_dir / "swarmforge.conf").write_text("window architect claude master\n")

            env = test_env()
            env["PATH"] = ""
            result = self._run_validate("--json", "-p", str(project), "-w", "ops", env=env)
            payload = json.loads(result.stdout)

            self.assertEqual(result.returncode, 0)
            self.assertTrue(payload["ok"])
            self.assertEqual(len(payload["warnings"]), 1)
            warning = payload["warnings"][0]
            self.assertEqual(warning["code"], "backend_not_installed")
            self.assertIsNone(warning["path"])
            self.assertIsNone(warning["line"])
            self.assertIn("claude", warning["message"])

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
