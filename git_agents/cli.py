from __future__ import annotations

import argparse
import difflib
import errno
import importlib.util
import html
import json
import mimetypes
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10
    tomllib = None


PACKAGE = "git_agents"
CONFIG_DIR = ".git-agents"
STATE_DIR_NAME = "state"
STATE_IGNORE_PATTERN = f"/{CONFIG_DIR}/{STATE_DIR_NAME}/"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 4173
NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
VALID_ENGINES = {"codex", "claude", "pi"}
ENGINE_COMMAND = {"codex": "codex", "claude": "claude", "pi": "pi"}
STATE_SUBDIRS = ("tasks", "jobs", "agents", "runs", "logs")


class UserError(Exception):
    def __init__(self, message: str, code: int = 1) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Repo:
    root: Path
    prefix: str
    git_dir: Path
    state_dir: Path
    legacy_state_dir: Path

    @property
    def config_dir(self) -> Path:
        return self.root / CONFIG_DIR


def timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def validate_name(label: str, value: str) -> None:
    if not value or not NAME_RE.match(value):
        raise UserError(
            f"invalid {label} '{value}': use letters, numbers, dot, underscore, or hyphen"
        )


def run_git(args: list[str], cwd: Path | None = None) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()
        raise UserError(detail or "not inside a Git repository")
    return proc.stdout.rstrip("\n")


def discover_repo(cwd: Path | None = None) -> Repo:
    cwd = cwd or Path.cwd()
    root = Path(run_git(["rev-parse", "--show-toplevel"], cwd)).resolve()
    prefix = run_git(["rev-parse", "--show-prefix"], cwd)
    git_dir = Path(run_git(["rev-parse", "--absolute-git-dir"], cwd)).resolve()
    legacy_raw = Path(run_git(["rev-parse", "--git-path", "agents"], cwd))
    legacy_state_dir = legacy_raw if legacy_raw.is_absolute() else (cwd / legacy_raw)
    state_dir = root / CONFIG_DIR / STATE_DIR_NAME
    return Repo(
        root=root,
        prefix=prefix,
        git_dir=git_dir,
        state_dir=state_dir.resolve(),
        legacy_state_dir=legacy_state_dir.resolve(),
    )


def package_path(*parts: str):
    return resources.files(PACKAGE).joinpath(*parts)


def read_package_text(*parts: str) -> str:
    return package_path(*parts).read_text(encoding="utf-8")


def write_bytes_atomic(path: Path, data: bytes, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    tmp.write_bytes(data)
    if executable:
        tmp.chmod(0o755)
    tmp.replace(path)


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def read_text(path: Path, fallback: str = "", max_bytes: int = 512 * 1024) -> str:
    try:
        with path.open("rb") as stream:
            return stream.read(max_bytes).decode("utf-8", "replace")
    except OSError:
        return fallback


def ensure_state_gitignore(repo: Repo) -> None:
    path = repo.root / ".gitignore"
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        text = ""
    except OSError as exc:
        raise UserError(f"cannot update {path}: {exc}") from exc
    if any(line.strip() == STATE_IGNORE_PATTERN for line in text.splitlines()):
        return
    if text and not text.endswith("\n"):
        text += "\n"
    write_text_atomic(path, text + STATE_IGNORE_PATTERN + "\n")


def migrate_legacy_state(repo: Repo) -> None:
    if repo.state_dir.exists() or not repo.legacy_state_dir.is_dir():
        return
    repo.state_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(repo.legacy_state_dir, repo.state_dir)


def ensure_state(repo: Repo) -> None:
    ensure_state_gitignore(repo)
    migrate_legacy_state(repo)
    repo.state_dir.mkdir(parents=True, exist_ok=True)
    for name in STATE_SUBDIRS:
        (repo.state_dir / name).mkdir(parents=True, exist_ok=True)
    write_text_atomic(repo.state_dir / "repo-root", str(repo.root) + "\n")
    config = repo.state_dir / "config.json"
    if not config.exists():
        write_text_atomic(
            config,
            json.dumps(
                {
                    "version": 1,
                    "created_at": timestamp(),
                    "state": "filesystem",
                },
                indent=2,
            )
            + "\n",
        )


def copy_runtime_tree(src_parts: tuple[str, ...], destination: Path) -> None:
    src = package_path(*src_parts)
    for item in src.iterdir():
        target = destination / item.name
        if item.is_dir():
            copy_runtime_tree((*src_parts, item.name), target)
            continue
        data = item.read_bytes()
        executable = data.startswith(b"#!")
        write_bytes_atomic(target, data, executable=executable)


def legacy_team_text(agents: list[dict[str, str]]) -> str:
    lines = [
        "# git-agents team file",
        "# Format: <name> <role> <agent> [model]",
        "# The built-in console assistant is started by git agents start, not this file.",
        "",
    ]
    for agent in agents:
        line = f"{agent['name']} {agent['role']} {agent['engine']}"
        if agent.get("model"):
            line += f" {agent['model']}"
        lines.append(line)
    return "\n".join(lines).rstrip() + "\n"


def sync_runtime(repo: Repo) -> None:
    ensure_state(repo)
    copy_runtime_tree(("runtime", "bin"), repo.state_dir / "bin")
    copy_runtime_tree(("runtime", "tools"), repo.state_dir / "tools")

    rules, _rules_source = effective_rules_text(repo)
    write_text_atomic(repo.state_dir / "AGENTS.md", rules)

    roles_dir = repo.state_dir / "roles"
    roles_dir.mkdir(parents=True, exist_ok=True)
    for name in sorted(set(packaged_role_names()) | set(local_role_names(repo))):
        text, _source = effective_role_text(repo, name)
        write_text_atomic(roles_dir / f"{name}.md", text)

    team, _team_source = effective_team(repo)
    write_text_atomic(repo.state_dir / "default.team", legacy_team_text(team))


def pid_is_running(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read_pid(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def list_dirs(path: Path) -> list[str]:
    try:
        return sorted(item.name for item in path.iterdir() if item.is_dir())
    except OSError:
        return []


def print_table(headers: list[str], rows: list[list[Any]]) -> None:
    values = [[str(cell) if cell is not None and str(cell) else "-" for cell in row] for row in rows]
    widths = [len(header) for header in headers]
    for row in values:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))
    print("  ".join(header.ljust(widths[index]) for index, header in enumerate(headers)))
    print("  ".join("-" * width for width in widths))
    for row in values:
        print("  ".join(cell.ljust(widths[index]) for index, cell in enumerate(row)))


def user_path(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else (Path.cwd() / path).resolve()


def run_runtime_tool(repo: Repo, tool: str, args: list[str]) -> int:
    sync_runtime(repo)
    command = [str(repo.state_dir / "bin" / tool), *args]
    proc = subprocess.run(command, cwd=repo.state_dir, check=False)
    return proc.returncode


def required_engine_commands(repo: Repo, no_console: bool) -> dict[str, str]:
    agents, _source = effective_team(repo)
    engines = {agent["engine"] for agent in agents}
    if not no_console:
        engines.add("pi")
    return {engine: ENGINE_COMMAND[engine] for engine in sorted(engines)}


def validate_required_engines(repo: Repo, no_console: bool) -> None:
    missing = [
        command
        for command in required_engine_commands(repo, no_console).values()
        if shutil.which(command) is None
    ]
    if missing:
        raise UserError("required command not found: " + ", ".join(sorted(set(missing))))


def packaged_role_names() -> list[str]:
    base = package_path("templates", "roles")
    return sorted(
        path.name.removesuffix(".md")
        for path in base.iterdir()
        if path.is_file() and path.name.endswith(".md")
    )


def local_role_path(repo: Repo, name: str) -> Path:
    return repo.config_dir / "roles" / f"{name}.md"


def packaged_role_text(name: str) -> str | None:
    path = package_path("templates", "roles", f"{name}.md")
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def effective_role_text(repo: Repo, name: str) -> tuple[str, str]:
    validate_name("role", name)
    local = local_role_path(repo, name)
    if local.is_file():
        return local.read_text(encoding="utf-8"), str(local)
    packaged = packaged_role_text(name)
    if packaged is None:
        raise UserError(f"role not found: {name}")
    return packaged, "package"


def local_role_names(repo: Repo) -> list[str]:
    roles_dir = repo.config_dir / "roles"
    try:
        return sorted(
            path.name.removesuffix(".md")
            for path in roles_dir.iterdir()
            if path.is_file() and path.name.endswith(".md")
        )
    except OSError:
        return []


def materialize_role(repo: Repo, name: str) -> Path:
    text, _source = effective_role_text(repo, name)
    path = local_role_path(repo, name)
    if not path.exists():
        write_text_atomic(path, text)
    return path


def materialize_all_roles(repo: Repo) -> None:
    for name in packaged_role_names():
        materialize_role(repo, name)


def effective_rules_text(repo: Repo) -> tuple[str, str]:
    local = repo.config_dir / "AGENTS.md"
    if local.is_file():
        return local.read_text(encoding="utf-8"), str(local)
    return read_package_text("templates", "AGENTS.md"), "package"


def materialize_rules(repo: Repo) -> Path:
    path = repo.config_dir / "AGENTS.md"
    if not path.exists():
        text, _source = effective_rules_text(repo)
        write_text_atomic(path, text)
    return path


def parse_toml_subset(text: str) -> dict[str, Any]:
    agents: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line == "[[agents]]":
            current = {}
            agents.append(current)
            continue
        if current is None or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] == '"':
            value = value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        current[key.strip()] = value
    return {"agents": agents}


def parse_team_text(text: str) -> list[dict[str, str]]:
    if tomllib is not None:
        data = tomllib.loads(text)
    else:
        data = parse_toml_subset(text)
    agents = data.get("agents", [])
    if not isinstance(agents, list):
        raise UserError("team config must use [[agents]] entries")
    result: list[dict[str, str]] = []
    for index, item in enumerate(agents, start=1):
        if not isinstance(item, dict):
            raise UserError(f"team agent #{index} must be a table")
        name = str(item.get("name", "")).strip()
        role = str(item.get("role", "")).strip()
        engine = str(item.get("engine", "")).strip()
        model = str(item.get("model", "") or "").strip()
        validate_name("agent", name)
        validate_name("role", role)
        if engine not in VALID_ENGINES:
            raise UserError(
                f"invalid engine '{engine}' for agent '{name}': expected "
                + ", ".join(sorted(VALID_ENGINES))
            )
        row = {"name": name, "role": role, "engine": engine}
        if model:
            row["model"] = model
        result.append(row)
    return result


def toml_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def format_team(agents: list[dict[str, str]]) -> str:
    lines = [
        "# git-agents team",
        "# Edit with: git agents team edit",
        "",
    ]
    for agent in agents:
        lines.append("[[agents]]")
        lines.append(f"name = {toml_quote(agent['name'])}")
        lines.append(f"role = {toml_quote(agent['role'])}")
        lines.append(f"engine = {toml_quote(agent['engine'])}")
        if agent.get("model"):
            lines.append(f"model = {toml_quote(agent['model'])}")
        lines.append("")
    return "\n".join(lines)


def effective_team_text(repo: Repo) -> tuple[str, str]:
    local = repo.config_dir / "team.toml"
    if local.is_file():
        return local.read_text(encoding="utf-8"), str(local)
    return read_package_text("templates", "team.toml"), "package"


def effective_team(repo: Repo) -> tuple[list[dict[str, str]], str]:
    text, source = effective_team_text(repo)
    return parse_team_text(text), source


def materialize_team(repo: Repo) -> Path:
    path = repo.config_dir / "team.toml"
    if not path.exists():
        text, _source = effective_team_text(repo)
        write_text_atomic(path, text)
    return path


def write_local_team(repo: Repo, agents: list[dict[str, str]]) -> None:
    path = repo.config_dir / "team.toml"
    write_text_atomic(path, format_team(agents))


def first_markdown_title(markdown: str, fallback: str) -> str:
    for line in markdown.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            if title:
                return title
    return fallback


def iso_mtime(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat().replace("+00:00", "Z")
    except OSError:
        return ""


def task_records(repo: Repo) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for task_id in list_dirs(repo.state_dir / "tasks"):
        task_dir = repo.state_dir / "tasks" / task_id
        spec = read_text(task_dir / "spec.md")
        records.append(
            {
                "id": task_id,
                "state": read_text(task_dir / "state", "open", 1024).strip() or "open",
                "title": first_markdown_title(spec, task_id),
                "updated": iso_mtime(task_dir),
            }
        )
    return records


def job_records(repo: Repo) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for job_id in list_dirs(repo.state_dir / "jobs"):
        job_dir = repo.state_dir / "jobs" / job_id
        records.append(
            {
                "id": job_id,
                "status": read_text(job_dir / "status", "unknown", 1024).strip() or "unknown",
                "task_id": read_text(job_dir / "task-id", "", 1024).strip(),
                "role": read_text(job_dir / "role", "", 1024).strip(),
                "agent_id": read_text(job_dir / "agent-id", "", 1024).strip(),
            }
        )
    return records


def agent_records(repo: Repo) -> list[dict[str, Any]]:
    jobs = job_records(repo)
    records: list[dict[str, Any]] = []
    for agent_id in list_dirs(repo.state_dir / "agents"):
        if agent_id.startswith("."):
            continue
        agent_dir = repo.state_dir / "agents" / agent_id
        runner_pid = read_pid(agent_dir / "runner.pid")
        engine_pid = read_pid(agent_dir / "engine.pid")
        active_jobs = [
            job["id"]
            for job in jobs
            if job.get("agent_id") == agent_id and job.get("status") in {"claimed", "running"}
        ]
        records.append(
            {
                "id": agent_id,
                "role": read_text(agent_dir / "role", "", 1024).strip(),
                "engine": read_text(agent_dir / "engine", "", 1024).strip(),
                "current_job": read_text(agent_dir / "current-job", "", 1024).strip(),
                "runner_pid": runner_pid,
                "engine_pid": engine_pid,
                "running": pid_is_running(runner_pid) or pid_is_running(engine_pid),
                "active_jobs": active_jobs,
            }
        )
    return records


def status_data(repo: Repo) -> dict[str, Any]:
    tasks = task_records(repo) if (repo.state_dir / "tasks").is_dir() else []
    jobs = job_records(repo) if (repo.state_dir / "jobs").is_dir() else []
    supervisor_pid = read_pid(repo.state_dir / "runs" / "supervisor.pid")
    server_path = repo.state_dir / "runs" / "server.json"
    server: dict[str, Any] = {}
    try:
        server = json.loads(server_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        server = {}
    server_pid = int(server.get("pid") or 0)
    if not pid_is_running(server_pid):
        server = {}
    return {
        "repo_root": str(repo.root),
        "git_dir": str(repo.git_dir),
        "state_dir": str(repo.state_dir),
        "config_dir": str(repo.config_dir),
        "initialized": repo.state_dir.is_dir(),
        "supervisor_pid": supervisor_pid,
        "supervisor_running": pid_is_running(supervisor_pid),
        "server_url": server.get("url", ""),
        "task_count": len(tasks),
        "job_count": len(jobs),
        "failed_job_count": sum(1 for job in jobs if job.get("status") == "failed"),
    }


def cmd_init(args: argparse.Namespace) -> int:
    repo = discover_repo()
    sync_runtime(repo)
    if args.tracked_config:
        materialize_rules(repo)
        materialize_all_roles(repo)
        materialize_team(repo)
        (repo.config_dir / "specs").mkdir(parents=True, exist_ok=True)
    print(f"Initialized git agents state: {repo.state_dir}")
    if args.tracked_config:
        print(f"Materialized tracked config: {repo.config_dir}")
    return 0


def cmd_status(_args: argparse.Namespace) -> int:
    repo = discover_repo()
    data = status_data(repo)
    rows = [
        ["initialized", data["initialized"]],
        ["supervisor", "running" if data["supervisor_running"] else "stopped"],
        ["supervisor_pid", data["supervisor_pid"] or ""],
        ["web", data["server_url"]],
        ["tasks", data["task_count"]],
        ["jobs", data["job_count"]],
        ["failed_jobs", data["failed_job_count"]],
        ["state", data["state_dir"]],
        ["config", data["config_dir"]],
    ]
    print_table(["field", "value"], rows)
    return 0


def cmd_role_list(_args: argparse.Namespace) -> int:
    repo = discover_repo()
    names = sorted(set(packaged_role_names()) | set(local_role_names(repo)))
    rows: list[list[str]] = []
    for name in names:
        local = local_role_path(repo, name)
        packaged = packaged_role_text(name)
        if local.is_file():
            source = "local"
            changed = "yes" if packaged is not None and local.read_text(encoding="utf-8") != packaged else "no"
        else:
            source = "package"
            changed = "no"
        rows.append([name, source, changed])
    print_table(["role", "source", "changed"], rows)
    return 0


def cmd_role_show(args: argparse.Namespace) -> int:
    repo = discover_repo()
    text, _source = effective_role_text(repo, args.name)
    print(text, end="" if text.endswith("\n") else "\n")
    return 0


def cmd_role_add(args: argparse.Namespace) -> int:
    repo = discover_repo()
    validate_name("role", args.name)
    path = local_role_path(repo, args.name)
    if path.exists():
        raise UserError(f"role already exists: {args.name}")
    if args.from_role:
        text, _source = effective_role_text(repo, args.from_role)
        text = text.replace(f"# {args.from_role.title()}", f"# {args.name.title()}", 1)
    else:
        text = f"# {args.name.title()}\n\nDescribe the {args.name} role here.\n"
    write_text_atomic(path, text)
    print(path)
    return 0


def cmd_role_edit(args: argparse.Namespace) -> int:
    repo = discover_repo()
    path = materialize_role(repo, args.name)
    editor = os.environ.get("EDITOR")
    if not editor:
        print(path)
        print("Set EDITOR to open this file automatically.", file=sys.stderr)
        return 0
    proc = subprocess.run([*shlex.split(editor), str(path)], check=False)
    return proc.returncode


def cmd_role_diff(args: argparse.Namespace) -> int:
    repo = discover_repo()
    names = [args.name] if args.name else sorted(set(packaged_role_names()) | set(local_role_names(repo)))
    emitted = False
    for name in names:
        validate_name("role", name)
        local = local_role_path(repo, name)
        packaged = packaged_role_text(name)
        if not local.exists():
            continue
        if packaged is None:
            packaged = ""
        diff = difflib.unified_diff(
            packaged.splitlines(keepends=True),
            local.read_text(encoding="utf-8").splitlines(keepends=True),
            fromfile=f"package/{name}.md",
            tofile=str(local),
        )
        for line in diff:
            print(line, end="")
            emitted = True
    if not emitted and args.name:
        print(f"role {args.name} has no local changes")
    return 0


def cmd_role_reset(args: argparse.Namespace) -> int:
    repo = discover_repo()
    validate_name("role", args.name)
    packaged = packaged_role_text(args.name)
    if packaged is None:
        raise UserError(f"package role not found: {args.name}")
    path = local_role_path(repo, args.name)
    if path.exists() and not args.yes:
        if not sys.stdin.isatty():
            raise UserError("refusing to overwrite role without --yes")
        answer = input(f"Reset {path}? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            return 1
    write_text_atomic(path, packaged)
    print(path)
    return 0


def cmd_rules_show(_args: argparse.Namespace) -> int:
    repo = discover_repo()
    text, _source = effective_rules_text(repo)
    print(text, end="" if text.endswith("\n") else "\n")
    return 0


def cmd_rules_edit(_args: argparse.Namespace) -> int:
    repo = discover_repo()
    path = materialize_rules(repo)
    editor = os.environ.get("EDITOR")
    if not editor:
        print(path)
        print("Set EDITOR to open this file automatically.", file=sys.stderr)
        return 0
    proc = subprocess.run([*shlex.split(editor), str(path)], check=False)
    return proc.returncode


def cmd_rules_reset(args: argparse.Namespace) -> int:
    repo = discover_repo()
    path = repo.config_dir / "AGENTS.md"
    if path.exists() and not args.yes:
        if not sys.stdin.isatty():
            raise UserError("refusing to overwrite rules without --yes")
        answer = input(f"Reset {path}? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            return 1
    write_text_atomic(path, read_package_text("templates", "AGENTS.md"))
    print(path)
    return 0


def cmd_team_list(_args: argparse.Namespace) -> int:
    repo = discover_repo()
    agents, source = effective_team(repo)
    rows = []
    run_dir = repo.state_dir / "agents" / ".team-runs"
    for agent in agents:
        pid = read_pid(run_dir / f"{agent['name']}.pid")
        last_status = read_text(run_dir / f"{agent['name']}.last-status", "", 1024).strip()
        if pid_is_running(pid):
            state = "running"
        elif last_status and last_status != "0":
            state = "failed"
        else:
            state = "stopped"
        rows.append(
            [
                agent["name"],
                agent["role"],
                agent["engine"],
                agent.get("model", ""),
                state,
                source,
            ]
        )
    print_table(["agent", "role", "engine", "model", "state", "source"], rows)
    return 0


def cmd_team_show(args: argparse.Namespace) -> int:
    repo = discover_repo()
    text, source = effective_team_text(repo)
    if not args.agent:
        print(text, end="" if text.endswith("\n") else "\n")
        return 0
    agents = parse_team_text(text)
    for agent in agents:
        if agent["name"] == args.agent:
            print(json.dumps({"source": source, **agent}, indent=2) + "\n")
            return 0
    raise UserError(f"agent not found in team: {args.agent}")


def cmd_team_add(args: argparse.Namespace) -> int:
    repo = discover_repo()
    validate_name("agent", args.agent)
    validate_name("role", args.role)
    if args.engine not in VALID_ENGINES:
        raise UserError(f"invalid engine '{args.engine}': expected " + ", ".join(sorted(VALID_ENGINES)))
    materialize_team(repo)
    agents, _source = effective_team(repo)
    if any(agent["name"] == args.agent for agent in agents):
        raise UserError(f"agent already exists: {args.agent}")
    row = {"name": args.agent, "role": args.role, "engine": args.engine}
    if args.model:
        row["model"] = args.model
    agents.append(row)
    write_local_team(repo, agents)
    print(repo.config_dir / "team.toml")
    return 0


def cmd_team_remove(args: argparse.Namespace) -> int:
    repo = discover_repo()
    materialize_team(repo)
    agents, _source = effective_team(repo)
    kept = [agent for agent in agents if agent["name"] != args.agent]
    if len(kept) == len(agents):
        raise UserError(f"agent not found in team: {args.agent}")
    write_local_team(repo, kept)
    print(repo.config_dir / "team.toml")
    return 0


def cmd_team_set(args: argparse.Namespace) -> int:
    repo = discover_repo()
    materialize_team(repo)
    agents, _source = effective_team(repo)
    found = False
    for agent in agents:
        if agent["name"] != args.agent:
            continue
        found = True
        if args.role:
            validate_name("role", args.role)
            agent["role"] = args.role
        if args.engine:
            if args.engine not in VALID_ENGINES:
                raise UserError(f"invalid engine '{args.engine}': expected " + ", ".join(sorted(VALID_ENGINES)))
            agent["engine"] = args.engine
        if args.model is not None:
            if args.model:
                agent["model"] = args.model
            else:
                agent.pop("model", None)
    if not found:
        raise UserError(f"agent not found in team: {args.agent}")
    if not any([args.role, args.engine, args.model is not None]):
        raise UserError("team set requires --role, --engine, or --model")
    write_local_team(repo, agents)
    print(repo.config_dir / "team.toml")
    return 0


def cmd_team_edit(_args: argparse.Namespace) -> int:
    repo = discover_repo()
    path = materialize_team(repo)
    editor = os.environ.get("EDITOR")
    if not editor:
        print(path)
        print("Set EDITOR to open this file automatically.", file=sys.stderr)
        return 0
    proc = subprocess.run([*shlex.split(editor), str(path)], check=False)
    return proc.returncode


def cmd_tasks_list(_args: argparse.Namespace) -> int:
    repo = discover_repo()
    rows = [[task["id"], task["state"], task["title"], task["updated"]] for task in task_records(repo)]
    print_table(["task", "state", "title", "updated"], rows)
    return 0


def cmd_tasks_create(args: argparse.Namespace) -> int:
    repo = discover_repo()
    validate_name("task", args.task)
    return run_runtime_tool(repo, "task-create", [args.task, str(user_path(args.spec_file))])


def cmd_tasks_show(args: argparse.Namespace) -> int:
    repo = discover_repo()
    validate_name("task", args.task)
    task_dir = repo.state_dir / "tasks" / args.task
    if not task_dir.is_dir():
        raise UserError(f"task not found: {args.task}")
    print(f"task: {args.task}")
    print(f"state: {read_text(task_dir / 'state', 'open', 1024).strip() or 'open'}")
    for name in ("spec.md", "log.md", "result.md"):
        path = task_dir / name
        if path.is_file():
            print(f"\n## {name}\n")
            print(read_text(path), end="")
    return 0


def cmd_tasks_comment(args: argparse.Namespace) -> int:
    repo = discover_repo()
    validate_name("task", args.task)
    message = " ".join(args.message)
    if not message:
        raise UserError("message required")
    return run_runtime_tool(repo, "task-comment", [args.task, message])


def cmd_tasks_state(args: argparse.Namespace) -> int:
    repo = discover_repo()
    validate_name("task", args.task)
    command = [args.task, args.state]
    if args.message:
        command.extend(["-m", args.message])
    return run_runtime_tool(repo, "task-state", command)


def cmd_tasks_result(args: argparse.Namespace) -> int:
    repo = discover_repo()
    validate_name("task", args.task)
    return run_runtime_tool(repo, "task-result", [args.task, str(user_path(args.result_file))])


def cmd_jobs_list(_args: argparse.Namespace) -> int:
    repo = discover_repo()
    rows = [
        [job["id"], job["status"], job["role"], job["task_id"], job["agent_id"]]
        for job in job_records(repo)
    ]
    print_table(["job", "status", "role", "task", "agent"], rows)
    return 0


def cmd_jobs_create(args: argparse.Namespace) -> int:
    repo = discover_repo()
    validate_name("job", args.job)
    validate_name("role", args.role)
    validate_name("task", args.task)
    return run_runtime_tool(
        repo,
        "job-create",
        [args.job, "-r", args.role, "-t", args.task, str(user_path(args.spec_file))],
    )


def cmd_jobs_reset(args: argparse.Namespace) -> int:
    repo = discover_repo()
    validate_name("job", args.job)
    command = [args.job]
    if args.message:
        command.extend(["-m", args.message])
    if args.force:
        command.append("--force")
    return run_runtime_tool(repo, "job-reset", command)


def cmd_jobs_kill(args: argparse.Namespace) -> int:
    repo = discover_repo()
    validate_name("job", args.job)
    command = [args.job]
    if args.message:
        command.extend(["-m", args.message])
    if args.force:
        command.append("--force")
    return run_runtime_tool(repo, "job-kill", command)


def cmd_jobs_orphans(_args: argparse.Namespace) -> int:
    repo = discover_repo()
    return run_runtime_tool(repo, "job-orphans", [])


def cmd_jobs_reset_orphans(_args: argparse.Namespace) -> int:
    repo = discover_repo()
    return run_runtime_tool(repo, "job-reset-orphans", [])


def cmd_jobs_reap(args: argparse.Namespace) -> int:
    repo = discover_repo()
    command = [str(args.minutes)] if args.minutes is not None else []
    return run_runtime_tool(repo, "job-reap", command)


def terminate_recorded_agent_processes(agent_dir: Path) -> int:
    signaled = 0
    engine_pid = read_pid(agent_dir / "engine.pid")
    runner_pid = read_pid(agent_dir / "runner.pid")

    if engine_pid and engine_pid != os.getpid():
        try:
            os.killpg(engine_pid, signal.SIGTERM)
            signaled += 1
        except ProcessLookupError:
            try:
                os.kill(engine_pid, signal.SIGTERM)
                signaled += 1
            except ProcessLookupError:
                pass
            except PermissionError as exc:
                raise UserError(f"cannot signal engine pid {engine_pid}: {exc}") from exc
        except PermissionError:
            try:
                os.kill(engine_pid, signal.SIGTERM)
                signaled += 1
            except ProcessLookupError:
                pass
            except PermissionError as exc:
                raise UserError(f"cannot signal engine pid {engine_pid}: {exc}") from exc

    if runner_pid and runner_pid != os.getpid():
        try:
            os.kill(runner_pid, signal.SIGTERM)
            signaled += 1
        except ProcessLookupError:
            pass
        except PermissionError as exc:
            raise UserError(f"cannot signal runner pid {runner_pid}: {exc}") from exc

    deadline = time.time() + 3
    while time.time() < deadline:
        if not (pid_is_running(engine_pid) or pid_is_running(runner_pid)):
            return signaled
        time.sleep(0.1)

    if engine_pid and pid_is_running(engine_pid):
        try:
            os.killpg(engine_pid, signal.SIGKILL)
        except ProcessLookupError:
            try:
                os.kill(engine_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except PermissionError as exc:
                raise UserError(f"cannot kill engine pid {engine_pid}: {exc}") from exc
        except PermissionError:
            try:
                os.kill(engine_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except PermissionError as exc:
                raise UserError(f"cannot kill engine pid {engine_pid}: {exc}") from exc
    if runner_pid and pid_is_running(runner_pid):
        try:
            os.kill(runner_pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except PermissionError as exc:
            raise UserError(f"cannot kill runner pid {runner_pid}: {exc}") from exc

    return signaled


def clear_agent_runtime_files(agent_dir: Path) -> None:
    for name in ("engine.pid", "runner.pid", "busy"):
        try:
            (agent_dir / name).unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass

    fifo = agent_dir / "input.fifo"
    try:
        if fifo.is_fifo():
            fifo.unlink()
    except OSError:
        pass


def cmd_agents_list(_args: argparse.Namespace) -> int:
    repo = discover_repo()
    rows = []
    for agent in agent_records(repo):
        if agent["running"] and agent["active_jobs"]:
            state = "busy"
        elif agent["running"]:
            state = "running"
        else:
            state = "stopped"
        rows.append(
            [
                agent["id"],
                agent["role"],
                agent["engine"],
                agent["current_job"],
                ",".join(agent["active_jobs"]),
                state,
            ]
        )
    print_table(["agent", "role", "engine", "current", "active_jobs", "state"], rows)
    return 0


def cmd_agents_reset(args: argparse.Namespace) -> int:
    repo = discover_repo()
    sync_runtime(repo)
    validate_name("agent", args.agent)

    agent_dir = repo.state_dir / "agents" / args.agent
    if not agent_dir.is_dir():
        raise UserError(f"agent not found: {args.agent}")

    message = args.message or f"Agent {args.agent} reset."
    reset_count = 0
    for job in job_records(repo):
        if job.get("agent_id") != args.agent or job.get("status") not in {"claimed", "running"}:
            continue
        command = [job["id"], "-m", message]
        if args.force:
            command.append("--force")
        rc = run_runtime_tool(repo, "job-reset", command)
        if rc != 0:
            return rc
        reset_count += 1

    signaled = 0
    if not args.no_kill:
        signaled = terminate_recorded_agent_processes(agent_dir)

    write_text_atomic(agent_dir / "current-job", "")
    clear_agent_runtime_files(agent_dir)
    print(f"reset agent {args.agent}: jobs reset={reset_count}, processes signaled={signaled}")
    return 0


def stop_supervisor(repo: Repo, quiet: bool = False) -> int:
    pid_file = repo.state_dir / "runs" / "supervisor.pid"
    pid = read_pid(pid_file)
    if not pid_is_running(pid):
        try:
            pid_file.unlink()
        except OSError:
            pass
        if not quiet:
            print("git agents supervisor is not running")
        return 0
    assert pid is not None
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    except PermissionError as exc:
        raise UserError(f"cannot stop supervisor pid {pid}: {exc}") from exc
    deadline = time.time() + 5
    while time.time() < deadline and pid_is_running(pid):
        time.sleep(0.1)
    if pid_is_running(pid):
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        pid_file.unlink()
    except OSError:
        pass
    if not quiet:
        print(f"stopped git agents supervisor pid={pid}")
    return 0


def start_supervisor(repo: Repo, no_console: bool, restart: bool = False) -> int:
    validate_required_engines(repo, no_console)
    sync_runtime(repo)
    pid_file = repo.state_dir / "runs" / "supervisor.pid"
    existing = read_pid(pid_file)
    if pid_is_running(existing):
        if not restart:
            raise UserError(f"git agents supervisor is already running pid={existing}")
        stop_supervisor(repo, quiet=True)
    log_path = repo.state_dir / "logs" / "supervisor.log"
    command = [
        sys.executable,
        "-m",
        "git_agents.cli",
        "_supervisor",
        "--repo-root",
        str(repo.root),
        "--state-dir",
        str(repo.state_dir),
    ]
    if no_console:
        command.append("--no-console")
    with log_path.open("ab") as log:
        proc = subprocess.Popen(
            command,
            cwd=repo.root,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    time.sleep(0.2)
    if proc.poll() is not None:
        raise UserError(f"supervisor exited early; see {log_path}")
    write_text_atomic(pid_file, f"{proc.pid}\n")
    print(f"started git agents supervisor pid={proc.pid}")
    return 0


def cmd_start(args: argparse.Namespace) -> int:
    repo = discover_repo()
    return start_supervisor(repo, no_console=args.no_console, restart=args.restart)


def cmd_stop(_args: argparse.Namespace) -> int:
    repo = discover_repo()
    return stop_supervisor(repo)


def cmd_restart(args: argparse.Namespace) -> int:
    repo = discover_repo()
    ensure_state(repo)
    stop_supervisor(repo, quiet=True)
    return start_supervisor(repo, no_console=args.no_console, restart=False)


def cmd_supervisor(args: argparse.Namespace) -> int:
    root = Path(args.repo_root).resolve()
    state_dir = Path(args.state_dir).resolve()
    for name in STATE_SUBDIRS:
        (state_dir / name).mkdir(parents=True, exist_ok=True)
    pid = os.getpid()
    write_text_atomic(state_dir / "runs" / "supervisor.pid", f"{pid}\n")
    write_text_atomic(
        state_dir / "runs" / "supervisor.json",
        json.dumps(
            {
                "pid": pid,
                "repo_root": str(root),
                "started_at": timestamp(),
                "no_console": bool(args.no_console),
                "runtime_root": str(state_dir),
            },
            indent=2,
        )
        + "\n",
    )
    stopping = False
    children: list[subprocess.Popen[bytes]] = []

    def request_stop(_signum: int, _frame: Any) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    def launch(label: str, command: list[str]) -> subprocess.Popen[bytes]:
        log_path = state_dir / "logs" / f"{label}.log"
        log = log_path.open("ab")
        env = os.environ.copy()
        env["GIT_AGENTS_REPO_ROOT"] = str(root)
        env["GIT_AGENTS_STATE_DIR"] = str(state_dir)
        try:
            proc = subprocess.Popen(
                command,
                cwd=state_dir,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                env=env,
            )
        finally:
            log.close()
        print(f"{timestamp()} started {label} pid={proc.pid}", flush=True)
        return proc

    def terminate(proc: subprocess.Popen[bytes]) -> None:
        if proc.poll() is not None:
            return
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                return
            proc.wait(timeout=5)

    print(f"{timestamp()} supervisor started for {root}", flush=True)
    try:
        if not args.no_console:
            children.append(
                launch(
                    "console",
                    [str(state_dir / "tools" / "agent-pi-interactive"), "--console", "--headless"],
                )
            )
        else:
            print(f"{timestamp()} console disabled", flush=True)

        children.append(launch("team", [str(state_dir / "tools" / "run_git_agents")]))

        while not stopping:
            write_text_atomic(state_dir / "runs" / "supervisor-heartbeat", timestamp() + "\n")
            for index, proc in enumerate(list(children)):
                rc = proc.poll()
                if rc is None:
                    continue
                label = "console" if index == 0 and not args.no_console else "team"
                print(f"{timestamp()} {label} exited rc={rc}; restarting", flush=True)
                if label == "console":
                    children[index] = launch(
                        "console",
                        [str(state_dir / "tools" / "agent-pi-interactive"), "--console", "--headless"],
                    )
                else:
                    children[index] = launch("team", [str(state_dir / "tools" / "run_git_agents")])
            time.sleep(1)
    finally:
        print(f"{timestamp()} supervisor stopping", flush=True)
        for proc in reversed(children):
            terminate(proc)
        try:
            (state_dir / "runs" / "supervisor.pid").unlink()
        except OSError:
            pass
    return 0


def cmd_log(args: argparse.Namespace) -> int:
    repo = discover_repo()
    validate_name("agent", args.agent)
    path = repo.state_dir / "agents" / args.agent / "transcript.log"
    if not path.is_file():
        raise UserError(f"transcript not found: {path}")
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        print(stream.read(), end="")
        if not args.follow:
            return 0
        while True:
            chunk = stream.read()
            if chunk:
                print(chunk, end="")
                sys.stdout.flush()
            time.sleep(0.5)


def read_flag(path: Path) -> str:
    return read_text(path, "", 1024).strip()


def follow_console_turn(console_dir: Path, transcript_path: Path, start_offset: int) -> None:
    busy_path = console_dir / "busy"
    saw_activity = False
    emitted_output = False
    output_ended_with_newline = True
    idle_since: float | None = None
    deadline = time.time() + 10
    with transcript_path.open("r", encoding="utf-8", errors="replace") as stream:
        stream.seek(start_offset)
        while True:
            chunk = stream.read()
            if chunk:
                saw_activity = True
                emitted_output = True
                output_ended_with_newline = chunk.endswith("\n")
                idle_since = None
                print(chunk, end="")
                sys.stdout.flush()

            busy = read_flag(busy_path)
            if busy == "1":
                saw_activity = True
                idle_since = None
            elif saw_activity:
                idle_since = idle_since or time.time()
                if time.time() - idle_since >= 0.4:
                    break
            elif time.time() > deadline:
                raise UserError("timed out waiting for console output")

            time.sleep(0.1)
    if emitted_output and not output_ended_with_newline:
        print()


def cmd_prompt(args: argparse.Namespace) -> int:
    repo = discover_repo()
    ensure_state(repo)
    if args.message:
        message = " ".join(args.message)
    elif not sys.stdin.isatty():
        message = sys.stdin.read()
    else:
        raise UserError("prompt requires a message argument or stdin")
    console_dir = repo.state_dir / "agents" / "console"
    fifo = console_dir / "input.fifo"
    if not fifo.exists():
        raise UserError("console agent is not running")
    transcript = console_dir / "transcript.log"
    transcript_offset = transcript.stat().st_size if transcript.exists() else 0
    try:
        fd = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
    except OSError as exc:
        raise UserError(f"console agent is not accepting input: {exc}") from exc
    try:
        payload = json.dumps({"message": message.rstrip(), "mode": "prompt"}) + "\n"
        os.write(fd, payload.encode("utf-8"))
    finally:
        os.close(fd)
    if not args.quiet:
        transcript.touch()
        follow_console_turn(console_dir, transcript, transcript_offset)
    return 0


def json_response(handler: BaseHTTPRequestHandler, status: int, payload: Any) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def static_response(handler: BaseHTTPRequestHandler, name: str) -> None:
    path = package_path("web", name)
    if not path.is_file():
        handler.send_error(404)
        return
    body = path.read_bytes()
    handler.send_response(200)
    handler.send_header("Content-Type", mimetypes.guess_type(name)[0] or "application/octet-stream")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def bind_server(host: str, port: int, handler_type):
    attempts = 1 if port == 0 else 100
    last_error: OSError | None = None
    for offset in range(attempts):
        candidate = port + offset if port else 0
        try:
            return ThreadingHTTPServer((host, candidate), handler_type)
        except OSError as exc:
            last_error = exc
            if exc.errno == errno.EADDRINUSE and offset + 1 < attempts:
                continue
            break
    raise UserError(f"cannot bind {host}:{port}: {last_error}")


def server_url(server: ThreadingHTTPServer, host: str) -> str:
    public_host = host
    if public_host in {"", "0.0.0.0", "::"}:
        public_host = "127.0.0.1"
    if ":" in public_host and not public_host.startswith("["):
        public_host = f"[{public_host}]"
    return f"http://{public_host}:{server.server_address[1]}"


def cmd_serve(args: argparse.Namespace) -> int:
    repo = discover_repo()
    sync_runtime(repo)
    command = [
        str(repo.state_dir / "tools" / "git-agents-ui"),
        "--root",
        str(repo.state_dir),
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--no-team",
        "--no-console",
    ]
    proc = subprocess.run(command, cwd=repo.state_dir, check=False)
    return proc.returncode


def cmd_spec_build(_args: argparse.Namespace) -> int:
    raise UserError("spec build is not implemented yet", 2)


def add_role_parser(subparsers: argparse._SubParsersAction) -> None:
    role = subparsers.add_parser("role", help="manage roles")
    role_sub = role.add_subparsers(dest="role_command", required=True)
    role_sub.add_parser("list", help="list roles").set_defaults(func=cmd_role_list)
    show = role_sub.add_parser("show", help="show effective role text")
    show.add_argument("name")
    show.set_defaults(func=cmd_role_show)
    add = role_sub.add_parser("add", help="add a local role")
    add.add_argument("name")
    add.add_argument("--from", dest="from_role")
    add.set_defaults(func=cmd_role_add)
    edit = role_sub.add_parser("edit", help="edit a local role")
    edit.add_argument("name")
    edit.set_defaults(func=cmd_role_edit)
    diff = role_sub.add_parser("diff", help="diff local roles against package templates")
    diff.add_argument("name", nargs="?")
    diff.set_defaults(func=cmd_role_diff)
    reset = role_sub.add_parser("reset", help="reset a role from the package template")
    reset.add_argument("name")
    reset.add_argument("--yes", action="store_true")
    reset.set_defaults(func=cmd_role_reset)


def add_rules_parser(subparsers: argparse._SubParsersAction) -> None:
    rules = subparsers.add_parser("rules", help="manage generic agent rules")
    rules_sub = rules.add_subparsers(dest="rules_command", required=True)
    rules_sub.add_parser("show", help="show effective generic rules").set_defaults(func=cmd_rules_show)
    rules_sub.add_parser("edit", help="edit local generic rules").set_defaults(func=cmd_rules_edit)
    reset = rules_sub.add_parser("reset", help="reset generic rules from the package template")
    reset.add_argument("--yes", action="store_true")
    reset.set_defaults(func=cmd_rules_reset)


def add_team_parser(subparsers: argparse._SubParsersAction) -> None:
    team = subparsers.add_parser("team", help="manage the configured team")
    team_sub = team.add_subparsers(dest="team_command", required=True)
    team_sub.add_parser("list", help="list configured agents").set_defaults(func=cmd_team_list)
    show = team_sub.add_parser("show", help="show team config or one agent")
    show.add_argument("agent", nargs="?")
    show.set_defaults(func=cmd_team_show)
    add = team_sub.add_parser("add", help="add a configured agent")
    add.add_argument("agent")
    add.add_argument("--role", required=True)
    add.add_argument("--engine", choices=sorted(VALID_ENGINES), default="codex")
    add.add_argument("--model")
    add.set_defaults(func=cmd_team_add)
    remove = team_sub.add_parser("remove", help="remove a configured agent")
    remove.add_argument("agent")
    remove.set_defaults(func=cmd_team_remove)
    set_cmd = team_sub.add_parser("set", help="update a configured agent")
    set_cmd.add_argument("agent")
    set_cmd.add_argument("--role")
    set_cmd.add_argument("--engine", choices=sorted(VALID_ENGINES))
    set_cmd.add_argument("--model")
    set_cmd.set_defaults(func=cmd_team_set)
    team_sub.add_parser("edit", help="edit the team config").set_defaults(func=cmd_team_edit)


def add_tasks_parser(subparsers: argparse._SubParsersAction) -> None:
    tasks = subparsers.add_parser("tasks", help="inspect tasks")
    tasks_sub = tasks.add_subparsers(dest="tasks_command", required=True)
    create = tasks_sub.add_parser("create", help="create a task and initial planner job")
    create.add_argument("task")
    create.add_argument("spec_file")
    create.set_defaults(func=cmd_tasks_create)
    tasks_sub.add_parser("list", help="list tasks").set_defaults(func=cmd_tasks_list)
    show = tasks_sub.add_parser("show", help="show a task")
    show.add_argument("task")
    show.set_defaults(func=cmd_tasks_show)
    comment = tasks_sub.add_parser("comment", help="append a task comment")
    comment.add_argument("task")
    comment.add_argument("message", nargs="+")
    comment.set_defaults(func=cmd_tasks_comment)
    state = tasks_sub.add_parser("state", help="set task state")
    state.add_argument("task")
    state.add_argument("state", choices=["open", "done"])
    state.add_argument("-m", "--message")
    state.set_defaults(func=cmd_tasks_state)
    result = tasks_sub.add_parser("result", help="record task result and mark done")
    result.add_argument("task")
    result.add_argument("result_file")
    result.set_defaults(func=cmd_tasks_result)


def add_jobs_parser(subparsers: argparse._SubParsersAction) -> None:
    jobs = subparsers.add_parser("jobs", help="inspect and recover jobs")
    jobs_sub = jobs.add_subparsers(dest="jobs_command", required=True)
    create = jobs_sub.add_parser("create", help="create a job")
    create.add_argument("job")
    create.add_argument("--role", required=True)
    create.add_argument("--task", required=True)
    create.add_argument("spec_file")
    create.set_defaults(func=cmd_jobs_create)
    jobs_sub.add_parser("list", help="list jobs").set_defaults(func=cmd_jobs_list)
    reset = jobs_sub.add_parser("reset", help="force a job back to pending")
    reset.add_argument("job")
    reset.add_argument("-m", "--message")
    reset.add_argument("--force", action="store_true", help="allow completed jobs and non-empty locks")
    reset.set_defaults(func=cmd_jobs_reset)
    kill = jobs_sub.add_parser("kill", help="stop a claimed or running job immediately")
    kill.add_argument("job")
    kill.add_argument("-m", "--message")
    kill.add_argument("--force", action="store_true", help="allow removing a non-empty lock")
    kill.set_defaults(func=cmd_jobs_kill)
    jobs_sub.add_parser("orphans", help="list claimed/running jobs with missing owners").set_defaults(func=cmd_jobs_orphans)
    jobs_sub.add_parser("reset-orphans", help="reset orphaned jobs to pending").set_defaults(func=cmd_jobs_reset_orphans)
    reap = jobs_sub.add_parser("reap", help="reset stale locked jobs")
    reap.add_argument("minutes", nargs="?", type=int)
    reap.set_defaults(func=cmd_jobs_reap)


def add_agents_parser(subparsers: argparse._SubParsersAction) -> None:
    agents = subparsers.add_parser("agents", help="inspect and recover runtime agents")
    agents_sub = agents.add_subparsers(dest="agents_command", required=True)
    agents_sub.add_parser("list", help="list runtime agents").set_defaults(func=cmd_agents_list)
    reset = agents_sub.add_parser("reset", help="reset one runtime agent")
    reset.add_argument("agent")
    reset.add_argument("-m", "--message")
    reset.add_argument("--force", action="store_true", help="force resetting non-empty job locks")
    reset.add_argument("--no-kill", action="store_true", help="clear state without signaling recorded processes")
    reset.set_defaults(func=cmd_agents_reset)


def add_spec_parser(subparsers: argparse._SubParsersAction) -> None:
    spec = subparsers.add_parser("spec", help="spec workflows")
    spec_sub = spec.add_subparsers(dest="spec_command", required=True)
    spec_sub.add_parser("build", help="build a task spec").set_defaults(func=cmd_spec_build)


def build_parser(include_internal: bool = False) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="git agents")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name in ("init", "install"):
        init = subparsers.add_parser(name, help="initialize repository state")
        init.add_argument("--tracked-config", action="store_true", help="materialize .git-agents config files")
        init.set_defaults(func=cmd_init)

    start = subparsers.add_parser("start", help="start the agent supervisor")
    start.add_argument("--restart", action="store_true")
    start.add_argument("--no-console", action="store_true")
    start.set_defaults(func=cmd_start)

    subparsers.add_parser("stop", help="stop the agent supervisor").set_defaults(func=cmd_stop)
    restart = subparsers.add_parser("restart", help="restart the agent supervisor")
    restart.add_argument("--no-console", action="store_true")
    restart.set_defaults(func=cmd_restart)
    subparsers.add_parser("status", help="show repository agent status").set_defaults(func=cmd_status)

    serve = subparsers.add_parser("serve", help="serve the web UI in the foreground")
    serve.add_argument("--host", default=os.environ.get("HOST", DEFAULT_HOST))
    serve.add_argument("--port", type=int, default=int(os.environ.get("PORT", DEFAULT_PORT)))
    serve.set_defaults(func=cmd_serve)

    log = subparsers.add_parser("log", help="show an agent transcript")
    log.add_argument("-f", "--follow", action="store_true")
    log.add_argument("agent", nargs="?", default="console")
    log.set_defaults(func=cmd_log)

    prompt = subparsers.add_parser("prompt", help="send input to the console agent")
    prompt.add_argument("-q", "--quiet", action="store_true", help="send the prompt without printing the console turn")
    prompt.add_argument("message", nargs="*")
    prompt.set_defaults(func=cmd_prompt)

    add_role_parser(subparsers)
    add_rules_parser(subparsers)
    add_team_parser(subparsers)
    add_tasks_parser(subparsers)
    add_jobs_parser(subparsers)
    add_agents_parser(subparsers)
    add_spec_parser(subparsers)

    if include_internal:
        supervisor = subparsers.add_parser("_supervisor")
        supervisor.add_argument("--repo-root", required=True)
        supervisor.add_argument("--state-dir", required=True)
        supervisor.add_argument("--no-console", action="store_true")
        supervisor.set_defaults(func=cmd_supervisor)

    return parser


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = build_parser(include_internal=bool(argv and argv[0] == "_supervisor"))
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except BrokenPipeError:
        return 1
    except KeyboardInterrupt:
        print("", file=sys.stderr)
        return 130
    except UserError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.code


if __name__ == "__main__":
    raise SystemExit(main())
