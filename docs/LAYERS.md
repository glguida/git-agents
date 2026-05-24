# GitAgents Layers

GitAgents is easiest to reason about as a system for building repository-local
agent systems. The fixed GitAgents protocol provides the coordination machinery;
repositories define the project-facing agent system on top with roles, team
configuration, project documentation, and optional skills.

Each layer answers a different question, and each layer should avoid
duplicating the others.

## 1. Fixed GitAgents Protocol

The fixed protocol answers:

> How do agents coordinate?

This layer is repository-agnostic. It defines the mechanics of tasks, jobs,
agent state, logs, transcripts, result files, console input, managed helper
processes, and recovery commands.

Examples:

- how a task is created
- how a job is claimed, started, completed, failed, reset, or killed
- where job specs and results are stored
- where agent transcripts and pid files live
- how an agent notifies the planner or records a blocker
- how the interactive console receives live input
- how heartbeat and role=`console` jobs reach the console
- how running repository `.git-agents` directories are linked for the global dashboard

This belongs to GitAgents itself. In an initialized repository, the
GitAgents-owned protocol file lives at:

```text
.git-agents/AGENTS.md
```

That file is GitAgents-owned system protocol. It is copied on `git agents init`
and refreshed by `git agents update` together with the GitAgents command
helpers, because the protocol and helpers are versioned together.

Repository-specific behavior should not be added to `.git-agents/AGENTS.md`.
Project configuration should not redefine the queue protocol.

The default role files and default `team.toml` installed by `init` are starter
templates for higher layers. They are useful defaults, not the fixed Layer 1
contract. See [Layer 1: GitAgents System Contract](LAYER_ONE.md) for the
user-facing Layer 1 details.

## 2. Repository Rules

Repository rules answer:

> What is always true in this repository?

These are project-specific invariants that agents must obey while working in
the repository. They usually already exist in repository documentation.

Examples:

- coding style
- required test commands
- review policy
- license and copyright rules
- required deliverables for changes
- architecture or translation constraints
- release or integration policy

GitAgents should not duplicate canonical project documentation. Instead, roles,
task specs, and skills should point agents to the authoritative project files.

Useful locations:

```text
AGENTS.md
docs/
```

## 3. Repository Roles

Roles answer:

> What kind of work is this agent responsible for?

A role is a durable project-facing responsibility, not just a process name. A
repository can define roles that fit its own work model.

Examples:

- planner
- implementer
- reviewer
- committer
- translator
- integrator
- release manager
- verification engineer

Roles are the right place for mandatory responsibility boundaries. If an agent
with a given role must always produce a specific set of artifacts, read a
specific project document, or avoid a category of edits, that should be stated
in the role.

Useful locations:

```text
.git-agents/roles/<role>.md
```

## 4. Team Configuration

The team answers:

> Which named agents are running?

The team is process configuration. It should say which named agents exist, what
role each agent serves, what engine each uses, and any per-agent launch policy
that belongs to the process.

Example:

```toml
[[agents]]
name = "planner-1"
role = "planner"
engine = "pi"

[[agents]]
name = "reviewer-1"
role = "reviewer"
engine = "pi"
```

The team should not become a workflow graph. Behavior belongs in roles and
project rules; the team only decides which workers are alive.

Useful location:

```text
.git-agents/team.toml
```

## 5. Skills

Skills answer:

> What specialized playbook may help this agent on demand?

Skills are not mandatory baseline rules and they are not permissions. They are
discoverable, on-demand instructions for specialized procedures, domains, or
tools.

Examples:

- debugging a specific simulator failure
- performing a security review
- running a release checklist
- translating a recurring hardware pattern
- using a project-specific script

Pi skills live naturally at repository root in Pi's conventional locations:

```text
.agents/skills/<skill>/SKILL.md
.pi/skills/<skill>/SKILL.md
```

A role may mention important skills, but baseline obligations should remain in
repository rules or role files. Skills are best used for targeted expertise
that should be loaded only when relevant.

## 6. Tools And Extensions

Tools and extensions answer:

> What can the runtime actually do?

Tools are callable actions, such as reading files, running commands, editing
files, or invoking a custom API. Extensions can add tools, commands, UI, event
hooks, provider integrations, and policy gates.

These are runtime capabilities, not project roles. Tool availability can be
configured separately from the conceptual responsibility of an agent.

Examples:

- a reviewer role may run with read-only tools
- an implementer role may run with edit/write tools
- an interactive console may load web-search extensions
- queued agents may run without web-search extensions

## Where Workflow Fits

"Workflow" is often a useful human word, but it should not automatically become
a separate GitAgents object.

Many workflows are just a combination of:

- repository rules
- one or more roles
- a team that runs those roles
- optional skills for specialized tactics

Before adding a new workflow abstraction, ask:

1. Is this a coordination mechanic? Put it in the fixed protocol.
2. Is this always true for the repository? Put it in repository rules.
3. Is this a responsibility boundary? Put it in a role.
4. Is this just which workers are running? Put it in `team.toml`.
5. Is this optional specialized expertise? Put it in a skill.
6. Is this a runtime capability or permission? Configure tools/extensions.

This keeps GitAgents flexible without flattening project-specific behavior into
a central workflow graph.
