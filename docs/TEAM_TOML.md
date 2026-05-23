# team.toml

`team.toml` is the repo-local configuration file that defines which queued
GitAgents agents are launched by `git agents start`.

It is optional. If `.git-agents/team.toml` does not exist, GitAgents uses the
packaged default team:

```toml
[[agents]]
name = "planner-1"
role = "planner"
engine = "pi"

[[agents]]
name = "implementer-1"
role = "implementer"
engine = "pi"

[[agents]]
name = "reviewer-1"
role = "reviewer"
engine = "pi"

[[agents]]
name = "committer-1"
role = "committer"
engine = "pi"
```

## Creating the File

Create or materialize the file with one of these commands:

```sh
git agents init --tracked-config
git agents team edit
git agents team add my-agent --role implementer
```

The file lives at:

```text
.git-agents/team.toml
```

Because it is outside `.git-agents/state/`, it can be committed and reviewed
like normal project configuration.

## Format

The file contains one `[[agents]]` table per configured queued agent.

Supported fields:

```toml
[[agents]]
name = "implementer-1"
role = "implementer"
engine = "pi"
model = "anthropic/claude-sonnet-4"
```

`name` is required. It is the stable runtime agent id. It must contain only
letters, numbers, dots, underscores, and hyphens.

`role` is required. It selects the role instructions from the effective
`roles/<role>.md` file. The role name uses the same character rules as `name`.

`engine` is required. Current valid values are:

- `pi`: a queued Pi agent that claims one job at a time and exits after the
  job finishes.
- `pi-interactive`: a Pi agent that still follows the queued job protocol, but
  also accepts live input through the web UI.

`model` is optional. When set, GitAgents passes it to Pi as `--model <model>`
for that agent.

No other `team.toml` fields are currently used by GitAgents.

## Console Agent

The built-in console agent is not listed in `team.toml`.

It is launched separately by `git agents start` unless you pass:

```sh
git agents start --no-console
```

Set the console model with:

```sh
git agents start --console-model openai/gpt-5
```

Queued team agents use their own optional `model` fields from `team.toml`.

## Commands

Inspect the effective team:

```sh
git agents team list
git agents team show
git agents team show implementer-1
```

Add and update agents:

```sh
git agents team add implementer-2 --role implementer --engine pi
git agents team set implementer-2 --model openai/gpt-5
git agents team set implementer-2 --engine pi-interactive
git agents team remove implementer-2
```

Edit the file directly:

```sh
git agents team edit
```

If `$EDITOR` is unset, `team edit` prints the path instead of opening an
editor.

## Runtime Behavior

Before agents start, GitAgents reads the effective `team.toml` directly. The
Python supervisor launches and restarts each configured agent; there is no
separate runtime team file to edit.

After changing `.git-agents/team.toml`, restart the supervisor for the new team
definition to take effect:

```sh
git agents restart
```

Removing an agent from `team.toml` prevents it from being launched on future
starts. It does not by itself kill an already running process; use `git agents
restart`, `git agents stop`, or recovery commands when you need to stop active
runtime agents.

## Current Limits

`team.toml` can configure agent name, role, engine, and model. It does not
currently configure per-agent Pi extensions, skills, tool allowlists, provider
settings, environment variables, or arbitrary Pi command-line arguments.

Those settings must currently be handled through Pi's own configuration or by
changing the GitAgents launch implementation.
