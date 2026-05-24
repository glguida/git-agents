# git-agents

GitAgents is a framework for defining, running, and evolving agentic systems in git.
It provides the fixed coordination protocol, queue commands, launchers, and UI;
each repository supplies the project-facing roles, team configuration, docs,
skills, and operating policy that make those agents useful for that codebase.

The default planner, implementer, reviewer, committer, and console role
templates work out of the box, while tracked repo-local role files let a
project adapt those agents to its own architecture, test commands, review
standards, release process, and risk policy.

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
git agents update
git agents status
git agents tasks create my-task spec.md
git agents start
git agents start --no-heartbeat
git agents start --heartbeat 5
git agents prompt "summarize current status"
git agents prompt --quiet "leave the response in the log"
git agents log -f
git agents rules show
git agents role list
git agents team list
git agents agents list
git agents jobs kill my-task-plan -m "stop now"
git agents jobs create notify-console-1 --role console --task my-task spec.md
git agents agents reset planner-1
gitagents-dashboard
```

GitAgents can initialize an empty Git repository, but agent work expects the
repository to have at least one commit. For a new project, initialize GitAgents
and commit the stationary `.git-agents` files before starting agents:

```sh
git init
git agents init
git add .gitignore .git-agents
git commit -m "Initialize git-agents"
git agents start
git agents prompt "Add a task to write a simple hello world in C"
```

## Repository Layout

GitAgents has a stationary repository side and a local execution-state side.
The stationary side can be committed:

```text
.git-agents/AGENTS.md
.git-agents/bin/
.git-agents/tools/
.git-agents/roles/
.git-agents/team.toml
```

Runtime state lives under the repo-local GitAgents directory:

```text
.git-agents/state/
```

`git agents init` installs `.git-agents/AGENTS.md`, `.git-agents/bin`,
`.git-agents/tools`, default roles, and default `team.toml`. It also adds
`.git-agents/state/` to `.gitignore`. `.git-agents/AGENTS.md` is GitAgents-owned
system protocol, not the place for repository rules. Put repository policy in
normal project documentation and repo-local roles.

`git agents update` refreshes the package-managed runtime command helpers and
the GitAgents-owned `.git-agents/AGENTS.md` together. It does not rewrite
repo-local roles by default. Use `git agents update --roles` only when you
explicitly want to refresh the default role templates under `.git-agents/roles/`.

After updating GitAgents itself, run this in each repository that already has
GitAgents installed:

```sh
git agents update
git agents restart
```

`update` refreshes installed Layer 1 files. `restart` is needed only when a
supervisor is already running, so newly installed managed tools such as
heartbeat and console job forwarding are started.

`git agents start` links the running repository into the per-user
instances directory:

```text
~/.gitagents/instances/
```

Each entry points at the repository's `.git-agents` directory. The dashboard
reads status from that real directory; it does not maintain a second copy of
repository state.

Use the separate dashboard utility to inspect all running repositories with one
UI:

```sh
gitagents-dashboard
```

`gitagents-dashboard` is installed globally by the Python package, the same way
`git-agents` is installed. It is not copied into `.git-agents/tools/`.

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
- runtime/protocol refresh with `update`
- multi-repository dashboard with `gitagents-dashboard`
- GitAgents-owned generic protocol installed at `.git-agents/AGENTS.md`
- generic role templates copied from the local agent template source
- role, rules, team, task, job, status, log, and prompt command surfaces
- job and agent recovery commands for reset, kill, orphan reset, and stale lock reap
- filesystem-backed runtime state
- package-managed command helpers materialized under `.git-agents/bin` and `.git-agents/tools`
- `start` links running repository `.git-agents` directories under `~/.gitagents/instances/`
- `start` supervises the console runner and configured team agents directly
- `start` sends a console heartbeat immediately and then every 15 minutes by default; use
  `--heartbeat <minutes>` or `--no-heartbeat`
- jobs whose role is `console` are forwarded to the interactive console through
  the same input path as `git agents prompt`
- `gitagents-dashboard` serves the same UI style across all linked
  running GitAgents repositories

See [docs/LAYER_ONE.md](docs/LAYER_ONE.md) for the user-facing Layer 1 system
contract: installed files, update/restart, supervisor behavior, heartbeat, and
console jobs. See [docs/LAYERS.md](docs/LAYERS.md) for the conceptual
layering model, [docs/PLAN.md](docs/PLAN.md) for the full command model, and
[docs/TEAM_TOML.md](docs/TEAM_TOML.md) for the repo-local team configuration
format. See [docs/RUNNING_TESTS.md](docs/RUNNING_TESTS.md) for test-running
guardrails used while developing GitAgents.
