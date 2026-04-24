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
import os
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

SESSION_PREFIX = "swarmforge"
AGENT_WINDOW = "swarm"
SUPPORTED_AGENTS = {"claude", "codex", "none"}

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
    display: str
    worktree_path: Path


@dataclass(frozen=True)
class ProjectPaths:
    working_dir: Path
    script_path: Path
    swarmforge_dir: Path
    worktrees_dir: Path
    config_file: Path
    constitution_file: Path
    state_dir: Path
    sessions_file: Path
    prompts_dir: Path


def q(value: str | Path) -> str:
    return shlex.quote(str(value))


def fail(message: str, code: int = 1) -> None:
    print(f"{RED}Error:{RESET} {message}", file=sys.stderr)
    raise SystemExit(code)


def run(cmd: list[str], *, cwd: Path | None = None, check: bool = True, stdout=None, stderr=None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=check, stdout=stdout, stderr=stderr, text=True)


def check_dependency(name: str) -> None:
    if shutil.which(name) is None:
        fail(f"'{name}' is required but not installed.")


def paths_for(working_dir: Path) -> ProjectPaths:
    working_dir = working_dir.expanduser().resolve()
    script_path = Path(__file__).expanduser().resolve()
    swarmforge_dir = working_dir / "swarmforge"
    state_dir = working_dir / ".swarmforge"
    return ProjectPaths(
        working_dir=working_dir,
        script_path=script_path,
        swarmforge_dir=swarmforge_dir,
        worktrees_dir=working_dir / ".worktrees",
        config_file=swarmforge_dir / "swarmforge.conf",
        constitution_file=swarmforge_dir / "constitution.prompt",
        state_dir=state_dir,
        sessions_file=state_dir / "sessions.tsv",
        prompts_dir=state_dir / "prompts",
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


def display_name_for_role(role: str) -> str:
    return " ".join(part.capitalize() for part in role.replace("-", " ").replace("_", " ").split())


def session_name_for_role(role: str) -> str:
    return f"{SESSION_PREFIX}-{role}"


def parse_config(paths: ProjectPaths) -> list[WindowConfig]:
    if not paths.config_file.is_file():
        fail(f"Config not found at {paths.config_file}")
    if not paths.constitution_file.is_file():
        fail(f"Constitution prompt not found at {paths.constitution_file}")

    configs: list[WindowConfig] = []
    roles: set[str] = set()
    worktrees: set[str] = set()

    for line_no, raw in enumerate(paths.config_file.read_text().splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        fields = line.split()
        if len(fields) != 4:
            fail(f"Invalid config line {line_no}: {line}")

        keyword, role, agent, worktree_name = fields
        agent = agent.lower()

        if keyword != "window":
            fail(f"Unknown config directive on line {line_no}: {keyword}")
        if role in roles:
            fail(f"Duplicate role '{role}' in {paths.config_file}")
        if worktree_name not in {"none", "master"} and worktree_name in worktrees:
            fail(f"Duplicate worktree '{worktree_name}' in {paths.config_file}")
        if "/" in worktree_name or worktree_name in {".", ".."}:
            fail(f"Invalid worktree '{worktree_name}' for role '{role}'")
        if agent not in SUPPORTED_AGENTS:
            fail(f"Unsupported agent '{agent}' for role '{role}'")
        if agent != "none" and not (paths.swarmforge_dir / f"{role}.prompt").is_file():
            fail(f"Missing role prompt {paths.swarmforge_dir / f'{role}.prompt'}")

        roles.add(role)
        if worktree_name not in {"none", "master"}:
            worktrees.add(worktree_name)
            worktree_path = paths.worktrees_dir / worktree_name
        else:
            worktree_path = paths.working_dir

        configs.append(
            WindowConfig(
                index=len(configs) + 1,
                role=role,
                agent=agent,
                worktree_name=worktree_name,
                session=session_name_for_role(role),
                display=display_name_for_role(role),
                worktree_path=worktree_path,
            )
        )

    if not configs:
        fail(f"No windows defined in {paths.config_file}")
    return configs


def write_sessions_file(paths: ProjectPaths, configs: list[WindowConfig]) -> None:
    lines = [f"{c.index}\t{c.role}\t{c.session}\t{c.display}\t{c.agent}" for c in configs]
    paths.sessions_file.write_text("\n".join(lines) + "\n")


def prepare_workspace(paths: ProjectPaths, configs: list[WindowConfig]) -> None:
    for directory in [
        paths.working_dir / "logs",
        paths.working_dir / "agent_context",
        paths.working_dir / "features",
        paths.state_dir,
        paths.prompts_dir,
        paths.worktrees_dir,
    ]:
        directory.mkdir(parents=True, exist_ok=True)

    write_sessions_file(paths, configs)


def prepare_worktrees(paths: ProjectPaths, configs: list[WindowConfig]) -> None:
    for config in configs:
        if config.worktree_name in {"none", "master"}:
            continue
        if (config.worktree_path / ".git").exists():
            continue
        branch_name = f"swarmforge-{config.worktree_name}"
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
        if config.agent in {"claude", "codex"}:
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


def create_role_session(config: WindowConfig) -> None:
    tmux("new-session", "-d", "-s", config.session, "-n", AGENT_WINDOW)
    tmux("rename-window", "-t", f"{config.session}:{AGENT_WINDOW}", config.display)
    tmux("set-window-option", "-t", f"{config.session}:{config.display}", "allow-rename", "off")


def write_agent_instruction_file(paths: ProjectPaths, role: str) -> Path:
    prompt_file = paths.prompts_dir / f"{role}.md"
    prompt_file.write_text(
        f"Read swarmforge/constitution.prompt, then read every file it refers to recursively, and obey all of those instructions.\n"
        f"Read swarmforge/{role}.prompt, then read every file it refers to recursively, and follow all of those instructions.\n"
        f"To notify another role, run: uv run --script {paths.script_path} notify <role-or-index> '<message>'\n"
        f"To write a swarm log entry, run: uv run --script {paths.script_path} log {role} '<message>'\n"
    )
    return prompt_file


def script_command(paths: ProjectPaths) -> str:
    return f"uv run --script {q(paths.script_path)}"


def base_environment_command(paths: ProjectPaths) -> str:
    return f"export SWARMFORGE_PROJECT_DIR={q(paths.working_dir)} SWARMFORGE_SCRIPT={q(paths.script_path)}"


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
    target = first_pane_target(config.session)

    if config.agent == "none":
        if config.role == "logger":
            command = f"cd {q(paths.working_dir)} && touch logs/agent_messages.log && tail -f logs/agent_messages.log"
            tmux("send-keys", "-t", target, command, "Enter")
        print(f"  {CYAN}[{config.display}]{RESET} opened without agent backend")
        return

    prompt_file = write_agent_instruction_file(paths, config.role)
    env_cmd = base_environment_command(paths)

    if config.agent == "claude":
        command = (
            f"{env_cmd} && cd {q(config.worktree_path)} && "
            f"claude --append-system-prompt-file {q(prompt_file)} "
            f"--permission-mode acceptEdits -n {q('SwarmForge ' + config.display)} "
            f'"$(cat {q(prompt_file)})"'
        )
    elif config.agent == "codex":
        command = (
            f"{env_cmd} && cd {q(config.worktree_path)} && "
            f"codex -C {q(config.worktree_path)} "
            f'"$(cat {q(prompt_file)})"'
        )
    else:
        fail(f"Unsupported agent '{config.agent}' for role '{config.role}'")

    if cleanup_owner == config.index:
        cleanup_cmd = f"{script_command(paths)} cleanup " + " ".join(q(c.session) for c in configs)
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


def launch(working_dir_arg: str) -> None:
    working_dir = Path(working_dir_arg)
    if not working_dir.exists():
        fail(f"Working directory does not exist: {working_dir}")

    paths = paths_for(working_dir)

    check_dependency("uv")
    check_dependency("tmux")
    check_dependency("git")

    initialize_git_repo(paths.working_dir)
    configs = parse_config(paths)
    check_backend_dependencies(configs)
    prepare_workspace(paths, configs)
    prepare_worktrees(paths, configs)
    cleanup_owner = choose_cleanup_owner(configs)

    for config in configs:
        if tmux_has_session(config.session):
            print(f"{YELLOW}Existing SwarmForge session found: {config.session}. Killing it...{RESET}")
            tmux("kill-session", "-t", config.session, check=False)

    print_banner()
    print(f"{GREEN}Launching SwarmForge tmux sessions...{RESET}")
    for config in configs:
        create_role_session(config)

    print(f"{GREEN}Starting agents...{RESET}")
    for config in configs:
        launch_role(paths, configs, config, cleanup_owner)

    print()
    print(f"{GREEN}{BOLD}SwarmForge is ready.{RESET}")
    print(f"Working directory: {paths.working_dir}")
    print("Sessions:")
    for config in configs:
        print(f"  {config.display}: {config.session}")
    print()
    print(f"{GREEN}Tip: Notify with: uv run --script {paths.script_path} notify <role-or-index> \"message\"{RESET}")
    print(f"{GREEN}Tip: Reattach with 'tmux attach-session -t <session-name>'.{RESET}")
    if cleanup_owner is not None:
        owner = next(c for c in configs if c.index == cleanup_owner)
        print(f"{GREEN}Tip: Cleanup is owned by {owner.display}; when it exits, all swarm sessions are killed.{RESET}")
    print()


def project_dir_from_context() -> Path:
    env_project = os.environ.get("SWARMFORGE_PROJECT_DIR")
    if env_project:
        return Path(env_project).expanduser().resolve()

    return Path.cwd().resolve()


def read_sessions(sessions_file: Path) -> list[tuple[str, str, str, str, str]]:
    if not sessions_file.is_file():
        fail(f"Sessions file not found: {sessions_file}")

    rows: list[tuple[str, str, str, str, str]] = []
    for raw in sessions_file.read_text().splitlines():
        fields = raw.split("\t")
        if len(fields) == 5:
            rows.append(tuple(fields))  # type: ignore[arg-type]
    return rows


def resolve_project_dir(project: str | None) -> Path:
    if project:
        return Path(project).expanduser().resolve()
    return project_dir_from_context()


def resolve_session(rows: list[tuple[str, str, str, str, str]], target: str) -> str:
    normalized = target.lower()
    for index, role, session, _display, _agent in rows:
        if normalized in {index.lower(), role.lower(), session.lower()}:
            return session
    fail(f"Unknown target: {target}")


def append_log(project_dir: Path, actor: str, message: str) -> None:
    log_file = project_dir / "logs" / "agent_messages.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with log_file.open("a") as f:
        f.write(f"[{timestamp}] [{actor}] {message}\n")


def cmd_notify(args: argparse.Namespace) -> None:
    project_dir = resolve_project_dir(args.project)
    rows = read_sessions(project_dir / ".swarmforge" / "sessions.tsv")
    target_session = resolve_session(rows, args.target)
    message = " ".join(args.message)

    append_log(project_dir, target_session, message)

    pane_target = first_pane_target(target_session)
    tmux("send-keys", "-t", pane_target, "-l", "--", message)
    time.sleep(0.15)
    tmux("send-keys", "-t", pane_target, "C-m")
    time.sleep(0.05)
    tmux("send-keys", "-t", pane_target, "C-j")


def cmd_log(args: argparse.Namespace) -> None:
    project_dir = resolve_project_dir(args.project)
    message = " ".join(args.message)
    append_log(project_dir, args.role, message)
    print(f"[{args.role}] {message}")


def cmd_sessions(args: argparse.Namespace) -> None:
    project_dir = resolve_project_dir(args.project)
    rows = read_sessions(project_dir / ".swarmforge" / "sessions.tsv")
    print(f"Swarm sessions for {project_dir}:")
    for index, role, session, display, agent in rows:
        marker = "running" if tmux_has_session(session) else "stopped"
        print(f"  {index}. {role:<16} {session:<24} {agent:<6} {marker}  ({display})")


def cmd_attach(args: argparse.Namespace) -> None:
    project_dir = resolve_project_dir(args.project)
    rows = read_sessions(project_dir / ".swarmforge" / "sessions.tsv")
    session = resolve_session(rows, args.target)
    os.execvp("tmux", ["tmux", "attach-session", "-t", session])


def cmd_cleanup(args: argparse.Namespace) -> None:
    sessions = args.sessions
    if not sessions:
        project_dir = resolve_project_dir(args.project)
        rows = read_sessions(project_dir / ".swarmforge" / "sessions.tsv")
        sessions = [session for _index, _role, session, _display, _agent in rows]

    for session in sessions:
        tmux("kill-session", "-t", session, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def add_project_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-p",
        "--project",
        metavar="DIR",
        help="project directory; defaults to $SWARMFORGE_PROJECT_DIR or current directory",
    )


def build_parser() -> argparse.ArgumentParser:
    examples = """
examples:
  swarm.py .
  swarm.py launch ~/code/my-project
  swarm.py sessions -p ~/code/my-project
  swarm.py attach coder -p ~/code/my-project
  swarm.py notify reviewer "Please review the latest changes" -p ~/code/my-project
  swarm.py log architect "Plan updated" -p ~/code/my-project
  swarm.py cleanup -p ~/code/my-project
"""
    parser = argparse.ArgumentParser(
        prog="swarm.py",
        description="Single-file Python/uv SwarmForge runner using tmux sessions and git worktrees.",
        epilog=examples,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.set_defaults(command="launch")

    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    launch_parser = subparsers.add_parser("launch", help="start the configured swarm")
    launch_parser.add_argument("working_dir", nargs="?", default=os.getcwd(), help="project directory, default: current directory")

    notify_parser = subparsers.add_parser("notify", help="send a message to a role, index, or tmux session")
    add_project_arg(notify_parser)
    notify_parser.add_argument("target", help="role name, session index, or tmux session name")
    notify_parser.add_argument("message", nargs="+", help="message to type into the target tmux pane")

    log_parser = subparsers.add_parser("log", help="append a message to logs/agent_messages.log")
    add_project_arg(log_parser)
    log_parser.add_argument("role", help="actor name to write in the log")
    log_parser.add_argument("message", nargs="+", help="message to log")

    sessions_parser = subparsers.add_parser("sessions", help="list configured sessions and running status")
    add_project_arg(sessions_parser)

    attach_parser = subparsers.add_parser("attach", help="attach to a role, index, or tmux session")
    add_project_arg(attach_parser)
    attach_parser.add_argument("target", help="role name, session index, or tmux session name")

    cleanup_parser = subparsers.add_parser("cleanup", help="kill swarm tmux sessions")
    add_project_arg(cleanup_parser)
    cleanup_parser.add_argument("sessions", nargs="*", help="session names; if omitted, read from the project sessions file")

    return parser


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)

    # Friendly shortcuts:
    #   swarm.py /project       -> swarm.py launch /project
    #   swarm.py help notify    -> swarm.py notify --help
    if argv and argv[0] == "help":
        argv = ["--help"] if len(argv) == 1 else [argv[1], "--help"]

    commands = {"launch", "notify", "log", "sessions", "attach", "cleanup"}
    if argv and argv[0] not in commands and not argv[0].startswith("-"):
        argv = ["launch", *argv]

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "launch":
        launch(args.working_dir if hasattr(args, "working_dir") else os.getcwd())
    elif args.command == "notify":
        cmd_notify(args)
    elif args.command == "log":
        cmd_log(args)
    elif args.command == "sessions":
        cmd_sessions(args)
    elif args.command == "attach":
        cmd_attach(args)
    elif args.command == "cleanup":
        cmd_cleanup(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
