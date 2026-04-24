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

## Commands

Launch:

```bash
uv run --script swarm.py /path/to/project
```

Notify an agent:

```bash
uv run --script swarm.py notify coder "Please implement the next slice."
```

Append to swarm log:

```bash
uv run --script swarm.py log reviewer "Review started."
```

Cleanup sessions:

```bash
uv run --script swarm.py cleanup swarmforge-architect swarmforge-coder swarmforge-reviewer
```

Attach manually:

```bash
tmux attach-session -t swarmforge-coder
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
