import json
import os
import subprocess
from pathlib import Path

import config

PATHS = config.load_paths()
REPO_ROOT = config.REPO_ROOT.resolve()
SPECS_DIR = PATHS.specs.resolve()
SPEC_LOGS_DIR = PATHS.spec_logs.resolve()
SEED_DIR = SPECS_DIR / ".seed"
SUBAGENT_RUNNING_DIR = SPECS_DIR / ".running"
SESSIONS_RUNNING_DIR = REPO_ROOT / ".harness" / "sessions" / ".running"
TERMINAL = {"complete", "limit", "aborted"}
PREFIX = "spec lifecycle: "
SEED_RESTORE = "python3 .harness/bin/seed.py restore"
SEED_MANIFESTS = {"manifest.json", "manifest.json.tmp"}
ANCESTOR_WALK_LIMIT = 64


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def frontmatter(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {}
    if not lines or lines[0].strip() != "---":
        return {}
    values = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return values
        if ":" in line:
            key, value = line.split(":", 1)
            values[key.strip()] = value.strip()
    return {}


def seed_files() -> list[Path]:
    try:
        if not SEED_DIR.is_dir():
            return []
        return sorted(path for path in SEED_DIR.rglob("*") if path.is_file())
    except OSError:
        return []


def spec_files() -> list[Path]:
    try:
        return sorted(SPECS_DIR.glob("*.md"))
    except OSError:
        return []


def is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def ancestor_pids() -> set[int]:
    # A failed walk keeps the pids found so far: fewer own pids means more
    # markers classed as other, so the failure refuses instead of proceeding.
    found = {os.getpid(), os.getppid()}
    pid = os.getppid()
    for _ in range(ANCESTOR_WALK_LIMIT):
        if pid <= 1:
            break
        try:
            result = subprocess.run(
                ["ps", "-o", "ppid=", "-p", str(pid)],
                capture_output=True, text=True, timeout=5, check=False,
            )
            pid = int(result.stdout.strip())
        except (OSError, ValueError, subprocess.SubprocessError):
            break
        if pid in found:
            break
        found.add(pid)
    return found


def marker_session_id(marker: Path) -> str | None:
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    value = data.get("session_id")
    return value if isinstance(value, str) and value else None


def other_live_sessions() -> list[tuple[int, str | None]]:
    try:
        markers = sorted(SESSIONS_RUNNING_DIR.iterdir())
    except OSError:
        return []
    candidates = []
    for marker in markers:
        if not marker.name.isascii() or not marker.name.isdecimal():
            continue
        pid = int(marker.name)
        try:
            if not marker.is_file() or not is_alive(pid):
                continue
        except OSError:
            continue
        candidates.append((pid, marker_session_id(marker)))
    if not candidates:
        return []
    own_session = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    ancestors = ancestor_pids()
    return [
        (pid, session_id)
        for pid, session_id in candidates
        if pid not in ancestors and not (own_session and session_id == own_session)
    ]


def format_sessions(sessions: list[tuple[int, str | None]]) -> str:
    return ", ".join(
        f"pid {pid} (session id {session_id})" if session_id else f"pid {pid}"
        for pid, session_id in sessions
    )


def _seed_line() -> list[str]:
    files = seed_files()
    if not files:
        return []
    names = []
    for path in files:
        try:
            name = path.relative_to(SEED_DIR).as_posix()
        except ValueError:
            continue
        if name not in SEED_MANIFESTS:
            names.append(name)
    return [
        f"{PREFIX}unrestored seed backup in {rel(SEED_DIR)} ({', '.join(names)}); run `{SEED_RESTORE}`"
    ]


def _spec_lines() -> list[str]:
    seeded = bool(seed_files())
    open_lines = []
    done_lines = []
    for path in spec_files():
        values = frontmatter(path)
        status = values.get("status")
        if status in {"draft", "active"}:
            base = values.get("base_commit") or "unknown"
            open_lines.append(f"{PREFIX}{rel(path)} is {status}, base_commit {base}")
        elif status in TERMINAL:
            destination = SPEC_LOGS_DIR / path.name
            if seeded:
                reason = "unrestored seed backup"
            elif destination.exists():
                reason = f"already in {rel(destination)}"
            else:
                reason = "not archived yet"
            done_lines.append(f"{PREFIX}{rel(path)} is {status}: {reason}")
    return open_lines + done_lines


def _running_line() -> list[str]:
    try:
        entries = sorted(SUBAGENT_RUNNING_DIR.iterdir())
    except OSError:
        return []
    if not entries:
        return []
    return [
        f"{PREFIX}leftover subagent markers {', '.join(rel(entry) for entry in entries)}; "
        "delete them if no subagent is running"
    ]


def notice_lines() -> list[str]:
    lines = []
    for build in (_seed_line, _spec_lines, _running_line):
        try:
            lines.extend(build())
        except Exception:
            continue
    return lines


def print_notice() -> None:
    lines = notice_lines()
    if lines:
        print("\n".join(lines))
