# git-agents

`git-agents` is a Git extension for running coding-agent workflows inside a
repository.

The user-facing command is:

```sh
git agents <command>
```

Git resolves that to an executable named `git-agents` on `PATH`.

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

Codex-backed job agents run with `workspace-write` by default and receive both
the target repository root and the GitAgents runtime root as writable
directories. Override `GIT_AGENTS_CODEX_SANDBOX` only when testing a different
Codex sandbox mode.

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
- `start` supervises the console runner and configured team runner

See [docs/PLAN.md](docs/PLAN.md) for the full command model, Git integration
notes, state layout, and packaging plan.
