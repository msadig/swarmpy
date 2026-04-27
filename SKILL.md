---
name: swarmpy-workflows
description: Use when setting up, launching, inspecting, debugging, or coordinating SwarmPy/Swarmpy agent workflows. Teaches agents the project/workflow directory model, swarmforge.conf semantics, tmux sessions/windows, git worktrees, logs, agent_context, notify/log commands, and safe workflow setup beyond `swarmpy --help`.
---

# SwarmPy Workflow Operator

SwarmPy (`swarmpy`) is a single-file Python/uv CLI for running a workflow as one `tmux` session with one window per agent role. Use this skill whenever the user wants to create, run, monitor, or modify a SwarmPy workflow.

The important part is not the command list; it is understanding which directory is the target project, which files are source-of-truth workflow config, and which files are runtime state.

## Mental model

A SwarmPy project can contain multiple named workflows. Each workflow has:

- source config and prompts under `swarmforge/`
- runtime state under `.swarmforge/<workflow>/`
- optional git worktrees under `.worktrees/<workflow>/`
- shared communication logs under `logs/<workflow>/`
- durable agent artifacts under `agent_context/<workflow>/`
- one tmux session named `swarmpy-<project>-<workflow>`
- one tmux window per configured role

Default workflow layout:

```text
PROJECT/
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
PROJECT/
  swarmforge/
    workflows/
      development/
        swarmforge.conf
        settings.env
        constitution.prompt
        architect.prompt
        coder.prompt
        reviewer.prompt
```

Runtime layout created by `launch`:

```text
PROJECT/
  .swarmforge/<workflow>/
    sessions.tsv          # role/index -> tmux target registry
    prompts/<role>.md     # generated startup instruction files; do not hand-edit
  .worktrees/<workflow>/
    <worktree-name>/      # generated git worktrees
  logs/<workflow>/
    agent_messages.log    # notify/log messages
    panes/<role>.log      # raw tmux pane output
  agent_context/<workflow>/
    ...                   # workflow artifacts agents should preserve/share
  features/               # created if missing
```

Source-of-truth files are in `swarmforge/`. Runtime files are generated and normally ignored by git.

## First rule: identify the target project directory

Do not assume the current shell directory is the project that should receive a swarm. Before running commands, determine:

- `PROJECT`: absolute path to the user’s target repository or workspace
- `WORKFLOW`: named workflow, usually `development`, `content`, `research`, `review`, or `default`
- desired roles and backends (`claude`, `codex`, or `none`)
- whether roles should share the main checkout, get separate worktrees, or share one workflow worktree

Use absolute paths in examples and commands when there is any ambiguity.

## Dependencies

Check dependencies before launch:

```bash
command -v uv
command -v tmux
command -v git
```

Agent backends are required only for configured roles:

```bash
command -v claude   # needed for `window <role> claude <worktree>`
command -v codex    # needed for `window <role> codex <worktree>`
```

If the global command is not installed, either install it:

```bash
uv run --script /path/to/swarm.py install
export PATH="$HOME/.local/bin:$PATH"
```

or call the script directly:

```bash
uv run --script /path/to/swarm.py <command>
```

## Standard workflow setup protocol

Use this procedure when the user asks to set up a workflow.

### 1. Initialize scaffold

```bash
swarmpy init "$PROJECT" -w "$WORKFLOW"
```

This creates the workflow config, settings file, constitution, and default role prompts. Never use `--force` unless the user explicitly wants to overwrite existing workflow files.

### 2. Inspect generated files

For a named workflow:

```bash
ls -la "$PROJECT/swarmforge/workflows/$WORKFLOW"
```

For the default workflow:

```bash
ls -la "$PROJECT/swarmforge"
```

### 3. Edit `swarmforge.conf`

Each non-comment line is:

```conf
window <role> <agent> <worktree>
```

Supported agents:

- `claude` — launches Claude Code in the role’s working directory
- `codex` — launches Codex in the role’s working directory
- `none` — opens a tmux window without an agent backend; useful for `logger` or manual panes

Worktree field semantics:

- `master` — use the main project checkout
- `none` — use the main project checkout and do not create a worktree
- any other name — create/use `PROJECT/.worktrees/<workflow>/<name>` on branch `swarmpy-<project>-<workflow>-<name>`

Important constraints:

- role names must be unique
- non-shared worktree names must be unique within one workflow
- worktree names cannot contain `/`, `.` or `..`
- every non-`none` role must have a matching `<role>.prompt` file in the workflow directory

Default coding workflow:

```conf
window architect claude master
window coder codex coder
window reviewer codex reviewer
window logger none none
```

Shared-worktree coding workflow:

```conf
window architect claude master
window coder codex feature-slice
window reviewer codex review-slice
window logger none none
```

Content/research workflow example:

```conf
window researcher claude researcher
window analyst codex analyst
window writer claude writer
window reviewer codex reviewer
window logger none none
```

Create prompt files for every non-`none` role, for example `researcher.prompt`, `analyst.prompt`, `writer.prompt`, and `reviewer.prompt`.

### 4. Edit the constitution and role prompts

The constitution applies to every role. Keep it short, explicit, and workflow-specific.

Each role prompt should say:

- what the role owns
- what inputs it should read first
- what outputs it should produce
- how to signal completion/blockers
- what checks it must run before notifying another role

Agents launched by SwarmPy receive a generated startup instruction telling them to read:

1. `constitution.prompt`
2. their own `<role>.prompt`
3. recursively any files those prompts reference

Do not hand-edit `.swarmforge/<workflow>/prompts/<role>.md`; it is generated. Edit the source prompt in `swarmforge/...` instead.

### 5. Configure workflow settings

`settings.env` is sourced before each agent starts. Put workflow-specific environment variables here:

```env
REPORT_OUTPUT_DIR=agent_context/content/reports
GITHUB_LABEL=bug
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
```

Be careful with secrets: `settings.env` lives under `swarmforge/` and may be tracked unless the project ignores it.

### 6. Launch the workflow

```bash
swarmpy launch "$PROJECT" -w "$WORKFLOW"
```

To force every non-`none` role into one shared workflow worktree regardless of per-role config:

```bash
swarmpy launch "$PROJECT" -w "$WORKFLOW" --worktree nightly
```

This creates/uses:

```text
PROJECT/.worktrees/<workflow>/nightly
```

Relaunching an existing workflow kills the previous tmux session with the same session name before starting a new one.

## Operating a running workflow

List workflows in a project:

```bash
swarmpy workflows -p "$PROJECT"
swarmpy workflows -p "$PROJECT" --json
```

List configured sessions/windows and running status:

```bash
swarmpy sessions -p "$PROJECT" -w "$WORKFLOW"
swarmpy sessions -p "$PROJECT" -w "$WORKFLOW" --json
```

`--json` is the agent-friendly form — it emits a stable schema on stdout for `workflows`, `sessions`, `doctor`, `inspect`, and `validate`:

- `workflows --json` → `{ "project", "workflows": [{ "name", "path", "config_file" }] }`. Exits 0 even when empty.
- `sessions --json` → `{ "project", "workflow", "sessions": [{ "index", "role", "session", "window", "target", "display", "agent", "running" }] }`. If `sessions.tsv` is missing, the same JSON shape is printed with an extra `error` field and the process exits 1 — branch on `error`, not on stderr.
- `doctor --json` / `inspect --json` → top-level `ok: true|false`; on `ok: false` the payload includes a single string `error` key and exit code is 1. `inspect --json` also emits `project`, `workflow`, `roles[]`, and `message_log` on success; on `ok: false` the `workflow` object is restricted to `{name, session}` and `roles[]` and `message_log` are omitted.
- `validate --json` → `{ "ok", "project", "workflow", "errors": [{ "code", "message", "path", "line" }], "warnings": [...] }`. `ok: true` with `errors: []` on success (warnings may still be present and do not fail). `ok: false` with at least one entry in `errors` and exit 1 on any config issue. `validate` is read-only and does not launch tmux or mutate project state.

Attach to a role window:

```bash
swarmpy attach coder -p "$PROJECT" -w "$WORKFLOW"
```

Send a message to a role, index, session, or `session:window` target:

```bash
swarmpy notify coder "Please implement the next slice." -p "$PROJECT" -w "$WORKFLOW"
swarmpy notify 3 "Please review the latest changes." -p "$PROJECT" -w "$WORKFLOW"
```

Append a message to the shared workflow log without sending it to a tmux pane:

```bash
swarmpy log architect "Plan approved; coder can start slice 1." -p "$PROJECT" -w "$WORKFLOW"
```

Show or follow shared workflow messages:

```bash
swarmpy logs -p "$PROJECT" -w "$WORKFLOW"
swarmpy logs -f -p "$PROJECT" -w "$WORKFLOW"
```

Show or follow raw pane output:

```bash
swarmpy logs --pane coder -p "$PROJECT" -w "$WORKFLOW"
swarmpy logs --pane coder -f -p "$PROJECT" -w "$WORKFLOW"
swarmpy logs --all-panes -f -p "$PROJECT" -w "$WORKFLOW"
```

Print log path:

```bash
swarmpy logs --path -p "$PROJECT" -w "$WORKFLOW"
```

Clean up tmux session(s):

```bash
swarmpy cleanup -p "$PROJECT" -w "$WORKFLOW"
swarmpy cleanup swarmpy-myproject-development
```

`cleanup` kills tmux sessions. It does not remove git worktrees or source config.

## Inside a launched agent window

SwarmPy exports useful environment variables before starting each backend:

```text
SWARMFORGE_PROJECT_DIR=<absolute project path>
SWARMPY_WORKFLOW=<workflow>
SWARMPY=<swarmpy command or uv script command>
SWARMFORGE_SCRIPT=<absolute path to swarm.py>
```

When an agent runs inside a worktree, its current directory may be `PROJECT/.worktrees/<workflow>/<name>`, not the main checkout. To target the original project state, use `$SWARMFORGE_PROJECT_DIR`. To communicate without guessing paths, use `$SWARMPY`:

```bash
$SWARMPY log coder "Started implementation" -w "$SWARMPY_WORKFLOW"
$SWARMPY notify reviewer "Ready for review" -w "$SWARMPY_WORKFLOW"
```

If `-p` is omitted, SwarmPy resolves the project from `$SWARMFORGE_PROJECT_DIR` or the current directory. In ambiguous scripts, pass `-p "$SWARMFORGE_PROJECT_DIR"` explicitly.

## Worktree guidance

Use separate worktrees when multiple roles may edit code concurrently. Example:

```conf
window coder codex coder
window reviewer codex reviewer
```

This avoids agents trampling each other’s checkout state.

Use `master` when a role should operate in the main checkout, often the architect:

```conf
window architect claude master
```

Use `none` for a passive/manual role that should not get a backend or dedicated worktree:

```conf
window logger none none
```

Use `--worktree <name>` for a single shared branch/run, such as a nightly run or one coordinated feature branch.

Do not manually delete `.worktrees/<workflow>/<name>` while a workflow is running. If a worktree must be removed, first `swarmpy cleanup`, then use normal `git worktree` commands from the main project.

## Troubleshooting

### `Config not found`

The workflow was not initialized, the wrong `PROJECT` was passed, or the wrong `WORKFLOW` was selected.

```bash
swarmpy workflows -p "$PROJECT"
swarmpy init "$PROJECT" -w "$WORKFLOW"
```

### `Missing role prompt`

A non-`none` role in `swarmforge.conf` does not have a matching `<role>.prompt` file. Create it in the same workflow directory.

### `Sessions file not found`

The workflow has not been launched yet, or runtime state was removed.

```bash
swarmpy launch "$PROJECT" -w "$WORKFLOW"
```

### `Unsupported agent`

Only `claude`, `codex`, and `none` are currently valid in `swarmforge.conf`.

### Backend not installed

If a configured role uses `claude` or `codex`, that executable must be on `PATH` before launch. Change the role to `none` for a manual window or install the backend.

### Tmux session stale or wrong

Inspect sessions:

```bash
tmux ls
swarmpy sessions -p "$PROJECT" -w "$WORKFLOW"
```

Then clean up and relaunch:

```bash
swarmpy cleanup -p "$PROJECT" -w "$WORKFLOW"
swarmpy launch "$PROJECT" -w "$WORKFLOW"
```

## Safe behavior rules for agents using this skill

- Always distinguish the SwarmPy tool repository from the user’s target `PROJECT`.
- Prefer absolute paths in setup, launch, attach, log, and notify commands.
- Read existing workflow files before editing them.
- Never run `swarmpy init --force` without explicit approval.
- Do not edit generated files under `.swarmforge/<workflow>/prompts/`; edit source prompts under `swarmforge/`.
- Do not delete `.worktrees/`, `logs/`, or `agent_context/` unless the user explicitly asks.
- Use `agent_context/<workflow>/` for durable artifacts agents should share.
- Use `swarmpy log` for status updates and `swarmpy notify` for direct instructions to another role.
- Before telling the user a workflow is ready, run `swarmpy sessions -p "$PROJECT" -w "$WORKFLOW"` and inspect logs if launch output looks suspicious.

## Response pattern to the user

When setting up or changing a workflow, report:

1. project path and workflow name
2. files created or edited under `swarmforge/`
3. roles/backends/worktree mapping
4. launch command
5. attach/log/notify commands for day-to-day operation
6. any dependency or secret-handling warnings
