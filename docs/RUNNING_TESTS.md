# Running Tests Safely

GitAgents tests and smoke checks often create temporary Git repositories and run
`git agents` commands inside them. Be strict about test working directories:
tests intended for a temporary repository must actually run there, not in the
`git-agents` development checkout.

## Standard Checks

Run these from the repository root:

```sh
python3 -m unittest discover -s tests
git diff --check
python3 -m py_compile git_agents/runtime/tools/agent git_agents/runtime/tools/agent-pi-interactive git_agents/runtime/tools/git-agents-ui git_agents/runtime/tools/heartbeat git_agents/runtime/tools/console-input git_agents/runtime/tools/console-notifier git_agents/runtime/tools/console_input.py git_agents/cli.py git_agents/dashboard.py
python3 -m compileall git_agents tests
```

After any test or smoke command that may initialize GitAgents, also run:

```sh
git status --short .gitignore .git-agents
```

That output must be empty unless the current task intentionally changes those
paths.

## Temp-Repo Smoke Tests

Use this shape for manual smoke tests of `git agents init`:

```sh
tmp=$(mktemp -d /tmp/gitagents-smoke.XXXXXX)
git -C "$tmp" init >/dev/null
cd "$tmp"
PYTHONPATH=/path/to/git-agents python3 -m git_agents init
find .git-agents -maxdepth 2 \( -type d -o -type f \) | sort
```

The explicit `cd "$tmp"` before `python3 -m git_agents init` is required.

## Bad Smoke Pattern

This is wrong:

```sh
tmp=$(mktemp -d /tmp/gitagents-smoke.XXXXXX)
git -C "$tmp" init >/dev/null
PYTHONPATH=/path/to/git-agents python3 -m git_agents init
```

`git -C "$tmp"` applies only to `git init`. The Python command still runs in the
current shell directory and can create `.git-agents/` in the development checkout
by accident.

## Test Hygiene

- Unit tests should use `tempfile.TemporaryDirectory()` for repositories they
  initialize.
- Helpers that run `git agents` should set `cwd` to the temporary repository.
- Manual smoke commands should either set the tool `workdir` to the temp repo or
  use an explicit `cd "$tmp"` before running `python3 -m git_agents`.
- Never accept `.git-agents/` or `.gitignore` changes in the development
  checkout as a side effect of running tests.
