# Layer 1: GitAgents System Contract

Layer 1 is the GitAgents-owned system layer. It is the part that lets a
repository host an agent system without each repository inventing its own task
queue, process launcher, console input path, or recovery commands.

Layer 1 answers:

> How does the agent system coordinate?

It does not answer:

> What should this repository's agents know, believe, or specialize in?

Repository-specific policy belongs in repository docs, repo-local roles, team
configuration, and skills. The packaged defaults are starter templates for
those higher layers, not the definition of the whole system.

## Installed Files

`git agents init` installs a stationary GitAgents side under `.git-agents/`.
This side can be committed:

```text
.git-agents/AGENTS.md
.git-agents/bin/
.git-agents/tools/
.git-agents/roles/
.git-agents/team.toml
```

`git agents init` also creates local execution state under:

```text
.git-agents/state/
```

Only `.git-agents/state/` is ignored. The installed command helpers and
GitAgents protocol are outside state so they can be reviewed with the
repository.

## Ownership

GitAgents owns these Layer 1 files:

```text
.git-agents/AGENTS.md
.git-agents/bin/
.git-agents/tools/
```

They are copied by `git agents init` and refreshed by `git agents update`.
The protocol file and command helpers are versioned together: the protocol tells
agents how to use the helpers, and the helpers implement the protocol.

Do not put repository policy in `.git-agents/AGENTS.md`. Put project rules in
normal repository documentation and put role responsibilities in
`.git-agents/roles/`.

## Default Templates

The files installed into `.git-agents/roles/` and `.git-agents/team.toml` are
default templates. They make a new repository useful immediately, but they are
not the Layer 1 contract.

Repositories may edit role files and team configuration to fit their own work
model. Those edits live above Layer 1.

`.git-agents/AGENTS.md` is different: it is GitAgents system protocol. Treat it
as package-managed. Refresh it with `git agents update`.

`git agents update` does not rewrite repo-local roles by default. If you want to
replace default role templates with the packaged versions from the installed
GitAgents package, run:

```sh
git agents update --roles
```

## State Layout

Layer 1 state is filesystem-backed:

```text
.git-agents/state/tasks/
.git-agents/state/jobs/
.git-agents/state/agents/
.git-agents/state/runs/
.git-agents/state/logs/
.git-agents/state/config.json
.git-agents/state/repo-root
```

The important directories are:

- `tasks/`: task specs, task logs, task state, and task results.
- `jobs/`: per-job specs, roles, status files, locks, logs, and ownership.
- `agents/`: per-agent transcripts, prompts, pid files, and live input FIFOs.
- `runs/`: supervisor pid and status files.
- `logs/`: supervisor and managed-process logs.

Use GitAgents commands and helpers to mutate this state. Inspecting the files
directly is fine for debugging.

## Lifecycle Commands

Initialize a repository:

```sh
git agents init
git add .gitignore .git-agents
git commit -m "Initialize git-agents"
```

Refresh package-managed Layer 1 files after installing a newer GitAgents
package:

```sh
git agents update
```

If the supervisor is already running, restart it so newly installed tools are
started:

```sh
git agents restart
```

Equivalent manual form:

```sh
git agents stop
git agents start
```

Start options are not persisted. If you normally pass `--console-model`,
`--heartbeat`, `--no-heartbeat`, or `--no-console`, pass them again on
`restart` or `start`.

## User Instances Directory

`git agents start` links the running repository in:

```text
~/.gitagents/instances/
```

Each entry is a link to the repository's `.git-agents` directory. The dashboard
derives the repository root from `.git-agents/state/repo-root`, the state root
from `.git-agents/state/`, and the running supervisor pid from
`.git-agents/state/runs/supervisor.pid`.

`git agents stop` removes the link. If a process exits uncleanly, the dashboard
can still inspect the linked `.git-agents` directory and treats the instance as
stale when the recorded supervisor pid is no longer running.

The instances directory is per-user machine state. It is not committed and it
is not part of any repository's project policy. It is an index of real
`.git-agents` directories, not a second state store.

Use the separate dashboard utility to inspect all linked running systems:

```sh
gitagents-dashboard
```

The dashboard command is installed globally by the Python package. It is not a
repo-local helper under `.git-agents/tools/`.

## Supervisor

`git agents start` starts one supervisor process. The supervisor owns the
managed runtime processes:

- the built-in interactive console, unless `--no-console` is set
- `console-notifier`, which forwards pending role=`console` jobs when the
  console is enabled
- `heartbeat`, when the console is enabled and heartbeat is not disabled
- the configured queued team agents from `.git-agents/team.toml`

`git agents stop` stops the supervisor and its managed children.

## Console Input

The configurable console behavior lives in `.git-agents/roles/console.md`.
The runtime file `.git-agents/state/agents/console/prompt.md` is generated
launch context: identity, paths, and pointers to `.git-agents/AGENTS.md` and
`.git-agents/roles/console.md`.

The console has one live input path:

```text
.git-agents/state/agents/console/input.fifo
```

`git agents prompt` writes one JSON message to that FIFO and, unless
`--quiet` is used, follows the console transcript for the response:

```sh
git agents prompt "summarize current status"
git agents prompt --quiet "record this in the console log"
```

Runtime tools use the same input path through:

```sh
.git-agents/tools/console-input "message"
```

This is live input, not a durable task or job. If the console is not running or
not listening, direct console input fails.

## Heartbeat

When the console is enabled, `git agents start` starts a heartbeat by default.
It sends one heartbeat as soon as the helper starts, then sends another every
15 minutes by default. The message is shaped like:

```text
heartbeat 14:23:00Z 2026-05-24
```

The default console role treats this as a liveness ping. If there is no active
user-relevant context to recover or report, the console should ignore it
silently.

Configure the interval in minutes:

```sh
git agents start --heartbeat 5
git agents restart --heartbeat 5
```

Disable heartbeat:

```sh
git agents start --no-heartbeat
git agents restart --no-heartbeat
```

`--no-console` also disables heartbeat, because there is no console to receive
it.

## Console Jobs

Console jobs are normal jobs whose role is `console`. They are durable requests
to send a message to the interactive console when it is available.

Create one with the normal job command:

```sh
.git-agents/bin/job-create notify-console-1 -r console -t <task-id> spec.md
```

The porcelain equivalent is:

```sh
git agents jobs create notify-console-1 --role console --task <task-id> spec.md
```

The job is stored under:

```text
.git-agents/state/jobs/notify-console-1/
```

`console-notifier`, started by `git agents start`, scans pending jobs. If a
job's `role` file is `console`, it claims the job, forwards the job spec
through the same console input path used by `git agents prompt`, and marks the
job `done`.

If the console is not ready, the job remains `pending` and is retried. If the
job spec is empty, the job is marked `failed`.

Console jobs are for human-visible console attention. They are still jobs, so
they must belong to a task and should have a meaningful spec. They are not a
replacement for task comments, job logs, planner notification jobs, or task
results. Durable task history should still be recorded on the task or job.

## Layer 1 Helpers

Layer 1 exposes command helpers under `.git-agents/bin/`. Agents normally use
these helpers rather than editing state files by hand:

```sh
.git-agents/bin/task-create <task-id> <spec-file>
.git-agents/bin/task-show <task-id>
.git-agents/bin/task-comment <task-id> <message>
.git-agents/bin/task-state <task-id> open
.git-agents/bin/task-state <task-id> done -m "completed"
.git-agents/bin/task-result <task-id> <result-file>
.git-agents/bin/task-list
.git-agents/bin/job-create <job-id> -r <role> -t <task-id> <spec-file>
.git-agents/bin/job-claim [job-id] [-r <role>] --agent-id <agent-id>
.git-agents/bin/job-start <job-id> --agent-id <agent-id>
.git-agents/bin/job-done <job-id> --agent-id <agent-id> -m <message>
.git-agents/bin/job-release <job-id> --agent-id <agent-id> -m <message>
.git-agents/bin/job-fail <job-id> --agent-id <agent-id> -m <message>
.git-agents/bin/job-list [status]
.git-agents/bin/job-mine --agent-id <agent-id>
.git-agents/bin/job-wait [-r <role>]
.git-agents/bin/job-watch <status>
.git-agents/bin/job-reset <job-id> -m <message> [--force]
.git-agents/bin/job-kill <job-id> -m <message> [--force]
.git-agents/bin/job-orphans
.git-agents/bin/job-reset-orphans
.git-agents/bin/job-reap [minutes]
```

The `git agents` porcelain commands wrap the common human operations. The
helpers are the agent-facing Layer 1 interface.
