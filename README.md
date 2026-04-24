# swarmpy

A single-file Python/uv port of SwarmForge.

The goal is intentionally boring:

- one file: `swarm.py`
- one global command: `swarmpy`
- no shell helper scripts
- no Terminal.app / `osascript`
- one `tmux` session per workflow
- one `tmux` window per agent role
- git worktrees when configured
- multiple workflows per project
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
```

Without installing, you can still run:

```bash
uv run --script swarm.py [COMMAND]
```

## Workflows

A project can have many workflows. Each workflow has its own config, role prompts, settings, tmux session, tmux windows, worktrees, logs, and agent context.

Tmux grouping is workflow-first:

```text
swarmpy-development          # tmux session
  architect                  # tmux window
  coder                      # tmux window
  reviewer                   # tmux window
  logger                     # tmux window

swarmpy-seo                  # tmux session
  collector                  # tmux window
  analyst                    # tmux window
  writer                     # tmux window
  reviewer                   # tmux window
  logger                     # tmux window
```

Default workflow layout:

```text
swarmforge/
  swarmforge.conf
  settings.env
  constitution.prompt
  architect.prompt
  coder.prompt
  reviewer.prompt
```

Named workflow layout:

```text
swarmforge/
  workflows/
    development/
      swarmforge.conf
      settings.env
      constitution.prompt
      architect.prompt
      coder.prompt
      reviewer.prompt
    content/
      swarmforge.conf
      settings.env
      constitution.prompt
      researcher.prompt
      writer.prompt
      reviewer.prompt
```

Create two workflows in the same project:

```bash
swarmpy init /path/to/project -w development
swarmpy init /path/to/project -w content
```

List workflows:

```bash
swarmpy workflows -p /path/to/project
```

Launch one workflow:

```bash
swarmpy launch /path/to/project -w development
```

Launch another workflow independently:

```bash
swarmpy launch /path/to/project -w content
```

Workflow-specific runtime state:

```text
.swarmforge/<workflow>/
.worktrees/<workflow>/
logs/<workflow>/agent_messages.log
agent_context/<workflow>/
```

Workflow-specific settings live in:

```text
swarmforge/workflows/<workflow>/settings.env
```

That file is sourced before each agent starts, so you can put environment variables there, for example:

```env
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
GITHUB_LABEL=bug
REPORT_OUTPUT_DIR=agent_context/content/reports
```

## Config

Each workflow has a `swarmforge.conf`:

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
- any other value creates `.worktrees/<workflow>/<name>` on branch `swarmpy-<workflow>-<name>`

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
install    install the global `swarmpy` command
init       create workflow config and role prompt scaffolding
launch     start the configured workflow
workflows  list workflows configured in a project
sessions   list configured sessions and running status
notify     send a message to a role, index, or tmux target
log        append a message to logs/<workflow>/agent_messages.log
logs       show or follow logs/<workflow>/agent_messages.log
attach     attach to a workflow session and select a role window
cleanup    kill workflow tmux sessions
```

Create workflow scaffolding:

```bash
swarmpy init /path/to/project -w development
```

This creates:

```text
swarmforge/workflows/development/swarmforge.conf
swarmforge/workflows/development/settings.env
swarmforge/workflows/development/constitution.prompt
swarmforge/workflows/development/architect.prompt
swarmforge/workflows/development/coder.prompt
swarmforge/workflows/development/reviewer.prompt
```

Launch:

```bash
swarmpy launch /path/to/project -w development
```

List sessions:

```bash
swarmpy sessions -p /path/to/project -w development
```

Attach to a role:

```bash
swarmpy attach coder -p /path/to/project -w development
```

Notify an agent:

```bash
swarmpy notify coder "Please implement the next slice." -p /path/to/project -w development
```

Append to workflow log:

```bash
swarmpy log reviewer "Review started." -p /path/to/project -w development
```

Show recent workflow logs:

```bash
swarmpy logs -p /path/to/project -w development
```

Follow workflow message logs:

```bash
swarmpy logs -f -p /path/to/project -w development
```

Show raw tmux output for one agent/window:

```bash
swarmpy logs --pane coder -p /path/to/project -w development
```

Follow raw tmux output for one agent/window:

```bash
swarmpy logs --pane coder -f -p /path/to/project -w development
```

Follow raw tmux output for every agent/window in the workflow:

```bash
swarmpy logs --all-panes -f -p /path/to/project -w development
```

Show the log file path:

```bash
swarmpy logs --path -p /path/to/project -w development
```

Cleanup all sessions for a workflow:

```bash
swarmpy cleanup -p /path/to/project -w development
```

Cleanup explicit sessions:

```bash
swarmpy cleanup swarmpy-development
```

## Tests

Run the regression suite:

```bash
python3 test.py
```

The tests cover CLI help, workflow scaffolding, global `swarmpy` installation, and a logger-only tmux workflow with notify/log/cleanup.
