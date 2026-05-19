# git-agents Plan

## Goal

Build a pip-installable Git extension that runs coding-agent workflows from
inside any Git repository:

```sh
git agents install
git agents start
git agents stop
git agents serve
git agents log -f
git agents prompt "what should I do next?"
```

The tool should make agents feel like a natural part of the Git workflow while
keeping runtime state out of the tracked worktree.

## Git Extension Model

Git supports external subcommands by looking for an executable named
`git-<command>` on `PATH`. For this project:

```sh
git agents start
```

invokes:

```sh
git-agents start
```

Arguments after `agents` are passed through to `git-agents` as normal command
arguments. There is no richer extension protocol that passes the repo root or
structured context.

Official references:

- `git(1)` documents custom subcommands in the `PATH` environment variable
  section: https://git-scm.com/docs/git
- `git rev-parse` documents repository path discovery helpers:
  https://git-scm.com/docs/git-rev-parse

## Repository Discovery

`git-agents` should discover repository context with Git plumbing:

```sh
git rev-parse --show-toplevel
git rev-parse --show-prefix
git rev-parse --absolute-git-dir
```

Runtime state lives in the worktree under `.git-agents/state/` so Codex
workspace sandboxing can access it without granting access to all Git-private
paths. The state directory is added to `.gitignore` during init/install.

## State Layout

Runtime state should live under the repo-local GitAgents directory:

```text
.git-agents/state/
  tasks/
  jobs/
  agents/
  runs/
  logs/
  config.json
```

Tracked project configuration, when explicitly requested, should be small and
human-editable:

```text
.git-agents/
  state/      # ignored runtime state
  roles/
  team.toml
  specs/
```

Default init/install may create or update `.gitignore` so `.git-agents/state/`
does not dirty `git status`.

## Command Shape

Preferred command tree:

```sh
git agents init
git agents install
git agents start
git agents stop
git agents restart
git agents status
git agents serve
git agents log [-f] [agent]
git agents prompt [--quiet] [message]
git agents rules show
git agents rules edit
git agents role list
git agents role add <name> [--from <template>]
git agents role edit <name>
git agents role show <name>
git agents team list
git agents team add <agent> --role <role> [--engine <engine>] [--model <model>]
git agents team remove <agent>
git agents team edit
git agents tasks create <task> <spec-file>
git agents tasks list
git agents tasks show <task>
git agents tasks comment <task> <message>
git agents tasks state <task> <open|done> [-m <message>]
git agents tasks result <task> <result-file>
git agents jobs create <job> --role <role> --task <task> <spec-file>
git agents jobs list
git agents jobs reset <job> [-m <message>] [--force]
git agents jobs kill <job> [-m <message>] [--force]
git agents jobs orphans
git agents jobs reset-orphans
git agents jobs reap [minutes]
git agents agents list
git agents agents reset <agent> [-m <message>] [--force] [--no-kill]
git agents spec build
```

Notes:

- `init` is the Git-native name for repo-local setup.
- `install` can be kept as an alias for `init`, because it is intuitive for
  installing agents into the current repository.
- Prefer grouped nouns like `tasks list` over long names like `list-tasks`; the
  command surface will scale better.
- `prompt` should accept both command-line arguments and stdin.
- `prompt` should print the console transcript for that turn by default; use
  `--quiet` to send only and leave the response in the log.
- `rules` commands manage the generic agent protocol copied from package
  templates when customization is requested.
- `role` commands manage repo-local role definitions copied from package
  templates when customization is requested.
- `team` commands manage the repo-local set of named agents.
- `serve` starts only the local web UI and runs in the foreground.
- `spec build` is the first planned higher-level workflow command for spec
  builder integration.

## Role Model

Roles should start from package-provided templates. Repo-local role files should
be created only when the user customizes roles or explicitly asks for tracked
configuration.

When materialized, role files live here:

```text
.git-agents/
  roles/
    planner.md
    implementer.md
    reviewer.md
    committer.md
    console.md
```

After a role is materialized, agents should read the repo-local role file for
that role. Package updates may add or improve templates, but should not
overwrite modified repo-local roles without an explicit command.

Generic agent rules live in the package by default and can be materialized as:

```text
.git-agents/
  AGENTS.md
```

The rules file defines behavior shared by all roles. Role files define only
role-specific responsibilities.

Possible role commands:

```sh
git agents role list
git agents role show <name>
git agents role add <name>
git agents role add <name> --from reviewer
git agents role edit <name>
git agents role diff [name]
git agents role reset <name>
```

Suggested semantics:

- `role list` shows effective roles and whether each one is package-provided or
  repo-local.
- `role show <name>` prints the effective role text.
- `role add <name>` creates a new repo-local role from a blank or minimal
  template.
- `role add <name> --from <template>` copies an existing packaged or local role
  as a starting point.
- `role edit <name>` materializes the role if needed, then opens `$EDITOR`.
- `role diff [name]` compares local roles against their packaged template
  source when known.
- `role reset <name>` restores a role from the packaged template, ideally with
  confirmation or a backup.

This keeps first setup clean while preserving local control over agent
behavior.

## Team Model

The team is the repo-local set of named agents that `git agents start` launches.
It should be editable without requiring users to hand-edit config.

By default, `git-agents` should use packaged team defaults. When customized,
team config lives next to roles:

```text
.git-agents/
  team.toml
```

Possible team commands:

```sh
git agents team list
git agents team show [agent]
git agents team add <agent> --role <role> [--engine pi|codex|claude] [--model <model>]
git agents team remove <agent>
git agents team set <agent> --role <role>
git agents team set <agent> --engine <engine>
git agents team set <agent> --model <model>
git agents team edit
```

Suggested semantics:

- `team list` shows configured agents, roles, engines, models, and whether they
  are currently running.
- `team show [agent]` shows either the whole team config or one agent.
- `team add` materializes `.git-agents/team.toml` if needed and adds a named agent
  using an existing role.
- `team remove` removes an agent from future starts; it should not kill a
  running process unless explicitly requested.
- `team set` updates one field on an existing agent.
- `team edit` materializes the team config if needed, then opens `$EDITOR`.

`start` should read the effective team config and launch those agents. `status`
should combine team config with runtime state so users can see expected agents
versus currently running agents.

## Command Semantics

### `git agents init` / `git agents install`

Initialize repo-local runtime state:

- create the runtime state directory under `.git-agents/state`
- add `/.git-agents/state/` to `.gitignore`
- write default runtime config if absent
- optionally materialize `.git-agents/` when the user passes a tracked-config option
- validate required agent executables

### `git agents start`

Start the configured team:

- launch the supervisor as the owner of agent processes
- write pid/status files under runtime state
- start or connect to the console agent by default
- support `--no-console` for batch/headless use
- return nonzero if agents are already running unless `--restart` is supplied

Codex job agents run from the target repository root with `workspace-write` by
default. The launcher passes both the repository root and GitAgents runtime root
as writable directories.

### `git agents stop`

Stop running agents cleanly:

- signal the managed process group
- release claimed jobs where possible
- leave transcripts and logs intact

### `git agents status`

Show a compact overview:

- whether the supervisor is running
- active agents
- current jobs
- failed jobs
- web server URL if `serve` is running

### `git agents tasks create <task> <spec-file>`

Create a task and its initial planner job using the package-managed runtime
queue tools under `.git-agents/state`.

Humans should prefer this porcelain command over invoking runtime tools under
`.git-agents/state/bin` directly.

### `git agents serve`

Start the web UI in the foreground:

- serve bundled package assets
- read runtime state from `.git-agents/state`
- never start, stop, or supervise agent processes
- exit when interrupted

There should not be a `--with-agents`, `--with-team`, or equivalent flag. Agent
process supervision belongs to `git agents start`.

The viewer/server can also become a separate Git extension later. The core
extension should keep the queue, supervisor, and filesystem state model usable
without requiring the UI.

### Recovery commands

Jobs and agents need explicit recovery paths because users can interrupt tools,
kill processes, or lose agents unexpectedly:

- `jobs reset <job>` moves a non-completed job back to `pending`, clears its
  owner, removes the lock, and records the reset in the job log. `--force`
  allows resetting completed jobs or non-empty lock directories.
- `jobs kill <job>` marks a claimed or running job `failed`, clears the active
  lock, clears the owning agent's current job, and signals recorded runner or
  engine PIDs.
- `agents reset <agent>` resets active jobs owned by that agent back to
  `pending`, clears volatile runtime files, and signals recorded processes
  unless `--no-kill` is supplied.
- orphan and stale-lock helpers remain available through porcelain commands so
  operators do not need to edit `.git-agents/state` by hand.

### `git agents log [-f] [agent]`

Show transcripts:

- default to the console transcript
- support `-f` for follow mode
- support named agents

### `git agents prompt [--quiet] [message]`

Send input to the console agent:

```sh
git agents prompt "summarize current status"
echo "what should I test next?" | git agents prompt
git agents prompt --quiet "summarize current status"
```

If the console is disabled or not running, fail clearly.

### `git agents spec build`

Planned workflow for integrating spec builder techniques:

- inspect current repository/task context
- draft or update a task specification
- create tasks/jobs from the generated spec
- keep the spec reviewable before agents execute large changes

## Persistence

Canonical state should be filesystem-first:

```text
.git-agents/state/
  tasks/<task-id>/spec.md
  tasks/<task-id>/state
  tasks/<task-id>/log.md
  jobs/<job-id>/status
  jobs/<job-id>/agent-id
  agents/<agent>/transcript.log
```

This is the more Git-like model: state is inspectable with ordinary tools,
recoverable after partial failure, and easy for humans and agents to debug.

SQLite can be added later only as a rebuildable index/cache for the web UI or
search. It should not be the only source of truth.

## Specs

Runtime task specs should be stored as filesystem state under the Git directory.
When specs need review, they can also be tracked explicitly:

```text
.git-agents/specs/<task-id>.md
```

Dispatching a reviewed spec should copy a snapshot into runtime state:

```text
.git-agents/state/tasks/<task-id>/spec.md
```

That gives agents stable runtime input while keeping human-reviewed specs
available when a project wants them.

## Packaging

Use a single name throughout:

- Python package name: `git-agents`
- installed console script: `git-agents`
- user command: `git agents`

The package should bundle web UI assets, role templates, and default
configuration. Repositories should not need copied static assets.

## Implementation Notes

- Use Python for the CLI and process supervision.
- Use `argparse` or `click`; prefer zero-heavy dependencies initially.
- Avoid writing runtime state into the worktree by default.
- Treat Git worktrees as first-class by using `git rev-parse --git-path`.
- Keep server assets package-managed so upgrades are simple.
- Make commands safe to run from subdirectories.
- Use non-interactive process management so commands work in scripts.
