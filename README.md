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

## Install global CLI

Install the global `swarmpy` command once:

```bash
uv run --script swarm.py install
```

This creates a symlink:

```text
~/.local/bin/swarmpy -> /path/to/swarm.py
```

Make sure `~/.local/bin` is in your `PATH`:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Then use:

```bash
swarmpy --help
swarmpy init /path/to/project
swarmpy launch /path/to/project
```

Without installing, you can still run:

```bash
uv run --script swarm.py [WORKING_DIR]
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
swarmpy --help
```

Show help for a command:

```bash
swarmpy help notify
swarmpy cleanup --help
```

Commands:

```text
install   install the global `swarmpy` command
init      create swarmforge config and role prompt scaffolding
launch    start the configured swarm
notify    send a message to a role, index, or tmux session
log       append a message to logs/agent_messages.log
sessions  list configured sessions and running status
attach    attach to a role, index, or tmux session
cleanup   kill swarm tmux sessions
```

Create the project wiring/scaffolding:

```bash
swarmpy init /path/to/project
```

This creates:

```text
swarmforge/swarmforge.conf
swarmforge/constitution.prompt
swarmforge/architect.prompt
swarmforge/coder.prompt
swarmforge/reviewer.prompt
```

It also initializes git for a new project and adds SwarmPy runtime paths to `.gitignore`.

Launch:

```bash
swarmpy /path/to/project
# or
swarmpy launch /path/to/project
```

List sessions:

```bash
swarmpy sessions -p /path/to/project
```

Attach to a role:

```bash
swarmpy attach coder -p /path/to/project
```

Notify an agent:

```bash
swarmpy notify coder "Please implement the next slice." -p /path/to/project
```

Append to swarm log:

```bash
swarmpy log reviewer "Review started." -p /path/to/project
```

Cleanup all sessions for a project:

```bash
swarmpy cleanup -p /path/to/project
```

Cleanup explicit sessions:

```bash
swarmpy cleanup swarmforge-architect swarmforge-coder swarmforge-reviewer
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
