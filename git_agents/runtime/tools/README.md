<!-- SPDX-License-Identifier: MIT -->

# GitAgents Tools

This directory contains runtime helper tools and the packaged dashboard server.
Only the agent/runtime helpers are copied into an installed `.git-agents`
directory; the dashboard server is launched through the globally installed
`gitagents-dashboard` command.

The helper launchers require `pi`. GitAgents is a Pi-based agentic system;
`agent`, `agent-pi-interactive`, `git-agents-ui`, and the dashboard entry point
use Python 3 stdlib only.

## `git-agents-ui`

`git-agents-ui` serves the web interface for GitAgents state. It is a packaged
server implementation used by the separate global dashboard utility:

```sh
gitagents-dashboard
```

It is not copied into installed repository `.git-agents/tools/` directories.

By default, GitAgents starts at `http://127.0.0.1:4137` and increases the port
until it finds a free one.

Options:

- `--root <path>`: serve a different GitAgents state directory.
- `--registry`: read running GitAgents instances from links in
  `~/.gitagents/instances/`.
- `--registry-dir <path>`: read a different user instances directory.
- `--host <host>`: bind host. Defaults to `127.0.0.1`.
- `--port <port>`: starting port to bind. GitAgents tries this port and then
  increasing ports until one is free. Defaults to `4137`.
- `--verbose`: print console transcript output in this terminal.
- `--no-console`: do not start the built-in console agent.
- `--console-model <model>`: pass a model to the built-in console agent.

The configured queued team is started by `git agents start`, not by the web UI.
`git agents start` reads the effective `team.toml` and supervises each
configured agent directly. It also links each running repository's
`.git-agents` directory under `~/.gitagents/instances/` for the dashboard.

## `heartbeat`

`heartbeat` is launched by `git agents start` when the console is enabled. It
sends `heartbeat <time> <date>` to `.git-agents/state/agents/console/input.fifo`
when it starts and then every 15 minutes by default.

It uses the shared console input helper used by `console-input`, the same FIFO
protocol used by `git agents prompt`.

Users normally configure it through the supervisor:

```sh
git agents start --heartbeat 5
git agents start --no-heartbeat
```

## `console-input` and `console-notifier`

`console-input` sends one message to the running console agent using the same
JSON FIFO protocol as `git agents prompt`.

`console-notifier` is launched by `git agents start` when the console is
enabled. It watches `.git-agents/state/jobs/` and forwards pending jobs whose
`role` file is `console` through the shared console input helper used by
`console-input`. If the console is not listening yet, the job remains pending
and is retried.

Agents and tools create console notification jobs with the normal job helper:

```sh
.git-agents/bin/job-create notify-console-1 -r console -t <task-id> spec.md
```

## `agent`

`agent` starts one named agent, claims one pending job for that agent's role,
records the job in `agents/<agent-name>/current-job`, and renders CLI event
output to `agents/<agent-name>/transcript.log`.
By default it also prints the rendered transcript to stdout. Use `--headless`
to write files only.

From the target project root:

```sh
# Start a Pi planner agent.
.git-agents/tools/agent --pi planner planner-1

```

Options:

- `--pi`: use Pi, the only supported backend for packaged teams.
- `--headless`: do not print the rendered transcript to stdout.
- `-m <model>`: pass a model name to the selected CLI.

CLI stderr is saved in `error.log`.

For research-heavy interactive use, configure Pi with packages such as
`pi-web-access` in the Pi configuration used by the interactive console. That
package adds web search, URL fetching, code/docs search, GitHub cloning, PDF
extraction, and video extraction. Keep queued-agent Pi configurations without
web-search packages if only the interactive console should have web access.

The agent name is mandatory. `agent` calls `bin/agent-new`, `bin/job-wait`, and
`bin/job-claim`; the agent itself starts and completes the job according to
`AGENTS.md`. The rendered transcript is stored only in
`.git-agents/state/agents/<agent-name>/transcript.log`; the job log points to
that file.

## `agent-pi-interactive`

`agent-pi-interactive` is launched by `git agents start` for team entries that
use one of the interactive agent engines, and for the built-in console agent.
It writes the rendered transcript to
`.git-agents/state/agents/<agent-name>/transcript.log` and listens for web input
on the agent's local `input.fifo`.

It uses `pi --mode rpc` for a persistent live session.

Humans normally talk to the built-in console from `git agents prompt` or from
the web UI's `Chat` tab. Return sends the message; Shift+Return inserts a
newline; `Stop` sends an interrupting steer message. Agent inspectors still
provide the lower-level transcript view with explicit `Send` and `Steer`
controls.

## Task Commands

Task commands live under `.git-agents/bin` and operate on local folders under
`.git-agents/state/tasks/`:

```sh
.git-agents/bin/task-create <task-id> <spec-file>
.git-agents/bin/task-show <task-id>
.git-agents/bin/task-comment <task-id> <message>
.git-agents/bin/task-state <task-id> open
.git-agents/bin/task-state <task-id> done -m "completed"
.git-agents/bin/task-result <task-id> <result-file>
.git-agents/bin/task-list
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
.git-agents/bin/job-reset <job-id> -m "retry"
.git-agents/bin/job-kill <job-id> -m "stop now"
.git-agents/bin/job-orphans
.git-agents/bin/job-reset-orphans
.git-agents/bin/job-reap 60
```

`job-reset` requeues a job by clearing its owner and lock. `job-kill` marks a
claimed or running job failed and signals the recorded runner or engine PIDs.
