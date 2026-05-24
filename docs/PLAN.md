# git-agents Plan

## Goal

Build a pip-installable Git extension that runs coding-agent workflows from
inside any Git repository:

```sh
git agents install
git agents start
git agents stop
gitagents-dashboard
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

GitAgents installs a stationary repository-local system under `.git-agents/`.
Only `.git-agents/state/` is local execution state and ignored.

## Repository Layout

The stationary side can be committed:

```text
.git-agents/
  AGENTS.md
  bin/
  tools/
  roles/
  team.toml
  specs/
```

Runtime state should live under the ignored state directory:

```text
.git-agents/state/
  tasks/
  jobs/
  agents/
  runs/
  logs/
  config.json
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
git agents log [-f] [agent]
git agents prompt [--quiet] [message]
git agents rules show
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
- `rules` commands inspect the GitAgents-owned generic agent protocol installed
  by `init` and refreshed by `update`.
- `role` commands manage repo-local role definitions copied from package
  templates when customization is requested.
- `team` commands manage the repo-local set of named agents.
- `gitagents-dashboard` starts the global web UI in the foreground. It is a
  separate utility, not a `git agents` subcommand.
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

The generic GitAgents protocol is installed into the repository as:

```text
.git-agents/
  AGENTS.md
```

The protocol file defines system behavior shared by all roles. It is
GitAgents-owned, not repository policy. Repository rules belong in normal
project documentation and repo-local roles.

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
git agents team add <agent> --role <role> [--engine pi] [--model <model>]
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
- copy the generic agent protocol to `.git-agents/AGENTS.md` if absent
- copy runtime command helpers to `.git-agents/bin` and `.git-agents/tools`
- copy packaged roles to `.git-agents/roles` if absent
- copy default team config to `.git-agents/team.toml` if absent
- write default runtime config if absent
- optionally create the specs directory when the user passes a tracked-config
  option
- validate required agent executables

### `git agents update`

Refresh package-managed runtime pieces that must match each other:

- runtime queue/helper commands under `.git-agents/bin`
- runtime launcher/UI helpers under `.git-agents/tools`
- the generic agent protocol at `.git-agents/AGENTS.md`

Do not refresh repo-local roles by default. Roles are default templates and may
contain repository policy. `git agents update --roles` explicitly refreshes the
packaged role templates under `.git-agents/roles/`.

### `git agents start`

Start the configured team:

- launch the supervisor as the owner of agent processes
- write pid/status files under runtime state
- start or connect to the console agent by default
- start a console job forwarder when the console is enabled
- start a console heartbeat by default; the heartbeat sends
  `heartbeat <time> <date>` immediately and then every 15 minutes
- support `--heartbeat <minutes>` and `--no-heartbeat`
- support `--no-console` for batch/headless use
- return nonzero if agents are already running unless `--restart` is supplied

GitAgents is a Pi-based agentic system. Queued planner, implementer, reviewer,
and committer jobs run through Pi; no other agent runtime is supported. The
agent harness is extended through Pi settings, packages, skills, and model
providers.

Research-oriented web access should be configured in Pi, not in the GitAgents
task protocol. For example, the `pi-web-access` package can add web search,
URL fetching, code/docs search, GitHub cloning, PDF extraction, and video
extraction. If only the interactive console should have web access, use a Pi
configuration for that console with web-search packages enabled and keep
queued-agent Pi configurations without those packages.

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
- per-repository supervisor status

### `git agents tasks create <task> <spec-file>`

Create a task and its initial planner job using the package-managed queue tools
under `.git-agents/bin`.

Humans should prefer this porcelain command over invoking tools under
`.git-agents/bin` directly.

### `gitagents-dashboard`

Start the global web UI in the foreground:

- read linked running repositories from `~/.gitagents/instances/`
- treat each entry as a link to a real `.git-agents` directory
- serve bundled package assets
- switch between linked GitAgents state roots
- never start, stop, or supervise agent processes
- exit when interrupted

There should not be a `--with-agents`, `--with-team`, or equivalent flag. Agent
process supervision belongs to `git agents start`. The dashboard is visibility
over linked running systems, not the owner of those systems.

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
