# git-agents

`git-agents` is a Git extension for running repository-local coding-agent
workflows with versionable, project-specific roles.

It gives each repository a customizable agent team. The packaged planner,
implementer, reviewer, committer, and console roles work out of the box, while
tracked repo-local role files let a project adapt those agents to its own
architecture, test commands, review standards, release process, and risk policy.

The user-facing command is:

```sh
git agents <command>
```

Git resolves that to an executable named `git-agents` on `PATH`.

## Prerequisites

- Git and Python 3.10 or newer.
- A POSIX `sh` for the runtime helper scripts.
- `pi` for the queued agents and the built-in interactive console.

## Local Install

From this repository:

```sh
python3 -m pip install -e .
```

Then, from any Git repository:

```sh
git agents init
git agents status
git agents tasks create my-task spec.md
git agents start
git agents prompt "summarize current status"
git agents prompt --quiet "leave the response in the log"
git agents log -f
git agents rules show
git agents role list
git agents team list
git agents agents list
git agents jobs kill my-task-plan -m "stop now"
git agents agents reset planner-1
git agents serve
```

GitAgents can initialize an empty Git repository, but agent work expects the
repository to have at least one commit. For a new project, initialize GitAgents
and commit the `.gitignore` changes before starting agents:

```sh
git init
git agents init
git add .gitignore
git commit -m "Initialize git-agents"
git agents start
git agents prompt "Add a task to write a simple hello world in C"
```

## State Model

Runtime state lives under the repo-local GitAgents directory:

```text
.git-agents/state/
```

`git agents init` adds this state path to `.gitignore`. Tracked configuration is
opt-in and lives alongside it under:

```text
.git-agents/
```

Use this when you want repo-local editable rules, roles, or team config:

```sh
git agents init --tracked-config
```

## Pi-Based Agents

GitAgents is a Pi-based agentic system. Pi is the only supported agent runtime
for the packaged planner, implementer, reviewer, committer, and console agents.

For stronger interactive research and solution-finding, configure Pi rather
than changing the queued team backend. The Pi package `pi-web-access` adds web
search, URL fetching, code/docs search, GitHub cloning, PDF extraction, and
video extraction:

```sh
pi install npm:pi-web-access
```

Whether web search is available is a Pi configuration choice. If you want only
the interactive console to search the web, configure web-access only for the Pi
configuration used by that console, and keep queued coding-agent Pi
configurations without web-search packages or keys. GitAgents does not grant
web search as part of the task protocol, and it does not provide a separate
web-tool permission layer outside the tools exposed by Pi.

## Current Scope

Implemented now:

- packageable `git-agents` console script
- Git repository discovery with normal Git plumbing
- clean `init` / `install`
- foreground web UI with `serve`
- generic rules and role templates copied from the local agent template source
- role, rules, team, task, job, status, log, and prompt command surfaces
- job and agent recovery commands for reset, kill, orphan reset, and stale lock reap
- filesystem-backed runtime state
- package-managed runtime tools materialized under `.git-agents/state` for agents and internals
- `start` supervises the console runner and configured team agents directly

See [docs/PLAN.md](docs/PLAN.md) for the full command model, Git integration
notes, state layout, and packaging plan. See
[docs/TEAM_TOML.md](docs/TEAM_TOML.md) for the repo-local team configuration
format.
