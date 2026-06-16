#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# ///
"""
SwarmForge, ported to one Python file.

Usage:
  uv run --script swarm.py [WORKING_DIR]
  ./swarm.py [WORKING_DIR]

Agent helper commands:
  uv run --script /path/to/swarm.py notify <role-or-index> "message"
  uv run --script /path/to/swarm.py log <role> "message"
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path

SUPPORTED_AGENTS = ("claude", "codex", "opencode", "pi", "none")
BACKEND_AGENTS = tuple(agent for agent in SUPPORTED_AGENTS if agent != "none")
OPENCODE_DEFAULT_PERMISSION = json.dumps(
    {"*": "allow", "read": {"*": "allow", "*.env": "allow", "*.env.*": "allow"}},
    separators=(",", ":"),
)
SHARED_WORKTREE_NAMES = frozenset({"none", "master"})

RED = "\033[0;31m"
GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
CYAN = "\033[0;36m"
BOLD = "\033[1m"
RESET = "\033[0m"


@dataclass(frozen=True)
class WindowConfig:
    index: int
    role: str
    agent: str
    worktree_name: str
    session: str
    window: str
    display: str
    worktree_path: Path


@dataclass(frozen=True)
class ConfigIssue:
    code: str
    message: str
    path: str | None
    line: int | None


@dataclass(frozen=True)
class SessionRow:
    index: str
    role: str
    session: str
    window: str
    display: str
    agent: str

    @property
    def target(self) -> str:
        return f"{self.session}:{self.window}"


@dataclass(frozen=True)
class ProjectPaths:
    working_dir: Path
    script_path: Path
    project_id: str
    workflow: str
    swarmforge_dir: Path
    worktrees_dir: Path
    config_file: Path
    constitution_file: Path
    settings_file: Path
    state_dir: Path
    sessions_file: Path
    prompts_dir: Path
    logs_dir: Path
    context_dir: Path


def q(value: str | Path) -> str:
    return shlex.quote(str(value))


def fail(message: str, code: int = 1) -> None:
    print(f"{RED}Error:{RESET} {message}", file=sys.stderr)
    raise SystemExit(code)


def _emit_json(payload: dict) -> None:
    print(json.dumps(payload, indent=2))


def run(cmd: list[str], *, cwd: Path | None = None, check: bool = True, stdout=None, stderr=None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=check, stdout=stdout, stderr=stderr, text=True)


def check_dependency(name: str) -> None:
    if shutil.which(name) is None:
        fail(f"'{name}' is required but not installed.")


def clean_name(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in name.strip())
    cleaned = cleaned.strip("-")
    if not cleaned:
        fail("Workflow name cannot be empty")
    return cleaned


def workflow_dir_for(working_dir: Path, workflow: str) -> Path:
    base = working_dir / "swarmforge"
    if workflow == "default":
        return base
    return base / "workflows" / workflow


def paths_for(working_dir: Path, workflow: str = "default") -> ProjectPaths:
    working_dir = working_dir.expanduser().resolve()
    workflow = clean_name(workflow)
    project_id = clean_name(working_dir.name).lower()
    script_path = Path(__file__).expanduser().resolve()
    swarmforge_dir = workflow_dir_for(working_dir, workflow)
    state_dir = working_dir / ".swarmforge" / workflow
    return ProjectPaths(
        working_dir=working_dir,
        script_path=script_path,
        project_id=project_id,
        workflow=workflow,
        swarmforge_dir=swarmforge_dir,
        worktrees_dir=working_dir / ".worktrees" / workflow,
        config_file=swarmforge_dir / "swarmforge.conf",
        constitution_file=swarmforge_dir / "constitution.prompt",
        settings_file=swarmforge_dir / "settings.env",
        state_dir=state_dir,
        sessions_file=state_dir / "sessions.tsv",
        prompts_dir=state_dir / "prompts",
        logs_dir=working_dir / "logs" / workflow,
        context_dir=working_dir / "agent_context" / workflow,
    )


def ensure_gitignore(working_dir: Path) -> None:
    gitignore = working_dir / ".gitignore"
    required = [".swarmforge/", ".worktrees/", "logs/", "agent_context/"]

    if not gitignore.exists():
        gitignore.write_text("\n".join(required) + "\n")
        return

    lines = gitignore.read_text().splitlines()
    existing = set(lines)
    changed = False
    for item in required:
        if item not in existing:
            lines.append(item)
            changed = True
    if changed:
        gitignore.write_text("\n".join(lines) + "\n")


def initialize_git_repo(working_dir: Path) -> None:
    if (working_dir / ".git").exists():
        return

    run(["git", "init", str(working_dir)], stdout=subprocess.DEVNULL)
    run(["git", "-C", str(working_dir), "branch", "-M", "master"], stdout=subprocess.DEVNULL)
    ensure_gitignore(working_dir)
    run(["git", "-C", str(working_dir), "add", "."])
    run(["git", "-C", str(working_dir), "commit", "-m", "Initial swarmforge repository"], stdout=subprocess.DEVNULL)


def write_scaffold_file(path: Path, content: str, force: bool) -> bool:
    if path.exists() and not force:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return True


def command_for_agents(paths: ProjectPaths) -> str:
    return "swarmpy" if shutil.which("swarmpy") else f"uv run --script {q(paths.script_path)}"


def install_cli(bin_dir_arg: str | None, force: bool = False) -> None:
    bin_dir = Path(bin_dir_arg or "~/.local/bin").expanduser().resolve()
    source = Path(__file__).expanduser().resolve()
    target = bin_dir / "swarmpy"

    bin_dir.mkdir(parents=True, exist_ok=True)
    source.chmod(source.stat().st_mode | 0o111)

    if target.exists() or target.is_symlink():
        try:
            already_installed = target.resolve() == source
        except OSError:
            already_installed = False

        if already_installed:
            print(f"{GREEN}swarmpy is already installed:{RESET} {target}")
            return
        if not force:
            fail(f"{target} already exists. Re-run with --force to replace it.")
        if target.is_dir() and not target.is_symlink():
            fail(f"{target} is a directory; cannot replace it.")
        target.unlink()

    target.symlink_to(source)
    print(f"{GREEN}Installed global command:{RESET} {target} -> {source}")

    path_entries = [Path(p).expanduser().resolve() for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    if bin_dir not in path_entries:
        print(f"{YELLOW}Note:{RESET} {bin_dir} is not currently in PATH.")
        print(f"Add this to your shell config:")
        print(f"  export PATH=\"{bin_dir}:$PATH\"")
    else:
        print("Try:")
        print("  swarmpy --help")


def init_project(working_dir_arg: str, workflow: str = "default", force: bool = False) -> None:
    working_dir = Path(working_dir_arg).expanduser().resolve()
    working_dir.mkdir(parents=True, exist_ok=True)
    paths = paths_for(working_dir, workflow)

    files = {
        paths.config_file: f"""# SwarmPy workflow config: {paths.workflow}
# Format: window <role> <agent> <worktree>
# Agents: claude, codex, opencode, pi, none
# Worktree: master runs in the main checkout; none creates no worktree; any other name creates .worktrees/{paths.workflow}/<name>.
window architect claude master
window coder codex coder
window reviewer codex reviewer
window logger none none
""",
        paths.settings_file: f"""# Workflow settings for: {paths.workflow}
# This file is sourced before each agent starts.
# Put workflow-specific environment variables here, for example:
# GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
# GITHUB_LABEL=bug
""",
        paths.constitution_file: f"""# Constitution: {paths.workflow}

Every agent in this workflow must follow these rules:

1. Read this file first.
2. Read your role prompt from this workflow directory.
3. Make small, reviewable changes.
4. Keep workflow-specific checks green.
5. Communicate through `swarmpy notify <role-or-index> "message" -w {paths.workflow}` and `swarmpy log <role> "message" -w {paths.workflow}`.

Workflow-specific rules belong here. Keep them short and explicit.
""",
        paths.swarmforge_dir / "architect.prompt": """# Architect

You own planning and task breakdown.

- Clarify intent before implementation.
- Split work into small slices.
- Notify coder with the next concrete task.
- Notify reviewer when a slice is ready for review.
""",
        paths.swarmforge_dir / "coder.prompt": """# Coder

You implement one small slice at a time.

- Read the constitution and this prompt before acting.
- Keep changes focused.
- Run relevant tests/checks.
- Notify reviewer when implementation is ready.
""",
        paths.swarmforge_dir / "reviewer.prompt": """# Reviewer

You verify quality and correctness.

- Review diffs carefully.
- Run relevant tests/checks.
- Ask coder for fixes when needed.
- Notify architect when the slice is accepted or blocked.
""",
    }

    created = []
    skipped = []
    for path, content in files.items():
        if write_scaffold_file(path, content, force):
            created.append(path)
        else:
            skipped.append(path)

    if (working_dir / ".git").exists():
        ensure_gitignore(working_dir)
    else:
        check_dependency("git")
        initialize_git_repo(working_dir)

    print(f"{GREEN}SwarmPy workflow initialized:{RESET} {working_dir} [{paths.project_id}/{paths.workflow}]")
    if created:
        print("Created:")
        for path in created:
            print(f"  {path.relative_to(working_dir)}")
    if skipped:
        print("Skipped existing files, use --force to overwrite:")
        for path in skipped:
            print(f"  {path.relative_to(working_dir)}")
    print()
    print("Next steps:")
    print(f"  1. Edit {paths.config_file.relative_to(working_dir)} and prompt files as needed")
    print(f"  2. Edit workflow settings: {paths.settings_file.relative_to(working_dir)}")
    print(f"  3. Start the swarm: {command_for_agents(paths)} launch {working_dir} -w {paths.workflow}")


def display_name_for_role(role: str) -> str:
    return " ".join(part.capitalize() for part in role.replace("-", " ").replace("_", " ").split())


def session_name_for_workflow(project_id: str, workflow: str) -> str:
    return f"swarmpy-{project_id}-{workflow}"


def collect_config_issues(paths: ProjectPaths) -> tuple[list[WindowConfig], list[ConfigIssue]]:
    """Walk the workflow config, collecting all issues without exiting.

    Used by validate (collect-all) and parse_config (fail-on-first wrapper).
    """
    issues: list[ConfigIssue] = []
    configs: list[WindowConfig] = []
    roles: set[str] = set()
    worktrees: set[str] = set()

    if not paths.config_file.is_file():
        issues.append(ConfigIssue(
            "missing_config",
            f"Config not found at {paths.config_file}",
            str(paths.config_file),
            None,
        ))
        return configs, issues

    if not paths.constitution_file.is_file():
        issues.append(ConfigIssue(
            "missing_constitution",
            f"Constitution prompt not found at {paths.constitution_file}",
            str(paths.constitution_file),
            None,
        ))
        # do not return — keep walking the config to surface every issue at once

    for line_no, raw in enumerate(paths.config_file.read_text().splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        fields = line.split()
        if len(fields) != 4:
            issues.append(ConfigIssue("invalid_line", f"Invalid config line {line_no}: {line}", str(paths.config_file), line_no))
            continue

        keyword, role, agent, worktree_name = fields
        agent = agent.lower()

        line_ok = True
        if keyword != "window":
            issues.append(ConfigIssue("unknown_directive", f"Unknown config directive on line {line_no}: {keyword}", str(paths.config_file), line_no))
            line_ok = False
        if role in roles:
            issues.append(ConfigIssue("duplicate_role", f"Duplicate role '{role}' in {paths.config_file}", str(paths.config_file), line_no))
            line_ok = False
        if worktree_name not in SHARED_WORKTREE_NAMES and worktree_name in worktrees:
            issues.append(ConfigIssue("duplicate_worktree", f"Duplicate worktree '{worktree_name}' in {paths.config_file}", str(paths.config_file), line_no))
            line_ok = False
        if "/" in worktree_name or worktree_name in {".", ".."}:
            issues.append(ConfigIssue("invalid_worktree", f"Invalid worktree '{worktree_name}' for role '{role}'", str(paths.config_file), line_no))
            line_ok = False
        if agent not in SUPPORTED_AGENTS:
            issues.append(ConfigIssue("unsupported_agent", f"Unsupported agent '{agent}' for role '{role}'", str(paths.config_file), line_no))
            line_ok = False
        prompt_path = paths.swarmforge_dir / f"{role}.prompt"
        if agent != "none" and not prompt_path.is_file():
            issues.append(ConfigIssue("missing_role_prompt", f"Missing role prompt {prompt_path}", str(prompt_path), line_no))
            line_ok = False

        # Always reserve the role/worktree name even when other fields on this
        # line failed validation — surfaces a duplicate-of-a-bad-line as a
        # duplicate rather than collapsing two bad lines into one.
        roles.add(role)
        if worktree_name not in SHARED_WORKTREE_NAMES:
            worktrees.add(worktree_name)
            worktree_path = paths.worktrees_dir / worktree_name
        else:
            worktree_path = paths.working_dir

        if line_ok:
            configs.append(
                WindowConfig(
                    index=len(configs) + 1,
                    role=role,
                    agent=agent,
                    worktree_name=worktree_name,
                    session=session_name_for_workflow(paths.project_id, paths.workflow),
                    window=role,
                    display=display_name_for_role(role),
                    worktree_path=worktree_path,
                )
            )

    # Emit empty_config only when the file truly has no non-comment config lines.
    # If any other issue was collected, those already explain why no fully-valid
    # configs exist; appending empty_config alongside them would be misleading.
    has_any_config_line = any(
        bool(line.strip()) and not line.strip().startswith("#")
        for line in paths.config_file.read_text().splitlines()
    )
    if not configs and not issues and not has_any_config_line:
        issues.append(ConfigIssue("empty_config", f"No windows defined in {paths.config_file}", str(paths.config_file), None))

    return configs, issues


def parse_config(paths: ProjectPaths) -> list[WindowConfig]:
    configs, issues = collect_config_issues(paths)
    if issues:
        fail(issues[0].message)  # preserve byte-identical first-error semantics for launch
    return configs


def write_sessions_file(paths: ProjectPaths, configs: list[WindowConfig]) -> None:
    lines = [f"{c.index}\t{c.role}\t{c.session}\t{c.window}\t{c.display}\t{c.agent}" for c in configs]
    paths.sessions_file.write_text("\n".join(lines) + "\n")


def apply_workflow_worktree(paths: ProjectPaths, configs: list[WindowConfig], worktree_name: str | None) -> list[WindowConfig]:
    if not worktree_name:
        return configs

    worktree_path = paths.worktrees_dir / worktree_name
    return [
        replace(config, worktree_name=worktree_name, worktree_path=worktree_path)
        if config.worktree_name != "none"
        else config
        for config in configs
    ]


def prepare_workspace(paths: ProjectPaths, configs: list[WindowConfig]) -> None:
    for directory in [
        paths.logs_dir,
        paths.context_dir,
        paths.working_dir / "features",
        paths.state_dir,
        paths.prompts_dir,
        paths.worktrees_dir,
    ]:
        directory.mkdir(parents=True, exist_ok=True)

    write_sessions_file(paths, configs)


def prepare_worktrees(paths: ProjectPaths, configs: list[WindowConfig]) -> None:
    for config in configs:
        if config.worktree_name in SHARED_WORKTREE_NAMES:
            continue
        if (config.worktree_path / ".git").exists():
            continue
        branch_name = f"swarmpy-{paths.project_id}-{paths.workflow}-{config.worktree_name}"
        run(
            [
                "git",
                "-C",
                str(paths.working_dir),
                "worktree",
                "add",
                "--force",
                "-B",
                branch_name,
                str(config.worktree_path),
                "HEAD",
            ],
            stdout=subprocess.DEVNULL,
        )


def check_backend_dependencies(configs: list[WindowConfig]) -> None:
    for config in configs:
        if config.agent in BACKEND_AGENTS:
            check_dependency(config.agent)


def tmux(*args: str, check: bool = True, stdout=None, stderr=None) -> subprocess.CompletedProcess:
    return run(["tmux", *args], check=check, stdout=stdout, stderr=stderr)


def tmux_has_session(session: str) -> bool:
    result = tmux("has-session", "-t", session, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return result.returncode == 0


def first_pane_target(session: str) -> str:
    result = tmux("list-panes", "-t", session, "-F", "#{pane_id}", stdout=subprocess.PIPE)
    pane_id = result.stdout.splitlines()[0].strip() if result.stdout else ""
    if not pane_id:
        fail(f"No tmux pane found in session {session}")
    return pane_id


def pane_log_path(paths: ProjectPaths, role: str) -> Path:
    return paths.logs_dir / "panes" / f"{role}.log"


def start_pane_logging(paths: ProjectPaths, config: WindowConfig) -> None:
    log_file = pane_log_path(paths, config.role)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.touch(exist_ok=True)
    target = f"{config.session}:{config.window}"
    tmux("pipe-pane", "-o", "-t", target, f"cat >> {q(log_file)}")


def create_workflow_session(paths: ProjectPaths, configs: list[WindowConfig]) -> None:
    for i, config in enumerate(configs):
        if i == 0:
            tmux("new-session", "-d", "-s", config.session, "-n", config.window)
        else:
            tmux("new-window", "-t", config.session, "-n", config.window)
        tmux("set-window-option", "-t", f"{config.session}:{config.window}", "allow-rename", "off")
        start_pane_logging(paths, config)


def write_agent_instruction_file(paths: ProjectPaths, role: str) -> Path:
    prompt_file = paths.prompts_dir / f"{role}.md"
    prompt_file.write_text(
        f"This agent is running in SwarmPy workflow: {paths.workflow}\n"
        f"Read {paths.constitution_file.relative_to(paths.working_dir)}, then read every file it refers to recursively, and obey all of those instructions.\n"
        f"Read {Path(paths.swarmforge_dir.name) / f'{role}.prompt' if paths.workflow == 'default' else paths.swarmforge_dir.relative_to(paths.working_dir) / f'{role}.prompt'}, then read every file it refers to recursively, and follow all of those instructions.\n"
        "Workflow settings have already been sourced into this process environment; do not read settings.env unless the user explicitly asks.\n"
        f"Workflow logs are in {paths.logs_dir.relative_to(paths.working_dir)}.\n"
        f"Workflow context is in {paths.context_dir.relative_to(paths.working_dir)}.\n"
        f"To notify another role, run: {command_for_agents(paths)} notify <role-or-index> '<message>' -w {paths.workflow}\n"
        f"To write a swarm log entry, run: {command_for_agents(paths)} log {role} '<message>' -w {paths.workflow}\n"
    )
    return prompt_file


def script_command(paths: ProjectPaths) -> str:
    return f"uv run --script {q(paths.script_path)}"


def base_environment_command(paths: ProjectPaths) -> str:
    return (
        f"set -a; [ -f {q(paths.settings_file)} ] && . {q(paths.settings_file)}; set +a; "
        f"export SWARMFORGE_PROJECT_DIR={q(paths.working_dir)} SWARMPY_WORKFLOW={q(paths.workflow)} "
        f"SWARMPY={q(command_for_agents(paths))} SWARMFORGE_SCRIPT={q(paths.script_path)}"
    )


def build_agent_command(paths: ProjectPaths, config: WindowConfig, prompt_file: Path) -> str:
    env_cmd = base_environment_command(paths)

    if config.agent == "claude":
        return (
            f"{env_cmd} && cd {q(config.worktree_path)} && "
            f"claude --append-system-prompt-file {q(prompt_file)} "
            f"--dangerously-skip-permissions -n {q('SwarmForge ' + config.display)} "
            f'"$(cat {q(prompt_file)})"'
        )
    if config.agent == "codex":
        return (
            f"{env_cmd} && cd {q(config.worktree_path)} && "
            f"codex -C {q(config.worktree_path)} "
            f"--dangerously-bypass-approvals-and-sandbox "
            f'"$(cat {q(prompt_file)})"'
        )
    if config.agent == "opencode":
        return (
            f"{env_cmd} && cd {q(config.worktree_path)} && "
            f"if [ -z \"${{OPENCODE_PERMISSION+x}}\" ]; then export OPENCODE_PERMISSION={q(OPENCODE_DEFAULT_PERMISSION)}; fi; "
            f"opencode {q(config.worktree_path)} "
            f"--prompt \"$(cat {q(prompt_file)})\""
        )
    if config.agent == "pi":
        return (
            f"{env_cmd} && cd {q(config.worktree_path)} && "
            f"pi "
            f'"$(cat {q(prompt_file)})"'
        )
    fail(f"Unsupported agent '{config.agent}' for role '{config.role}'")


def choose_cleanup_owner(configs: list[WindowConfig]) -> int | None:
    for config in configs:
        if config.role == "architect" and config.agent != "none":
            return config.index
    for config in configs:
        if config.agent != "none":
            return config.index
    return None


def launch_role(paths: ProjectPaths, configs: list[WindowConfig], config: WindowConfig, cleanup_owner: int | None) -> None:
    # Target the actual pane id so user tmux base-index/pane-base-index settings
    # cannot break startup.
    target = first_pane_target(f"{config.session}:{config.window}")

    if config.agent == "none":
        if config.role == "logger":
            command = f"cd {q(paths.working_dir)} && mkdir -p {q(paths.logs_dir)} && touch {q(paths.logs_dir / 'agent_messages.log')} && tail -f {q(paths.logs_dir / 'agent_messages.log')}"
            tmux("send-keys", "-t", target, command, "Enter")
        print(f"  {CYAN}[{config.display}]{RESET} opened without agent backend")
        return

    prompt_file = write_agent_instruction_file(paths, config.role)
    command = build_agent_command(paths, config, prompt_file)

    if cleanup_owner == config.index:
        cleanup_cmd = f"{script_command(paths)} cleanup " + q(config.session)
        command = f"{command}; exit_code=$?; nohup {cleanup_cmd} >/dev/null 2>&1 & exit $exit_code"

    tmux("send-keys", "-t", target, command, "Enter")
    print(f"  {CYAN}[{config.display}]{RESET} started in session {config.session}")


def print_banner() -> None:
    print(f"{CYAN}{BOLD}")
    print("  ╔═══════════════════════════════════════════════╗")
    print("  ║           SwarmForge v1.0 Starting            ║")
    print("  ║   Disciplined agents build better software    ║")
    print("  ╚═══════════════════════════════════════════════╝")
    print(f"{RESET}")


def launch(working_dir_arg: str, workflow: str = "default", worktree: str | None = None) -> None:
    working_dir = Path(working_dir_arg)
    if not working_dir.exists():
        fail(f"Working directory does not exist: {working_dir}")

    paths = paths_for(working_dir, workflow)

    check_dependency("uv")
    check_dependency("tmux")
    check_dependency("git")

    initialize_git_repo(paths.working_dir)
    worktree_name = clean_name(worktree) if worktree else None
    configs = apply_workflow_worktree(paths, parse_config(paths), worktree_name)
    check_backend_dependencies(configs)
    prepare_workspace(paths, configs)
    prepare_worktrees(paths, configs)
    cleanup_owner = choose_cleanup_owner(configs)

    workflow_session = configs[0].session
    if tmux_has_session(workflow_session):
        print(f"{YELLOW}Existing SwarmPy workflow session found: {workflow_session}. Killing it...{RESET}")
        tmux("kill-session", "-t", workflow_session, check=False)

    print_banner()
    print(f"{GREEN}Launching SwarmPy workflow tmux session...{RESET}")
    create_workflow_session(paths, configs)

    print(f"{GREEN}Starting agents...{RESET}")
    for config in configs:
        launch_role(paths, configs, config, cleanup_owner)

    print()
    print(f"{GREEN}{BOLD}SwarmForge is ready.{RESET}")
    print(f"Working directory: {paths.working_dir}")
    print(f"Project id: {paths.project_id}")
    print(f"Workflow: {paths.workflow}")
    if worktree_name:
        print(f"Workflow worktree: {paths.worktrees_dir / worktree_name}")
    print(f"Tmux session: {workflow_session}")
    print("Windows:")
    for config in configs:
        print(f"  {config.display}: {config.session}:{config.window}")
    print()
    print(f"{GREEN}Tip: Notify with: {command_for_agents(paths)} notify <role-or-index> \"message\" -w {paths.workflow}{RESET}")
    print(f"{GREEN}Tip: Reattach with 'tmux attach-session -t {workflow_session}'.{RESET}")
    if cleanup_owner is not None:
        owner = next(c for c in configs if c.index == cleanup_owner)
        print(f"{GREEN}Tip: Cleanup is owned by {owner.display}; when it exits, all swarm sessions are killed.{RESET}")
    print()


def project_dir_from_context() -> Path:
    env_project = os.environ.get("SWARMFORGE_PROJECT_DIR")
    if env_project:
        return Path(env_project).expanduser().resolve()

    return Path.cwd().resolve()


def workflow_from_context() -> str:
    return clean_name(os.environ.get("SWARMPY_WORKFLOW", "default"))


def read_sessions(sessions_file: Path) -> list[SessionRow]:
    if not sessions_file.is_file():
        fail(f"Sessions file not found: {sessions_file}")

    rows: list[SessionRow] = []
    for raw in sessions_file.read_text().splitlines():
        fields = raw.split("\t")
        if len(fields) == 6:
            index, role, session, window, display, agent = fields
            rows.append(SessionRow(index, role, session, window, display, agent))
        elif len(fields) == 5:
            # Backward compatibility for sessions files written before workflow
            # sessions were grouped into windows.
            index, role, session, display, agent = fields
            rows.append(SessionRow(index, role, session, role, display, agent))
    return rows


def resolve_project_dir(project: str | None) -> Path:
    if project:
        return Path(project).expanduser().resolve()
    return project_dir_from_context()


def resolve_project_paths(project: str | None, workflow: str | None) -> ProjectPaths:
    return paths_for(resolve_project_dir(project), workflow or workflow_from_context())


def resolve_target(rows: list[SessionRow], target: str) -> SessionRow:
    normalized = target.lower()
    for row in rows:
        if normalized in {row.index.lower(), row.role.lower(), row.session.lower(), row.target.lower()}:
            return row
    fail(f"Unknown target: {target}")


def append_log(paths: ProjectPaths, actor: str, message: str) -> None:
    log_file = paths.logs_dir / "agent_messages.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with log_file.open("a") as f:
        f.write(f"[{timestamp}] [{actor}] {message}\n")


def cmd_notify(args: argparse.Namespace) -> None:
    paths = resolve_project_paths(args.project, args.workflow)
    rows = read_sessions(paths.sessions_file)
    target = resolve_target(rows, args.target)
    message = " ".join(args.message)

    append_log(paths, target.target, message)

    pane_target = first_pane_target(target.target)
    tmux("send-keys", "-t", pane_target, "-l", "--", message)
    time.sleep(0.15)
    tmux("send-keys", "-t", pane_target, "C-m")
    time.sleep(0.05)
    tmux("send-keys", "-t", pane_target, "C-j")


def cmd_log(args: argparse.Namespace) -> None:
    paths = resolve_project_paths(args.project, args.workflow)
    message = " ".join(args.message)
    append_log(paths, args.role, message)
    print(f"[{args.role}] {message}")


def cmd_logs(args: argparse.Namespace) -> None:
    paths = resolve_project_paths(args.project, args.workflow)

    if args.all_panes or args.pane:
        rows = read_sessions(paths.sessions_file)
        targets = rows if args.all_panes else [resolve_target(rows, args.pane)]
        log_files = [pane_log_path(paths, t.role) for t in targets]
    else:
        log_files = [paths.logs_dir / "agent_messages.log"]

    if args.path:
        for log_file in log_files:
            print(log_file)
        return

    for log_file in log_files:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_file.touch(exist_ok=True)

    tail_cmd = ["tail", "-n", str(args.lines), *(["-f"] if args.follow else []), *[str(p) for p in log_files]]
    if args.follow:
        os.execvp("tail", tail_cmd)
    subprocess.run(tail_cmd, check=False)


def cmd_sessions(args: argparse.Namespace) -> None:
    paths = resolve_project_paths(args.project, args.workflow)
    if args.json:
        if not paths.sessions_file.is_file():
            _emit_json(
                {
                    "project": str(paths.working_dir),
                    "workflow": paths.workflow,
                    "sessions": [],
                    "error": f"Sessions file not found: {paths.sessions_file}",
                }
            )
            raise SystemExit(1)
        rows = read_sessions(paths.sessions_file)
        _emit_json(
            {
                "project": str(paths.working_dir),
                "workflow": paths.workflow,
                "sessions": [
                    {
                        "index": row.index,
                        "role": row.role,
                        "session": row.session,
                        "window": row.window,
                        "target": row.target,
                        "display": row.display,
                        "agent": row.agent,
                        "running": tmux_has_session(row.session),
                    }
                    for row in rows
                ],
            }
        )
        return
    rows = read_sessions(paths.sessions_file)
    print(f"Swarm sessions for {paths.working_dir} [{paths.workflow}]:")
    for row in rows:
        marker = "running" if tmux_has_session(row.session) else "stopped"
        print(f"  {row.index}. {row.role:<16} {row.target:<32} {row.agent:<6} {marker}  ({row.display})")


def cmd_workflows(args: argparse.Namespace) -> None:
    project_dir = resolve_project_dir(args.project)
    base = project_dir / "swarmforge"
    workflows: list[tuple[str, Path]] = []
    if (base / "swarmforge.conf").is_file():
        workflows.append(("default", base))
    workflows_dir = base / "workflows"
    if workflows_dir.is_dir():
        for child in sorted(workflows_dir.iterdir()):
            if child.is_dir() and (child / "swarmforge.conf").is_file():
                workflows.append((child.name, child))

    if args.json:
        _emit_json(
            {
                "project": str(project_dir),
                "workflows": [
                    {
                        "name": name,
                        "path": str(path),
                        "config_file": str(path / "swarmforge.conf"),
                    }
                    for name, path in workflows
                ],
            }
        )
        return

    if not workflows:
        print(f"No workflows found in {project_dir}. Create one with: swarmpy init {project_dir} -w development")
        return

    print(f"SwarmPy workflows for {project_dir}:")
    for name, path in workflows:
        print(f"  {name:<16} {path.relative_to(project_dir)}")


DOCTOR_DEPENDENCIES: list[tuple[str, bool]] = [
    ("uv", True),
    ("git", True),
    ("tmux", True),
    *[(agent, False) for agent in BACKEND_AGENTS],
    ("swarmpy", False),
]


def _dep_version(name: str) -> str | None:
    try:
        result = subprocess.run(
            [name, "--version"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    if result.returncode != 0:
        return None
    lines = result.stdout.strip().splitlines()
    return lines[0] if lines else None


def _doctor_required_overrides(config_file: Path) -> set[str]:
    # Intentionally permissive: silently skip blanks, comments, malformed lines,
    # unknown directives, and unsupported agent names. Strict validation belongs
    # to parse_config and issue #3 (validate --json); do not "improve" this into
    # hidden validation logic here.
    overrides: set[str] = set()
    try:
        text = config_file.read_text()
    except OSError:
        return overrides
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) != 4 or fields[0] != "window":
            continue
        agent = fields[2].lower()
        if agent in BACKEND_AGENTS:
            overrides.add(agent)
    return overrides


def cmd_doctor(args: argparse.Namespace) -> None:
    project_aware = args.project is not None or args.workflow is not None
    project_dir: Path | None = None
    workflow_name: str | None = None
    overrides: set[str] = set()
    if project_aware:
        project_dir = resolve_project_dir(args.project)
        workflow_name = args.workflow or workflow_from_context()
        paths = paths_for(project_dir, workflow_name)
        overrides = _doctor_required_overrides(paths.config_file)

    dependencies: list[dict] = []
    ok = True
    for name, base_required in DOCTOR_DEPENDENCIES:
        required = base_required or (name in overrides)
        path = shutil.which(name)
        found = path is not None
        version = _dep_version(name) if found else None
        if required and not found:
            ok = False
        dependencies.append(
            {
                "name": name,
                "required": required,
                "found": found,
                "path": path,
                "version": version,
            }
        )

    if args.json:
        _emit_json(
            {
                "ok": ok,
                "project": str(project_dir) if project_dir is not None else None,
                "workflow": workflow_name,
                "dependencies": dependencies,
            }
        )
        if not ok:
            raise SystemExit(1)
        return

    for dep in dependencies:
        marker = "[FOUND]  " if dep["found"] else "[MISSING]"
        tag = "required" if dep["required"] else "optional"
        location = dep["path"] or "not on PATH"
        version = f" ({dep['version']})" if dep["version"] else ""
        print(f"{marker} {dep['name']:<8} {tag:<8} {location}{version}")


def _inspect_running(session: str) -> bool:
    # Tmux fallback scoped to inspect: a missing tmux binary should not crash
    # the app-facing inspect output. Treat "tmux not on PATH" as "not running".
    # tmux_has_session and cmd_sessions are intentionally NOT modified; this
    # fallback is local to inspect so app-discovery flows still get a JSON
    # payload on machines where tmux has not yet been installed.
    try:
        return tmux_has_session(session)
    except OSError:
        return False


def cmd_inspect(args: argparse.Namespace) -> None:
    paths = resolve_project_paths(args.project, args.workflow)
    session = session_name_for_workflow(paths.project_id, paths.workflow)
    project_payload = {"id": paths.project_id, "path": str(paths.working_dir)}

    error: str | None = None
    if not paths.config_file.is_file():
        error = f"Config not found at {paths.config_file}"
    elif not paths.constitution_file.is_file():
        error = f"Constitution prompt not found at {paths.constitution_file}"

    if error is not None:
        if args.json:
            _emit_json(
                {
                    "ok": False,
                    "project": project_payload,
                    "workflow": {"name": paths.workflow, "session": session},
                    "error": error,
                }
            )
            raise SystemExit(1)
        fail(error)

    configs = parse_config(paths)
    running = _inspect_running(session)

    workflow_payload = {
        "name": paths.workflow,
        "session": session,
        "running": running,
        "config_file": str(paths.config_file),
        "settings_file": str(paths.settings_file),
        "constitution_file": str(paths.constitution_file),
        "state_dir": str(paths.state_dir),
        "logs_dir": str(paths.logs_dir),
    }
    roles_payload = [
        {
            "index": config.index,
            "role": config.role,
            "agent": config.agent,
            "worktree": config.worktree_name,
            "worktree_path": str(config.worktree_path),
            "window": config.window,
            "target": f"{session}:{config.window}",
            "running": running,
            "prompt_file": (
                None
                if config.agent == "none"
                else str(paths.swarmforge_dir / f"{config.role}.prompt")
            ),
            "pane_log": str(pane_log_path(paths, config.role)),
        }
        for config in configs
    ]
    message_log = paths.logs_dir / "agent_messages.log"

    if args.json:
        _emit_json(
            {
                "ok": True,
                "project": project_payload,
                "workflow": workflow_payload,
                "roles": roles_payload,
                "message_log": str(message_log),
            }
        )
        return

    running_label = "running" if running else "stopped"
    print(f"Inspect workflow: {paths.working_dir} [{paths.workflow}]")
    print(f"  session: {session} ({running_label})")
    print(f"  config:  {paths.config_file}")
    print(f"  state:   {paths.state_dir}")
    print(f"  logs:    {paths.logs_dir}")
    print()
    print("Roles:")
    for role in roles_payload:
        worktree_col = role["worktree"]
        if worktree_col not in SHARED_WORKTREE_NAMES:
            rel = Path(role["worktree_path"]).relative_to(paths.working_dir)
            worktree_col = f"{role['worktree']} ({rel})"
        print(f"  {role['index']}. {role['role']:<14} {role['agent']:<6} {worktree_col:<48} {role['target']} ({running_label})")


def cmd_validate(args: argparse.Namespace) -> None:
    paths = resolve_project_paths(args.project, args.workflow)
    configs, issues = collect_config_issues(paths)

    # Optional backend availability — warnings, not errors. Only check unique
    # agent backends that appear on validated lines, so a malformed unsupported
    # agent does not also produce a misleading backend_not_installed warning.
    warnings: list[ConfigIssue] = []
    seen_backends: set[str] = set()
    for cfg in configs:
        if cfg.agent in {"claude", "codex"} and cfg.agent not in seen_backends:
            seen_backends.add(cfg.agent)
            if shutil.which(cfg.agent) is None:
                warnings.append(ConfigIssue(
                    "backend_not_installed",
                    f"Configured agent '{cfg.agent}' is not on PATH",
                    None,
                    None,
                ))

    ok = not issues

    if args.json:
        _emit_json({
            "ok": ok,
            "project": str(paths.working_dir),
            "workflow": paths.workflow,
            "errors": [
                {"code": i.code, "message": i.message, "path": i.path, "line": i.line}
                for i in issues
            ],
            "warnings": [
                {"code": w.code, "message": w.message, "path": w.path, "line": w.line}
                for w in warnings
            ],
        })
        if not ok:
            raise SystemExit(1)
        return

    # Non-JSON path — minimal human summary, plain text. Header and OK on
    # stdout; errors and warnings on stderr. Matches cmd_doctor / cmd_inspect
    # discipline so machine consumers branch on --json.
    print(f"Workflow: {paths.workflow}  Project: {paths.working_dir}")
    if ok and not warnings:
        print("OK")
        return
    for issue in issues:
        loc = f" (line {issue.line})" if issue.line else ""
        print(f"error [{issue.code}] {issue.message}{loc}", file=sys.stderr)
    for w in warnings:
        print(f"warning [{w.code}] {w.message}", file=sys.stderr)
    if not ok:
        raise SystemExit(1)


def cmd_attach(args: argparse.Namespace) -> None:
    paths = resolve_project_paths(args.project, args.workflow)
    rows = read_sessions(paths.sessions_file)
    target = resolve_target(rows, args.target)
    tmux("select-window", "-t", target.target, check=False)
    os.execvp("tmux", ["tmux", "attach-session", "-t", target.session])


def cmd_cleanup(args: argparse.Namespace) -> None:
    sessions = args.sessions
    if not sessions:
        paths = resolve_project_paths(args.project, args.workflow)
        rows = read_sessions(paths.sessions_file)
        sessions = sorted({row.session for row in rows})

    for session in sessions:
        tmux("kill-session", "-t", session, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def add_project_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-p",
        "--project",
        metavar="DIR",
        help="project directory; defaults to $SWARMFORGE_PROJECT_DIR or current directory",
    )


def add_workflow_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-w",
        "--workflow",
        default=None,
        help="workflow name; defaults to $SWARMPY_WORKFLOW or 'default'",
    )


def build_parser() -> argparse.ArgumentParser:
    examples = """
examples:
  swarmpy install
  swarmpy init ~/code/my-project -w development
  swarmpy init ~/code/my-project -w content
  swarmpy launch ~/code/my-project -w development
  swarmpy launch ~/code/my-project -w development --worktree dev-run
  swarmpy sessions -p ~/code/my-project -w development
  swarmpy notify reviewer "Please review the latest changes" -p ~/code/my-project -w development
  swarmpy logs -f -p ~/code/my-project -w development
  swarmpy cleanup -p ~/code/my-project -w development
"""
    parser = argparse.ArgumentParser(
        prog=Path(sys.argv[0]).name,
        description="Single-file Python/uv SwarmForge runner using one tmux session per workflow and one window per role.",
        epilog=examples,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.set_defaults(command="launch")

    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    install_parser = subparsers.add_parser("install", help="install the global 'swarmpy' command")
    install_parser.add_argument("--bin-dir", default="~/.local/bin", help="directory for the swarmpy symlink, default: ~/.local/bin")
    install_parser.add_argument("--force", action="store_true", help="replace an existing swarmpy command")

    init_parser = subparsers.add_parser("init", help="create swarmforge config and role prompt scaffolding")
    init_parser.add_argument("working_dir", nargs="?", default=os.getcwd(), help="project directory, default: current directory")
    add_workflow_arg(init_parser)
    init_parser.add_argument("--force", action="store_true", help="overwrite existing scaffold files")

    launch_parser = subparsers.add_parser("launch", help="start the configured swarm")
    launch_parser.add_argument("working_dir", nargs="?", default=os.getcwd(), help="project directory, default: current directory")
    add_workflow_arg(launch_parser)
    launch_parser.add_argument("--worktree", metavar="NAME", help="run the workflow from a shared git worktree under .worktrees/<workflow>/<name>")

    notify_parser = subparsers.add_parser("notify", help="send a message to a role, index, or tmux target")
    add_project_arg(notify_parser)
    add_workflow_arg(notify_parser)
    notify_parser.add_argument("target", help="role name, index, workflow session, or session:window target")
    notify_parser.add_argument("message", nargs="+", help="message to type into the target tmux pane")

    log_parser = subparsers.add_parser("log", help="append a message to logs/<workflow>/agent_messages.log")
    add_project_arg(log_parser)
    add_workflow_arg(log_parser)
    log_parser.add_argument("role", help="actor name to write in the log")
    log_parser.add_argument("message", nargs="+", help="message to log")

    logs_parser = subparsers.add_parser("logs", help="show or follow workflow message logs or raw tmux pane logs")
    add_project_arg(logs_parser)
    add_workflow_arg(logs_parser)
    logs_parser.add_argument("-n", "--lines", type=int, default=80, help="number of lines to show before exiting/following, default: 80")
    logs_parser.add_argument("-f", "--follow", action="store_true", help="follow the log like tail -f")
    logs_parser.add_argument("--path", action="store_true", help="print the log file path and exit")
    pane_group = logs_parser.add_mutually_exclusive_group()
    pane_group.add_argument("--pane", metavar="ROLE", help="show/follow raw tmux output for one role/window")
    pane_group.add_argument("--all-panes", action="store_true", help="show/follow raw tmux output for all role windows")

    sessions_parser = subparsers.add_parser("sessions", help="list configured sessions and running status")
    add_project_arg(sessions_parser)
    add_workflow_arg(sessions_parser)
    sessions_parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")

    workflows_parser = subparsers.add_parser("workflows", help="list workflows configured in a project")
    add_project_arg(workflows_parser)
    workflows_parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")

    attach_parser = subparsers.add_parser("attach", help="attach to a workflow session and select a role window")
    add_project_arg(attach_parser)
    add_workflow_arg(attach_parser)
    attach_parser.add_argument("target", help="role name, index, workflow session, or session:window target")

    cleanup_parser = subparsers.add_parser("cleanup", help="kill workflow tmux sessions")
    add_project_arg(cleanup_parser)
    add_workflow_arg(cleanup_parser)
    cleanup_parser.add_argument("sessions", nargs="*", help="session names; if omitted, read from the project sessions file")

    doctor_parser = subparsers.add_parser("doctor", help="report local dependency and environment readiness")
    add_project_arg(doctor_parser)
    add_workflow_arg(doctor_parser)
    doctor_parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")

    inspect_parser = subparsers.add_parser("inspect", help="report configured workflow shape and runtime status")
    add_project_arg(inspect_parser)
    add_workflow_arg(inspect_parser)
    inspect_parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")

    validate_parser = subparsers.add_parser("validate", help="validate workflow config without launching")
    add_project_arg(validate_parser)
    add_workflow_arg(validate_parser)
    validate_parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")

    return parser


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)

    # Friendly shortcuts:
    #   swarm.py /project       -> swarm.py launch /project
    #   swarm.py help notify    -> swarm.py notify --help
    if argv and argv[0] == "help":
        argv = ["--help"] if len(argv) == 1 else [argv[1], "--help"]

    commands = {"install", "init", "launch", "notify", "log", "logs", "sessions", "workflows", "attach", "cleanup", "doctor", "inspect", "validate"}
    if argv and argv[0] not in commands and not argv[0].startswith("-"):
        argv = ["launch", *argv]

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "install":
        install_cli(args.bin_dir, args.force)
    elif args.command == "init":
        init_project(args.working_dir, args.workflow or "default", args.force)
    elif args.command == "launch":
        launch(args.working_dir if hasattr(args, "working_dir") else os.getcwd(), args.workflow or "default", args.worktree)
    elif args.command == "notify":
        cmd_notify(args)
    elif args.command == "log":
        cmd_log(args)
    elif args.command == "logs":
        cmd_logs(args)
    elif args.command == "sessions":
        cmd_sessions(args)
    elif args.command == "workflows":
        cmd_workflows(args)
    elif args.command == "attach":
        cmd_attach(args)
    elif args.command == "cleanup":
        cmd_cleanup(args)
    elif args.command == "doctor":
        cmd_doctor(args)
    elif args.command == "inspect":
        cmd_inspect(args)
    elif args.command == "validate":
        cmd_validate(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
