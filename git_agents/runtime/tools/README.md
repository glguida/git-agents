<!-- SPDX-License-Identifier: MIT -->

# GitAgents Tools

This directory contains local helper tools for an installed GitAgents directory.

The shell launchers require `sh` and whichever agent CLI is selected (`pi`,
`codex`, or `claude`). `tools/git_agents` and `tools/agent` use Python 3 stdlib
only.

## `git_agents`

`git_agents` is the top-level way to run GitAgents. It starts the built-in `console`
assistant, the configured team, and the local web interface for the installed
GitAgents directory. It serves the installed root by default, so from the target
project root:

```sh
git_agents/tools/git_agents
```

Then open the printed local URL.
By default, GitAgents starts at `http://127.0.0.1:4137` and increases the port
until it finds a free one.

Options:

- `--root <path>`: serve a different GitAgents root.
- `--host <host>`: bind host. Defaults to `127.0.0.1`.
- `--port <port>`: starting port to bind. GitAgents tries this port and then
  increasing ports until one is free. Defaults to `4137`.
- `--verbose`: print agent transcript output in this terminal.
- `--no-team`: serve the web interface without starting agents.
- `--no-console`: do not start the built-in console assistant.
- `--console-model <model>`: pass a model to the built-in console assistant.
- `[team-file]`: team file to run. Defaults to `git_agents/default.team`.

## `run_git_agents`

`run_git_agents` starts a named team from a team file and restarts each agent as
it exits. By default it runs agents headless. Use `--verbose` to print each
agent's rendered transcript output to the terminal, prefixed by agent name.

```sh
git_agents/tools/run_git_agents --verbose
git_agents/tools/run_git_agents
```

Team file format:

```text
# <name> <role> <agent> [model]
planner-1 planner pi
implementer-1 implementer codex
reviewer-1 reviewer claude sonnet
```

Use `pi-interactive` for a Pi agent that keeps the normal GitAgents role and job
protocol while accepting live messages from the web interface:

```text
planner-1 planner pi-interactive
```

The built-in `console` assistant is different: `git_agents/tools/git_agents` starts it
automatically as agent `console` with role `console`. It is not listed in the
team file and has no queued job.

## `agent`

`agent` starts one named agent, claims one pending job for that agent's role,
records the job in `agents/<agent-name>/current-job`, and renders CLI event
output to `agents/<agent-name>/transcript.log`.
By default it also prints the rendered transcript to stdout. Use `--headless`
to write files only.

From the target project root:

```sh
# Start a Pi planner agent.
git_agents/tools/agent --pi planner planner-1

# Start a named Codex implementer agent.
git_agents/tools/agent --codex implementer implementer-1

# Start a Claude reviewer agent with a specific model.
git_agents/tools/agent --claude -m sonnet reviewer reviewer-1
```

Options:

- `--pi`: use Pi. This is the default.
- `--codex`: use Codex CLI.
- `--claude`: use Claude Code.
- `--headless`: do not print the rendered transcript to stdout.
- `-m <model>`: pass a model name to the selected CLI.

CLI stderr is saved in `error.log`.

Codex agents run from the target repository root with `workspace-write` by
default. The launcher passes both the repository root and GitAgents runtime root
as writable directories. Override `GIT_AGENTS_CODEX_SANDBOX` only when testing a
different Codex sandbox mode.

The agent name is mandatory. `agent` calls `bin/agent-new`, `bin/job-wait`, and
`bin/job-claim`; the agent itself starts and completes the job according to
`AGENTS.md`. The rendered transcript is stored only in
`agents/<agent-name>/transcript.log`; the job log points to that file.

## `agent-pi-interactive`

`agent-pi-interactive` is launched by `run_git_agents` for team entries that use
`pi-interactive`, and by `git_agents` itself for the built-in console assistant.
It starts `pi --mode rpc`, writes the rendered transcript to
`agents/<agent-name>/transcript.log`, and listens for web input on the agent's
local `input.fifo`.

Humans normally talk to the built-in console from the `Chat` tab in
`git_agents/tools/git_agents`. Return sends the message; Shift+Return inserts a
newline; `Stop` sends an interrupting steer message. Agent inspectors still
provide the lower-level transcript view with explicit `Send` and `Steer`
controls.

## Task Commands

Task commands operate on local folders under `git_agents/tasks/`:

```sh
git_agents/bin/task-create <task-id> <spec-file>
git_agents/bin/task-show <task-id>
git_agents/bin/task-comment <task-id> <message>
git_agents/bin/task-state <task-id> open
git_agents/bin/task-state <task-id> done -m "completed"
git_agents/bin/task-result <task-id> <result-file>
git_agents/bin/task-list
```

## `bin/agent-new`

`bin/agent-new <agent-id> <role>` creates a named agent directory when needed
and prints its path. If the agent already has a claimed or running job, it exits
with an error instead.

## Job Recovery Commands

The normal job lifecycle is managed by agents through `job-claim`, `job-start`,
`job-done`, `job-release`, and `job-fail`. Operator recovery tools are also
available:

```sh
git_agents/bin/job-reset <job-id> -m "retry"
git_agents/bin/job-kill <job-id> -m "stop now"
git_agents/bin/job-orphans
git_agents/bin/job-reset-orphans
git_agents/bin/job-reap 60
```

`job-reset` requeues a job by clearing its owner and lock. `job-kill` marks a
claimed or running job failed and signals the recorded runner or engine PIDs.
