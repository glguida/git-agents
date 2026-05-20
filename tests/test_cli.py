from __future__ import annotations

import contextlib
import importlib.machinery
import importlib.util
import io
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
AGENT_TOOL = REPO_ROOT / "git_agents" / "runtime" / "tools" / "agent"
INTERACTIVE_AGENT_TOOL = REPO_ROOT / "git_agents" / "runtime" / "tools" / "agent-pi-interactive"


class CliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        subprocess.run(["git", "init"], cwd=self.repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.env = os.environ.copy()
        pythonpath = self.env.get("PYTHONPATH")
        self.env["PYTHONPATH"] = str(REPO_ROOT) if not pythonpath else f"{REPO_ROOT}{os.pathsep}{pythonpath}"

    def tearDown(self) -> None:
        subprocess.run(
            [sys.executable, "-m", "git_agents", "stop"],
            cwd=self.repo,
            env=self.env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        self.tmp.cleanup()

    def run_agents(self, *args: str, input_text: str | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
        proc = subprocess.run(
            [sys.executable, "-m", "git_agents", *args],
            cwd=self.repo,
            env=self.env,
            input=input_text,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if check and proc.returncode != 0:
            self.fail(
                f"git_agents {' '.join(args)} failed with {proc.returncode}\n"
                f"stdout:\n{proc.stdout}\n"
                f"stderr:\n{proc.stderr}"
            )
        return proc

    def run_agents_with_env(
        self,
        env: dict[str, str],
        *args: str,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        proc = subprocess.run(
            [sys.executable, "-m", "git_agents", *args],
            cwd=self.repo,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if check and proc.returncode != 0:
            self.fail(
                f"git_agents {' '.join(args)} failed with {proc.returncode}\n"
                f"stdout:\n{proc.stdout}\n"
                f"stderr:\n{proc.stderr}"
            )
        return proc

    def git_path(self, name: str) -> Path:
        out = subprocess.run(
            ["git", "rev-parse", "--git-path", name],
            cwd=self.repo,
            stdout=subprocess.PIPE,
            text=True,
            check=True,
        ).stdout.strip()
        path = Path(out)
        return path if path.is_absolute() else self.repo / path

    def state_path(self) -> Path:
        return self.repo / ".git-agents" / "state"

    def run_runtime_bin(self, state: Path, *args: str) -> subprocess.CompletedProcess[str]:
        proc = subprocess.run(
            [str(state / "bin" / args[0]), *args[1:]],
            cwd=state,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            self.fail(
                f"{args[0]} failed with {proc.returncode}\n"
                f"stdout:\n{proc.stdout}\n"
                f"stderr:\n{proc.stderr}"
            )
        return proc

    def create_demo_task(self, task: str = "demo-task") -> tuple[Path, str]:
        self.run_agents("init")
        spec = self.repo / f"{task}.md"
        spec.write_text(f"# {task}\n\nDo the thing.\n", encoding="utf-8")
        self.run_agents("tasks", "create", task, str(spec))
        return self.state_path(), f"{task}-plan"

    def claim_and_start_job(self, state: Path, job: str, agent: str = "planner-1") -> None:
        self.run_runtime_bin(state, "agent-new", agent, "planner")
        self.run_runtime_bin(state, "job-claim", job, "--agent-id", agent)
        self.run_runtime_bin(state, "job-start", job, "--agent-id", agent)
        (state / "agents" / agent / "current-job").write_text(f"{job}\n", encoding="utf-8")

    def load_agent_tool(self):
        loader = importlib.machinery.SourceFileLoader("git_agents_runtime_agent_test", str(AGENT_TOOL))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        self.assertIsNotNone(spec)
        assert spec is not None
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        return module

    def load_interactive_agent_tool(self):
        loader = importlib.machinery.SourceFileLoader(
            "git_agents_runtime_interactive_agent_test",
            str(INTERACTIVE_AGENT_TOOL),
        )
        spec = importlib.util.spec_from_loader(loader.name, loader)
        self.assertIsNotNone(spec)
        assert spec is not None
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        return module

    def test_follow_console_turn_finishes_partial_line_with_newline(self) -> None:
        from git_agents import cli

        console_dir = self.repo / "console"
        console_dir.mkdir()
        (console_dir / "busy").write_text("0\n", encoding="utf-8")
        transcript = console_dir / "transcript.log"
        transcript.write_text("agent response without newline", encoding="utf-8")

        output = io.StringIO()
        with (
            mock.patch.object(cli.time, "time", side_effect=[0.0, 0.0, 0.5]),
            mock.patch.object(cli.time, "sleep"),
            contextlib.redirect_stdout(output),
        ):
            cli.follow_console_turn(console_dir, transcript, 0)

        self.assertEqual(output.getvalue(), "agent response without newline\n")

    def test_console_engine_is_not_configurable(self) -> None:
        from git_agents import cli

        parser = cli.build_parser(include_internal=True)

        self.assertFalse(hasattr(parser.parse_args(["start"]), "console_engine"))
        self.assertFalse(hasattr(parser.parse_args(["restart"]), "console_engine"))
        self.assertFalse(
            hasattr(
                parser.parse_args(
                    ["_supervisor", "--repo-root", str(self.repo), "--state-dir", str(self.state_path())]
                ),
                "console_engine",
            )
        )

    def test_runtime_agent_defaults_to_pi(self) -> None:
        agent_tool = self.load_agent_tool()
        interactive_tool = self.load_interactive_agent_tool()

        with mock.patch.object(sys, "argv", ["agent", "planner", "planner-1"]):
            self.assertEqual(agent_tool.parse_args().engine, "pi")
        with mock.patch.object(sys, "argv", ["agent-pi-interactive", "--console"]):
            self.assertEqual(interactive_tool.parse_args().engine, "pi")

    def test_interactive_prompts_name_runtime_root(self) -> None:
        interactive_tool = self.load_interactive_agent_tool()
        root = Path("/tmp/repo/.git-agents/state")
        repo_root = Path("/tmp/repo")

        console_prompt = interactive_tool.build_prompt(
            "console",
            True,
            root,
            repo_root,
            role_text="# Console Role",
        )
        self.assertIn("Your GitAgents runtime root is: /tmp/repo/.git-agents/state", console_prompt)
        self.assertIn("Your target repository root is: /tmp/repo", console_prompt)
        self.assertIn("Read /tmp/repo/.git-agents/state/AGENTS.md", console_prompt)
        self.assertIn("effective generic GitAgents protocol", console_prompt)
        self.assertIn("Use the runtime bin tools under /tmp/repo/.git-agents/state/bin", console_prompt)
        self.assertIn("paths such as agents/, jobs/, tasks/, roles/, and bin/", console_prompt)

        agent_prompt = interactive_tool.build_prompt(
            "planner-1",
            False,
            root,
            repo_root,
            "demo-plan",
        )
        self.assertIn("Your GitAgents runtime root is: /tmp/repo/.git-agents/state", agent_prompt)
        self.assertIn("Your target repository root is: /tmp/repo", agent_prompt)
        self.assertIn("Your assigned job is: demo-plan", agent_prompt)
        self.assertIn("Read /tmp/repo/.git-agents/state/AGENTS.md", agent_prompt)
        self.assertIn("effective generic GitAgents protocol", agent_prompt)
        self.assertIn("Use the runtime bin tools under /tmp/repo/.git-agents/state/bin", agent_prompt)

    def test_init_creates_git_private_state_without_tracked_config(self) -> None:
        self.run_agents("init")

        state = self.state_path()
        self.assertTrue((state / "tasks").is_dir())
        self.assertTrue((state / "jobs").is_dir())
        self.assertTrue((state / "agents").is_dir())
        self.assertTrue((state / "runs").is_dir())
        self.assertTrue((state / "logs").is_dir())
        self.assertTrue((state / "config.json").is_file())
        self.assertTrue((state / "repo-root").is_file())
        self.assertTrue((state / "bin" / "task-create").is_file())
        self.assertTrue((state / "tools" / "run_git_agents").is_file())
        self.assertTrue((state / "tools" / "git-agents-ui").is_file())
        self.assertTrue((state / "roles" / "planner.md").is_file())
        self.assertIn("/.git-agents/state/", (self.repo / ".gitignore").read_text(encoding="utf-8"))
        self.assertFalse((self.repo / ".git-agents" / "AGENTS.md").exists())

        status = subprocess.run(
            ["git", "status", "--short"],
            cwd=self.repo,
            stdout=subprocess.PIPE,
            text=True,
            check=True,
        ).stdout
        self.assertNotIn(".git-agents/state", status)
        self.assertIn(".gitignore", status)

    def test_init_materializes_effective_rules_into_runtime(self) -> None:
        self.run_agents("init")
        state_rules = self.state_path() / "AGENTS.md"
        self.assertIn("Generic Agent Protocol", state_rules.read_text(encoding="utf-8"))

        local_rules = self.repo / ".git-agents" / "AGENTS.md"
        local_rules.write_text("# Local Rules\n\nRepo-specific protocol.\n", encoding="utf-8")
        self.run_agents("init")

        self.assertEqual(state_rules.read_text(encoding="utf-8"), local_rules.read_text(encoding="utf-8"))

    def test_tracked_config_materializes_rules_roles_and_team(self) -> None:
        self.run_agents("init", "--tracked-config")

        self.assertIn("Generic Agent Protocol", (self.repo / ".git-agents" / "AGENTS.md").read_text())
        self.assertIn("Absolutely no deferring", (self.repo / ".git-agents" / "roles" / "implementer.md").read_text())
        self.assertIn("[[agents]]", (self.repo / ".git-agents" / "team.toml").read_text())
        self.assertTrue((self.repo / ".git-agents" / "specs").is_dir())

        rules = self.run_agents("rules", "show").stdout
        role = self.run_agents("role", "show", "implementer").stdout
        self.assertIn("Generic Agent Protocol", rules)
        self.assertIn("Absolutely no deferring", role)

    def test_init_migrates_legacy_git_private_state(self) -> None:
        legacy = self.git_path("agents")
        (legacy / "jobs" / "legacy-job").mkdir(parents=True)
        (legacy / "jobs" / "legacy-job" / "status").write_text("pending\n", encoding="utf-8")

        self.run_agents("init")

        migrated = self.state_path() / "jobs" / "legacy-job" / "status"
        self.assertEqual(migrated.read_text(encoding="utf-8").strip(), "pending")

    def test_team_add_materializes_local_team(self) -> None:
        self.run_agents("team", "add", "tester-1", "--role", "reviewer", "--engine", "pi", "--model", "test-model")

        team_file = self.repo / ".git-agents" / "team.toml"
        self.assertTrue(team_file.is_file())
        self.assertIn('name = "tester-1"', team_file.read_text())

        listing = self.run_agents("team", "list").stdout
        self.assertIn("tester-1", listing)
        self.assertIn("test-model", listing)

    def test_team_add_accepts_interactive_engines(self) -> None:
        self.run_agents("team", "add", "console-reviewer", "--role", "reviewer", "--engine", "pi-interactive")

        listing = self.run_agents("team", "list").stdout
        self.assertIn("console-reviewer", listing)
        self.assertIn("pi-interactive", listing)

    def test_team_list_reads_team_run_pid_state(self) -> None:
        self.run_agents("init")
        state = self.state_path()
        run_dir = state / "agents" / ".team-runs"
        run_dir.mkdir(parents=True)
        (run_dir / "planner-1.pid").write_text(f"{os.getpid()}\n", encoding="utf-8")

        listing = self.run_agents("team", "list").stdout
        self.assertIn("planner-1", listing)
        self.assertIn("running", listing)

    def test_tasks_and_jobs_list_filesystem_state(self) -> None:
        self.run_agents("init")
        spec = self.repo / "demo-spec.md"
        spec.write_text("# Demo Task\n\nDo the thing.\n", encoding="utf-8")
        self.run_agents("tasks", "create", "demo-task", str(spec))

        tasks = self.run_agents("tasks", "list").stdout
        jobs = self.run_agents("jobs", "list").stdout
        self.assertIn("demo-task", tasks)
        self.assertIn("Demo Task", tasks)
        self.assertIn("demo-task-plan", jobs)
        self.assertIn("planner", jobs)

        job_spec = self.repo / "job-spec.md"
        job_spec.write_text("# Follow-up\n\nDo more.\n", encoding="utf-8")
        self.run_agents("jobs", "create", "demo-review", "--role", "reviewer", "--task", "demo-task", str(job_spec))
        jobs = self.run_agents("jobs", "list").stdout
        self.assertIn("demo-review", jobs)
        self.assertIn("reviewer", jobs)

    def test_jobs_reset_requeues_owned_job(self) -> None:
        state, job = self.create_demo_task()
        self.claim_and_start_job(state, job)

        reset = self.run_agents("jobs", "reset", job, "-m", "retry this job")
        self.assertIn(f"{job}: running -> pending", reset.stdout)
        self.assertEqual((state / "jobs" / job / "status").read_text(encoding="utf-8").strip(), "pending")
        self.assertFalse((state / "jobs" / job / "agent-id").exists())
        self.assertFalse((state / "jobs" / job / "lock").exists())
        self.assertEqual((state / "agents" / "planner-1" / "current-job").read_text(encoding="utf-8").strip(), "")

    def test_jobs_kill_marks_owned_job_failed(self) -> None:
        state, job = self.create_demo_task()
        self.claim_and_start_job(state, job)

        killed = self.run_agents("jobs", "kill", job, "-m", "stop now")
        self.assertIn(f"{job}: running -> failed", killed.stdout)
        self.assertEqual((state / "jobs" / job / "status").read_text(encoding="utf-8").strip(), "failed")
        self.assertEqual((state / "jobs" / job / "agent-id").read_text(encoding="utf-8").strip(), "planner-1")
        self.assertFalse((state / "jobs" / job / "lock").exists())
        self.assertEqual((state / "agents" / "planner-1" / "current-job").read_text(encoding="utf-8").strip(), "")

    def test_agents_reset_requeues_active_jobs(self) -> None:
        state, job = self.create_demo_task()
        self.claim_and_start_job(state, job)

        reset = self.run_agents("agents", "reset", "planner-1", "--no-kill", "-m", "reset agent")
        self.assertIn("reset agent planner-1: jobs reset=1", reset.stdout)
        self.assertEqual((state / "jobs" / job / "status").read_text(encoding="utf-8").strip(), "pending")
        self.assertFalse((state / "jobs" / job / "agent-id").exists())
        self.assertEqual((state / "agents" / "planner-1" / "current-job").read_text(encoding="utf-8").strip(), "")

    def test_start_and_stop_supervisor(self) -> None:
        self.run_agents("start", "--no-console")
        time.sleep(0.2)

        status = self.run_agents("status").stdout
        self.assertIn("supervisor", status)
        self.assertIn("running", status)

        stopped = self.run_agents("stop").stdout
        self.assertIn("stopped git agents supervisor", stopped)

    def test_start_validates_engines_before_daemonizing(self) -> None:
        env = self.env.copy()
        env["PATH"] = "/usr/bin:/bin"
        proc = self.run_agents_with_env(env, "start", "--no-console", check=False)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("required command not found: pi", proc.stderr)


if __name__ == "__main__":
    unittest.main()
