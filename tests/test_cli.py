from __future__ import annotations

import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
AGENT_TOOL = REPO_ROOT / "git_agents" / "runtime" / "tools" / "agent"
INTERACTIVE_AGENT_TOOL = REPO_ROOT / "git_agents" / "runtime" / "tools" / "agent-pi-interactive"
HEARTBEAT_TOOL = REPO_ROOT / "git_agents" / "runtime" / "tools" / "heartbeat"
CONSOLE_INPUT_TOOL = REPO_ROOT / "git_agents" / "runtime" / "tools" / "console-input"
CONSOLE_NOTIFIER_TOOL = REPO_ROOT / "git_agents" / "runtime" / "tools" / "console-notifier"
GIT_AGENTS_UI_TOOL = REPO_ROOT / "git_agents" / "runtime" / "tools" / "git-agents-ui"


class CliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        subprocess.run(["git", "init"], cwd=self.repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.env = os.environ.copy()
        pythonpath = self.env.get("PYTHONPATH")
        self.env["PYTHONPATH"] = str(REPO_ROOT) if not pythonpath else f"{REPO_ROOT}{os.pathsep}{pythonpath}"
        self.env["GIT_AGENTS_REGISTRY_DIR"] = str(self.repo / ".registry")

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
        git_agents_dir = state.parent
        proc = subprocess.run(
            [str(git_agents_dir / "bin" / args[0]), *args[1:]],
            cwd=git_agents_dir,
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
        sys.modules[loader.name] = module
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
        sys.modules[loader.name] = module
        loader.exec_module(module)
        return module

    def load_ui_tool(self):
        loader = importlib.machinery.SourceFileLoader("git_agents_runtime_ui_test", str(GIT_AGENTS_UI_TOOL))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        self.assertIsNotNone(spec)
        assert spec is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[loader.name] = module
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

    def test_serve_is_not_a_git_agents_subcommand(self) -> None:
        from git_agents import cli

        parser = cli.build_parser()
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                parser.parse_args(["serve"])

    def test_heartbeat_defaults_to_fifteen_minutes(self) -> None:
        from git_agents import cli

        parser = cli.build_parser(include_internal=True)

        start = parser.parse_args(["start"])
        restart = parser.parse_args(["restart"])
        disabled = parser.parse_args(["start", "--no-heartbeat"])
        custom = parser.parse_args(["start", "--heartbeat", "5"])
        internal = parser.parse_args(
            ["_supervisor", "--repo-root", str(self.repo), "--state-dir", str(self.state_path())]
        )

        self.assertEqual(start.heartbeat, 15)
        self.assertFalse(start.no_heartbeat)
        self.assertEqual(restart.heartbeat, 15)
        self.assertTrue(disabled.no_heartbeat)
        self.assertEqual(custom.heartbeat, 5)
        self.assertEqual(internal.heartbeat, 0)

    def test_effective_heartbeat(self) -> None:
        from git_agents import cli

        self.assertEqual(cli.effective_heartbeat(False, False, 15), 15)
        self.assertEqual(cli.effective_heartbeat(True, False, 15), 0)
        self.assertEqual(cli.effective_heartbeat(False, True, 15), 0)
        with self.assertRaises(cli.UserError):
            cli.effective_heartbeat(False, False, 0)

    def test_heartbeat_tool_sends_console_prompt(self) -> None:
        self.run_agents("init")
        console_dir = self.state_path() / "agents" / "console"
        console_dir.mkdir(parents=True)
        fifo = console_dir / "input.fifo"
        os.mkfifo(fifo)
        lines: list[str] = []
        errors: list[BaseException] = []

        def read_fifo() -> None:
            try:
                with fifo.open("r", encoding="utf-8") as stream:
                    lines.append(stream.readline())
            except BaseException as exc:  # pragma: no cover - reported below
                errors.append(exc)

        reader = threading.Thread(target=read_fifo)
        reader.start()
        proc = subprocess.run(
            [str(HEARTBEAT_TOOL), "--state-dir", str(self.state_path()), "--minutes", "1", "--once"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        reader.join(timeout=2)
        if reader.is_alive():
            try:
                fd = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
                os.write(fd, b"\n")
                os.close(fd)
            except OSError:
                pass
            reader.join(timeout=1)

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse(errors)
        self.assertEqual(len(lines), 1)
        payload = json.loads(lines[0])
        self.assertEqual(payload["mode"], "prompt")
        self.assertRegex(payload["message"], r"^heartbeat [0-9]{2}:[0-9]{2}:[0-9]{2}Z [0-9]{4}-[0-9]{2}-[0-9]{2}$")

    def test_heartbeat_waits_for_console_fifo_before_first_send(self) -> None:
        self.run_agents("init")
        console_dir = self.state_path() / "agents" / "console"
        fifo = console_dir / "input.fifo"
        lines: list[str] = []
        errors: list[BaseException] = []

        proc = subprocess.Popen(
            [str(HEARTBEAT_TOOL), "--state-dir", str(self.state_path()), "--minutes", "1"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            time.sleep(0.2)
            console_dir.mkdir(parents=True)
            os.mkfifo(fifo)

            def read_fifo() -> None:
                try:
                    with fifo.open("r", encoding="utf-8") as stream:
                        lines.append(stream.readline())
                except BaseException as exc:  # pragma: no cover - reported below
                    errors.append(exc)

            reader = threading.Thread(target=read_fifo)
            reader.start()
            reader.join(timeout=3)
            self.assertFalse(reader.is_alive())
            self.assertFalse(errors)
            self.assertEqual(len(lines), 1)
            payload = json.loads(lines[0])
            self.assertEqual(payload["mode"], "prompt")
            self.assertRegex(payload["message"], r"^heartbeat [0-9]{2}:[0-9]{2}:[0-9]{2}Z [0-9]{4}-[0-9]{2}-[0-9]{2}$")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3)

    def test_console_input_tool_sends_prompt(self) -> None:
        self.run_agents("init")
        console_dir = self.state_path() / "agents" / "console"
        console_dir.mkdir(parents=True)
        fifo = console_dir / "input.fifo"
        os.mkfifo(fifo)
        lines: list[str] = []
        errors: list[BaseException] = []

        def read_fifo() -> None:
            try:
                with fifo.open("r", encoding="utf-8") as stream:
                    lines.append(stream.readline())
            except BaseException as exc:  # pragma: no cover - reported below
                errors.append(exc)

        reader = threading.Thread(target=read_fifo)
        reader.start()
        proc = subprocess.run(
            [str(CONSOLE_INPUT_TOOL), "--state-dir", str(self.state_path()), "hello", "console"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        reader.join(timeout=2)
        if reader.is_alive():
            try:
                fd = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
                os.write(fd, b"\n")
                os.close(fd)
            except OSError:
                pass
            reader.join(timeout=1)

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse(errors)
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0]), {"message": "hello console", "mode": "prompt"})

    def test_console_notifier_forwards_console_jobs(self) -> None:
        state, _job = self.create_demo_task("console-task")
        spec = self.repo / "console-note.md"
        spec.write_text("# Tell Console\n\nReview needed.\n", encoding="utf-8")
        self.run_runtime_bin(state, "job-create", "console-note", "-r", "console", "-t", "console-task", str(spec))

        console_dir = self.state_path() / "agents" / "console"
        console_dir.mkdir(parents=True)
        fifo = console_dir / "input.fifo"
        os.mkfifo(fifo)
        lines: list[str] = []
        errors: list[BaseException] = []

        def read_fifo() -> None:
            try:
                with fifo.open("r", encoding="utf-8") as stream:
                    lines.append(stream.readline())
            except BaseException as exc:  # pragma: no cover - reported below
                errors.append(exc)

        reader = threading.Thread(target=read_fifo)
        reader.start()
        proc = subprocess.run(
            [str(CONSOLE_NOTIFIER_TOOL), "--state-dir", str(self.state_path()), "--once"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        reader.join(timeout=2)
        if reader.is_alive():
            try:
                fd = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
                os.write(fd, b"\n")
                os.close(fd)
            except OSError:
                pass
            reader.join(timeout=1)

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse(errors)
        self.assertEqual(len(lines), 1)
        self.assertEqual(
            json.loads(lines[0]),
            {"message": "Console job: console-note\n\n# Tell Console\n\nReview needed.", "mode": "prompt"},
        )
        job_dir = state / "jobs" / "console-note"
        self.assertEqual((job_dir / "status").read_text(encoding="utf-8").strip(), "done")
        self.assertEqual((job_dir / "agent-id").read_text(encoding="utf-8").strip(), "console-notifier")
        self.assertFalse((job_dir / "lock").exists())
        self.assertIn("Forwarded console job", (job_dir / "log.md").read_text(encoding="utf-8"))

    def test_console_notifier_ignores_non_console_jobs(self) -> None:
        state, job = self.create_demo_task("planner-task")

        proc = subprocess.run(
            [str(CONSOLE_NOTIFIER_TOOL), "--state-dir", str(state), "--once"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual((state / "jobs" / job / "status").read_text(encoding="utf-8").strip(), "pending")

    def test_ui_registry_lists_running_instances(self) -> None:
        ui_tool = self.load_ui_tool()
        state = self.state_path()
        for name in ("tasks", "jobs", "agents"):
            (state / name).mkdir(parents=True)
        (state / "runs").mkdir(parents=True)
        (state / "repo-root").write_text(str(self.repo) + "\n", encoding="utf-8")
        (state / "runs" / "supervisor.pid").write_text(str(os.getpid()) + "\n", encoding="utf-8")
        registry_dir = self.repo / ".registry"
        instances_dir = registry_dir / "instances"
        instances_dir.mkdir(parents=True)
        os.symlink(self.repo / ".git-agents", instances_dir / "demo", target_is_directory=True)

        config = ui_tool.Config(
            root=state,
            host="127.0.0.1",
            port=0,
            registry=True,
            registry_dir=registry_dir,
        )
        entries = ui_tool.registry_entries(config)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["id"], "demo")
        self.assertEqual(entries[0]["repoRoot"], str(self.repo))
        self.assertEqual(entries[0]["gitAgentsRoot"], str(self.repo / ".git-agents"))
        self.assertEqual(entries[0]["stateRoot"], str(state))
        self.assertEqual(entries[0]["supervisorPid"], os.getpid())
        self.assertTrue(entries[0]["running"])
        self.assertTrue(entries[0]["valid"])
        self.assertEqual(ui_tool.default_registry_root(config), str(state))

    def test_dashboard_command_runs_registry_viewer(self) -> None:
        from git_agents import dashboard

        with mock.patch.object(dashboard.subprocess, "call", return_value=0) as call:
            self.assertEqual(dashboard.main(["--port", "0"]), 0)

        command = call.call_args.args[0]
        self.assertEqual(command[0], sys.executable)
        self.assertIn("--registry", command)
        self.assertIn("--no-console", command)
        self.assertEqual(command[-2:], ["--port", "0"])

        with mock.patch.object(dashboard.subprocess, "call", side_effect=KeyboardInterrupt):
            self.assertEqual(dashboard.main([]), 0)

    def test_rules_are_inspection_only(self) -> None:
        from git_agents import cli

        parser = cli.build_parser()

        self.assertEqual(parser.parse_args(["rules", "show"]).func, cli.cmd_rules_show)
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                parser.parse_args(["rules", "edit"])
            with self.assertRaises(SystemExit):
                parser.parse_args(["rules", "reset", "--yes"])

    def test_runtime_agent_defaults_to_pi(self) -> None:
        agent_tool = self.load_agent_tool()
        interactive_tool = self.load_interactive_agent_tool()

        with mock.patch.object(sys, "argv", ["agent", "planner", "planner-1"]):
            self.assertEqual(agent_tool.parse_args().engine, "pi")
        with mock.patch.object(sys, "argv", ["agent-pi-interactive", "--console"]):
            self.assertEqual(interactive_tool.parse_args().engine, "pi")

    def test_interactive_prompts_name_runtime_root(self) -> None:
        interactive_tool = self.load_interactive_agent_tool()
        root = Path("/tmp/repo/.git-agents")
        repo_root = Path("/tmp/repo")

        console_prompt = interactive_tool.build_prompt(
            "console",
            True,
            root,
            repo_root,
        )
        self.assertIn("Your GitAgents root is: /tmp/repo/.git-agents", console_prompt)
        self.assertIn("Your GitAgents state directory is: /tmp/repo/.git-agents/state", console_prompt)
        self.assertIn("Your target repository root is: /tmp/repo", console_prompt)
        self.assertIn("Read /tmp/repo/.git-agents/AGENTS.md", console_prompt)
        self.assertIn("Read /tmp/repo/.git-agents/roles/console.md", console_prompt)
        self.assertIn("GitAgents-owned generic protocol", console_prompt)
        self.assertIn("Use the GitAgents command helpers under /tmp/repo/.git-agents/bin", console_prompt)
        self.assertIn("bin/ and roles/ as relative to the GitAgents root", console_prompt)
        self.assertIn("tasks/, jobs/, agents/, runs/, and logs/", console_prompt)
        self.assertNotIn("turn rough requests into clear task specs", console_prompt)

        agent_prompt = interactive_tool.build_prompt(
            "planner-1",
            False,
            root,
            repo_root,
            "demo-plan",
        )
        self.assertIn("Your GitAgents root is: /tmp/repo/.git-agents", agent_prompt)
        self.assertIn("Your GitAgents state directory is: /tmp/repo/.git-agents/state", agent_prompt)
        self.assertIn("Your target repository root is: /tmp/repo", agent_prompt)
        self.assertIn("Your assigned job is: demo-plan", agent_prompt)
        self.assertIn("Read /tmp/repo/.git-agents/AGENTS.md", agent_prompt)
        self.assertIn("GitAgents-owned generic protocol", agent_prompt)
        self.assertIn("Use the GitAgents command helpers under /tmp/repo/.git-agents/bin", agent_prompt)

    def test_interactive_busy_state_ignores_rpc_response_ack(self) -> None:
        interactive_tool = self.load_interactive_agent_tool()

        self.assertIs(interactive_tool.rpc_streaming_state({"type": "turn_start"}), True)
        self.assertIsNone(interactive_tool.rpc_streaming_state({"type": "response", "success": True}))
        self.assertIsNone(interactive_tool.rpc_streaming_state({"type": "response", "success": False}))
        self.assertIs(interactive_tool.rpc_streaming_state({"type": "turn_end"}), False)

    def test_console_pi_rpc_command_continues_existing_session(self) -> None:
        interactive_tool = self.load_interactive_agent_tool()
        session_dir = self.repo / "pi-session"

        command = interactive_tool.build_pi_rpc_command(None, True, "prompt", session_dir)
        self.assertNotIn("--continue", command)

        session_dir.mkdir()
        (session_dir / "session.jsonl").write_text("{}\n", encoding="utf-8")
        command = interactive_tool.build_pi_rpc_command("test-model", True, "prompt", session_dir)

        self.assertIn("--continue", command)
        self.assertIn("--append-system-prompt", command)
        self.assertIn("--session-dir", command)
        self.assertIn("test-model", command)

        non_console = interactive_tool.build_pi_rpc_command(None, False, "prompt", session_dir)
        self.assertNotIn("--continue", non_console)

    def test_console_restart_prompt_points_to_existing_transcript(self) -> None:
        interactive_tool = self.load_interactive_agent_tool()
        root = Path("/tmp/repo/.git-agents")
        transcript = self.repo / "transcript.log"
        crash = self.repo / "last-crash"
        crash.write_text("exit: 1\nactive_turn: yes\n", encoding="utf-8")

        prompt = interactive_tool.build_prompt(
            "console",
            True,
            root,
            Path("/tmp/repo"),
            transcript_path=transcript,
            include_restart_context=True,
            crash_path=crash,
        )

        self.assertIn(f"read enough recent history from {transcript}", prompt)
        self.assertIn("previous Pi process crashed during an active turn", prompt)
        self.assertIn(str(crash), prompt)

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
        self.assertFalse((state / "bin").exists())
        self.assertFalse((state / "tools").exists())
        self.assertFalse((state / "roles").exists())
        self.assertFalse((state / "AGENTS.md").exists())
        self.assertTrue((self.repo / ".git-agents" / "AGENTS.md").is_file())
        self.assertTrue((self.repo / ".git-agents" / "bin" / "task-create").is_file())
        self.assertFalse((self.repo / ".git-agents" / "tools" / "run_git_agents").exists())
        self.assertFalse((self.repo / ".git-agents" / "tools" / "git-agents-ui").exists())
        self.assertFalse((self.repo / ".git-agents" / "tools" / "git-agents-public").exists())
        self.assertTrue((self.repo / ".git-agents" / "tools" / "console-input").is_file())
        self.assertTrue((self.repo / ".git-agents" / "tools" / "console_input.py").is_file())
        self.assertTrue((self.repo / ".git-agents" / "tools" / "heartbeat").is_file())
        self.assertTrue((self.repo / ".git-agents" / "tools" / "console-notifier").is_file())
        self.assertFalse((self.repo / ".git-agents" / "tools" / "__pycache__").exists())
        self.assertTrue((self.repo / ".git-agents" / "roles" / "planner.md").is_file())
        self.assertIn(
            "ignore the heartbeat silently",
            (self.repo / ".git-agents" / "roles" / "console.md").read_text(encoding="utf-8"),
        )
        self.assertTrue((self.repo / ".git-agents" / "team.toml").is_file())
        self.assertIn(
            "Generic Agent Protocol",
            (self.repo / ".git-agents" / "AGENTS.md").read_text(encoding="utf-8"),
        )
        self.assertIn("/.git-agents/state/", (self.repo / ".gitignore").read_text(encoding="utf-8"))

        status = subprocess.run(
            ["git", "status", "--short"],
            cwd=self.repo,
            stdout=subprocess.PIPE,
            text=True,
            check=True,
        ).stdout
        self.assertNotIn(".git-agents/state", status)
        self.assertIn(".gitignore", status)
        self.assertIn(".git-agents/", status)

    def test_status_reports_running_managed_processes_without_supervisor(self) -> None:
        self.run_agents("init")
        agent_dir = self.state_path() / "agents" / "console"
        agent_dir.mkdir(parents=True)
        (agent_dir / "role").write_text("console\n", encoding="utf-8")
        (agent_dir / "runner.pid").write_text(f"{os.getpid()}\n", encoding="utf-8")

        status = self.run_agents("status").stdout

        self.assertIn("managed_processes", status)
        self.assertIn("managed processes running: 1", status)

    def test_init_installs_protocol_without_overwriting_existing_file(self) -> None:
        self.run_agents("init")
        protocol = self.repo / ".git-agents" / "AGENTS.md"
        self.assertIn("Generic Agent Protocol", protocol.read_text(encoding="utf-8"))

        protocol.write_text("# Local Rules\n\nRepo-specific protocol.\n", encoding="utf-8")
        self.run_agents("init")

        self.assertEqual("# Local Rules\n\nRepo-specific protocol.\n", protocol.read_text(encoding="utf-8"))
        self.assertFalse((self.state_path() / "AGENTS.md").exists())

    def test_update_refreshes_runtime_commands_and_protocol(self) -> None:
        self.run_agents("init")
        protocol = self.repo / ".git-agents" / "AGENTS.md"
        protocol.write_text("# stale\n", encoding="utf-8")

        task_create = self.repo / ".git-agents" / "bin" / "task-create"
        task_create.write_text("#!/bin/sh\necho stale\n", encoding="utf-8")
        planner_role = self.repo / ".git-agents" / "roles" / "planner.md"
        planner_role.write_text("# Custom Planner\n", encoding="utf-8")
        console_role = self.repo / ".git-agents" / "roles" / "console.md"
        console_role.write_text("# Custom Console\n\nPersonal console prompt.\n", encoding="utf-8")

        self.run_agents("update")

        self.assertIn("Generic Agent Protocol", protocol.read_text(encoding="utf-8"))
        self.assertIn("Create a task and enqueue its initial planner job.", task_create.read_text(encoding="utf-8"))
        self.assertEqual(planner_role.read_text(encoding="utf-8"), "# Custom Planner\n")
        self.assertEqual(console_role.read_text(encoding="utf-8"), "# Custom Console\n\nPersonal console prompt.\n")
        self.assertTrue(os.access(task_create, os.X_OK))
        self.assertFalse((self.state_path() / "AGENTS.md").exists())
        self.assertFalse((self.state_path() / "bin").exists())
        self.assertFalse((self.state_path() / "tools").exists())
        self.assertFalse((self.state_path() / "roles").exists())

    def test_update_roles_explicitly_refreshes_role_templates(self) -> None:
        self.run_agents("init")
        planner_role = self.repo / ".git-agents" / "roles" / "planner.md"
        planner_role.write_text("# stale planner\n", encoding="utf-8")
        console_role = self.repo / ".git-agents" / "roles" / "console.md"
        console_role.write_text("# stale console\n", encoding="utf-8")

        self.run_agents("update", "--roles")

        self.assertIn("Planner Role", planner_role.read_text(encoding="utf-8"))
        self.assertIn("ignore the heartbeat silently", console_role.read_text(encoding="utf-8"))

    def test_init_removes_obsolete_runtime_team_runner_files(self) -> None:
        state = self.state_path()
        stale_notification_create = self.repo / ".git-agents" / "bin" / "notification-create"
        stale_notification_create.parent.mkdir(parents=True)
        stale_notification_create.write_text("obsolete\n", encoding="utf-8")
        stale_ui = self.repo / ".git-agents" / "tools" / "git-agents-ui"
        stale_ui_public = self.repo / ".git-agents" / "tools" / "git-agents-public"
        stale_ui.parent.mkdir(parents=True)
        stale_ui.write_text("obsolete\n", encoding="utf-8")
        stale_ui_public.mkdir(parents=True)
        (stale_ui_public / "index.html").write_text("obsolete\n", encoding="utf-8")
        (state / "tools").mkdir(parents=True)
        (state / "tools" / "run_git_agents").write_text("obsolete\n", encoding="utf-8")
        (state / "bin").mkdir(parents=True)
        (state / "bin" / "task-create").write_text("obsolete\n", encoding="utf-8")
        (state / "roles").mkdir(parents=True)
        (state / "roles" / "planner.md").write_text("obsolete\n", encoding="utf-8")
        (state / "runs").mkdir(parents=True)
        (state / "runs" / "server.json").write_text("{}\n", encoding="utf-8")
        (state / "default.team").write_text("obsolete\n", encoding="utf-8")

        self.run_agents("init")

        self.assertFalse((state / "tools").exists())
        self.assertFalse((state / "bin").exists())
        self.assertFalse((state / "roles").exists())
        self.assertFalse((state / "default.team").exists())
        self.assertFalse((state / "runs" / "server.json").exists())
        self.assertFalse(stale_notification_create.exists())
        self.assertFalse(stale_ui.exists())
        self.assertFalse(stale_ui_public.exists())

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

    def test_team_agent_command_launches_direct_agent_runner(self) -> None:
        from git_agents import cli

        git_agents_dir = self.repo / ".git-agents"
        command = cli.team_agent_command(
            git_agents_dir,
            {
                "name": "reviewer-1",
                "role": "reviewer",
                "engine": "pi",
                "model": "test-model",
            },
        )
        self.assertEqual(command[0], str(git_agents_dir / "tools" / "agent"))
        self.assertEqual(command[1:], ["--pi", "--headless", "--model", "test-model", "reviewer", "reviewer-1"])

        interactive = cli.team_agent_command(
            git_agents_dir,
            {
                "name": "planner-1",
                "role": "planner",
                "engine": "pi-interactive",
            },
        )
        self.assertEqual(interactive[0], str(git_agents_dir / "tools" / "agent-pi-interactive"))
        self.assertEqual(interactive[1:], ["--pi", "--headless", "planner", "planner-1"])

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
        planner_pid = self.state_path() / "agents" / ".team-runs" / "planner-1.pid"
        deadline = time.time() + 3
        while not planner_pid.exists() and time.time() < deadline:
            time.sleep(0.1)
        self.assertTrue(planner_pid.is_file())
        registry_entries = list((self.repo / ".registry" / "instances").iterdir())
        self.assertEqual(len(registry_entries), 1)
        self.assertTrue(registry_entries[0].is_symlink())
        self.assertEqual(registry_entries[0].resolve(), self.repo / ".git-agents")

        stopped = self.run_agents("stop").stdout
        self.assertIn("stopped git agents supervisor", stopped)
        self.assertFalse(registry_entries[0].exists())

    def test_start_validates_engines_before_daemonizing(self) -> None:
        env = self.env.copy()
        env["PATH"] = "/usr/bin:/bin"
        proc = self.run_agents_with_env(env, "start", "--no-console", check=False)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("required command not found: pi", proc.stderr)


if __name__ == "__main__":
    unittest.main()
