# swarmpy

A single-file Python/uv port of SwarmForge.

The goal is intentionally boring:

- one file: `swarm.py`
- no shell helper scripts
- no Terminal.app / `osascript`
- only `tmux` sessions/windows and git worktrees
- simple config-driven agent launch

## Requirements

- `uv`
- `tmux`
- `git`
- optional agent CLIs depending on config: `claude`, `codex`

## Usage

```bash
uv run --script swarm.py [WORKING_DIR]
```

or:

```bash
chmod +x swarm.py
./swarm.py [WORKING_DIR]
```

If `WORKING_DIR` is omitted, the current directory is used.

## Project layout

A managed project needs:

```text
swarmforge/
  swarmforge.conf
  constitution.prompt
  architect.prompt
  coder.prompt
  reviewer.prompt
```

Example `swarmforge/swarmforge.conf`:

```conf
window architect claude master
window coder codex coder
window reviewer codex reviewer
window logger none none
```

Format:

```conf
window <role> <agent> <worktree>
```

Agents:

- `claude`
- `codex`
- `none`

Worktree behavior:

- `master` uses the main working directory
- `none` uses the main working directory and creates no worktree
- any other value creates `.worktrees/<name>` on branch `swarmforge-<name>`

## CLI

Show top-level help:

```bash
uv run --script swarm.py --help
```

Show help for a command:

```bash
uv run --script swarm.py help notify
uv run --script swarm.py cleanup --help
```

Commands:

```text
launch    start the configured swarm
notify    send a message to a role, index, or tmux session
log       append a message to logs/agent_messages.log
sessions  list configured sessions and running status
attach    attach to a role, index, or tmux session
cleanup   kill swarm tmux sessions
```

Launch:

```bash
uv run --script swarm.py /path/to/project
# or
uv run --script swarm.py launch /path/to/project
```

List sessions:

```bash
uv run --script swarm.py sessions -p /path/to/project
```

Attach to a role:

```bash
uv run --script swarm.py attach coder -p /path/to/project
```

Notify an agent:

```bash
uv run --script swarm.py notify coder "Please implement the next slice." -p /path/to/project
```

Append to swarm log:

```bash
uv run --script swarm.py log reviewer "Review started." -p /path/to/project
```

Cleanup all sessions for a project:

```bash
uv run --script swarm.py cleanup -p /path/to/project
```

Cleanup explicit sessions:

```bash
uv run --script swarm.py cleanup swarmforge-architect swarmforge-coder swarmforge-reviewer
```

## Runtime files in the managed project

`swarmpy` creates local runtime state inside the managed project:

```text
.swarmforge/
.worktrees/
logs/
agent_context/
features/
```

These are added to `.gitignore` when initializing a new repository.
