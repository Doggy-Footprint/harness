#!/usr/bin/env python3
import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

# lib/ goes first: bin/ holds a progress.py that would shadow lib/progress.py.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import config  # noqa: E402
import synced  # noqa: E402

REPO_ROOT = config.REPO_ROOT
PATHS = config.load_paths()
MANAGED_FILENAME_RE = re.compile(r"^[0-9a-f]{16}-[a-z0-9]+(?:-[a-z0-9]+)*\.md$")
SEPARATOR_RE = re.compile(r"^---\s*$")
FILE_LINE_RE = re.compile(r"^File:\s*(.*)$")
EXEMPT_DIRS = {"specs", "spec-logs", "progress", "progress-logs", "adr", "rejections", "handoff"}


class Refusal(Exception):
    pass


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def fail(message: str) -> int:
    print(f"records.py: {message}", file=sys.stderr)
    return 1


def read(path: Path) -> str:
    with open(path, encoding="utf-8", newline="") as handle:
        return handle.read()


def write(path: Path, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def git(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(REPO_ROOT), *args], capture_output=True, text=True)


def set_frontmatter_values(text: str, values: dict[str, str]) -> str:
    match = re.match(r"^(---[ \t]*\r?\n)(.*?)(\r?\n---[ \t]*\r?\n)", text, re.DOTALL)
    if not match:
        raise Refusal("frontmatter is missing")
    lines = match.group(2).split("\n")
    seen = set()
    for index, line in enumerate(lines):
        key = line.split(":", 1)[0].strip()
        if key in values and ":" in line:
            ending = "\r" if line.endswith("\r") else ""
            lines[index] = f"{key}: {values[key]}{ending}"
            seen.add(key)
    for key, value in values.items():
        if key not in seen:
            lines.append(f"{key}: {value}")
    return match.group(1) + "\n".join(lines) + match.group(3) + text[match.end():]


def cmd_synced_refresh(args) -> int:
    sid = args.id
    tracking = PATHS.synced_comments / f"{sid}.md"
    if not tracking.is_file():
        return fail(f"{rel(tracking)} does not exist; nothing to refresh")
    text = read(tracking)
    frontmatter = synced.parse_tracking_frontmatter(text)
    if frontmatter is None or not all(key in frontmatter for key in ("version", "count", "code_hash")):
        return fail(f"{rel(tracking)} has missing or invalid frontmatter (version, count, code_hash)")
    if frontmatter.get("obsolete", "false").lower() == "true":
        return fail(f"synced id {sid} is marked obsolete in {rel(tracking)}")
    try:
        tracked = synced.tracked_files(REPO_ROOT)
    except (subprocess.CalledProcessError, OSError) as error:
        return fail(f"cannot list tracked files: {error}")
    block_map, errors = synced.scan(REPO_ROOT, tracked, PATHS.docs_root, PATHS.exclude_dirs)
    own_errors = [error for error in errors if error.sid == sid]
    if own_errors:
        return fail(
            f"synced id {sid} has structural errors; fix them first:\n" + "\n".join(f"  - {error}" for error in own_errors)
        )
    blocks = block_map.get(sid, [])
    if not blocks:
        return fail(f"no code location carries synced id {sid}; nothing to refresh")
    count = len(blocks)
    code_hash = synced.block_hash(blocks)
    if count == int(frontmatter["count"]) and code_hash == frontmatter["code_hash"]:
        print(f"synced id {sid}: count and code_hash unchanged")
        return 0
    old = int(frontmatter["version"])
    new = old + 1
    pattern = re.compile(rf"synced id:\s*{sid}\s*,\s*version:\s*\d+\s*,\s*count:\s*\d+")
    replacement = f"synced id: {sid}, version: {new}, count: {count}"
    rewrites = {}
    tag_total = 0
    for path in sorted({block.path for block in blocks}):
        rewrites[path], tags = pattern.subn(replacement, read(REPO_ROOT / path))
        tag_total += tags
    reason = args.reason if args.reason else "Refreshed count and code_hash."
    updated = set_frontmatter_values(text, {"version": str(new), "count": str(count), "code_hash": code_hash})
    updated = updated.rstrip("\r\n") + f"\n\n## v{new} Log\n- {reason}\n"
    try:
        for path, content in rewrites.items():
            write(REPO_ROOT / path, content)
        write(tracking, updated)
    except OSError as error:
        return fail(f"write failed: {error.strerror or type(error).__name__}")
    print(
        f"synced id {sid}: version {old} -> {new}, count {count}, code_hash {code_hash}; "
        f"updated {tag_total} tag(s)"
    )
    return 0


def index_blocks(text: str) -> list[list]:
    segments: list[list] = [[[], None]]
    for line in text.splitlines(keepends=True):
        if SEPARATOR_RE.match(line.rstrip("\r\n")):
            segments[-1][1] = line
            segments.append([[], None])
        else:
            segments[-1][0].append(line)
    return segments


def segment_file(segment: list[str]) -> str | None:
    for line in segment:
        match = FILE_LINE_RE.match(line.rstrip("\r\n"))
        if match:
            return match.group(1).strip()
    return None


def validate_stale_target(path: Path) -> Path:
    docs = PATHS.docs_root.resolve()
    directory = path.parent
    if not path.is_file() or not MANAGED_FILENAME_RE.match(path.name):
        raise Refusal(f"{rel(path)} is not a file named <16-hex>-<kebab>.md")
    if not directory.is_relative_to(docs) or directory == docs:
        raise Refusal(f"{rel(path)} is not inside a managed directory under {rel(PATHS.docs_root)}/")
    parts = directory.relative_to(docs).parts
    if parts[0] in EXEMPT_DIRS or "stale" in parts:
        raise Refusal(f"{rel(directory)}/ is not an index-managed directory")
    if not (directory / "index.md").is_file():
        raise Refusal(f"{rel(directory)}/ holds no index.md")
    return directory


def cmd_stale(args) -> int:
    path = Path(args.path)
    if not path.is_absolute():
        candidate = Path.cwd() / path
        path = candidate if candidate.exists() else REPO_ROOT / path
    path = path.resolve()
    try:
        directory = validate_stale_target(path)
        index = directory / "index.md"
        stale_md = directory / "stale.md"
        stale_dir = directory / "stale"
        destination = stale_dir / path.name
        if destination.exists():
            raise Refusal(f"{rel(destination)} already exists")
        segments = index_blocks(read(index))
        matching = [
            number for number, (lines, _separator) in enumerate(segments)
            if any(line.strip() for line in lines) and segment_file(lines) == path.name
        ]
        if not matching:
            raise Refusal(f"{rel(index)} has no entry with `File: {path.name}`")
        if len(matching) > 1:
            raise Refusal(f"{rel(index)} has {len(matching)} entries with `File: {path.name}`; remove the duplicates first")
        number = matching[0]
        block = segments[number][0]
        if segments[number][1] is None and number > 0:
            segments[number - 1][1] = None
        del segments[number]
        remaining = "".join("".join(lines) + (separator or "") for lines, separator in segments)
        existing = read(stale_md) if stale_md.is_file() else ""
        appended = existing
        if existing.strip():
            appended = existing if existing.endswith("\n") else existing + "\n"
            appended += "---\n"
        else:
            appended = ""
        appended += "".join(block)
        if not appended.endswith("\n"):
            appended += "\n"
        tracked = git(["ls-files", "--error-unmatch", "--", rel(path)]).returncode == 0
        created_dir = not stale_dir.exists()
        stale_dir.mkdir(exist_ok=True)
        if tracked:
            moved = git(["mv", "--", rel(path), rel(destination)])
            if moved.returncode != 0:
                if created_dir:
                    stale_dir.rmdir()
                raise Refusal(f"git mv {rel(path)} {rel(destination)} failed: {moved.stderr.strip()}")
        else:
            os.rename(path, destination)
        write(index, remaining)
        write(stale_md, appended)
    except Refusal as error:
        return fail(str(error))
    except OSError as error:
        return fail(f"{error.strerror or type(error).__name__}: {error.filename or ''}".rstrip(": "))
    print(f"stale: {rel(path)} -> {rel(destination)}")
    return 0


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(prog="records.py")
    commands = value.add_subparsers(dest="command", required=True)
    stale = commands.add_parser("stale", help="move a record to stale/ and its index entry to stale.md")
    stale.add_argument("path")
    stale.set_defaults(handler=cmd_stale)
    refresh = commands.add_parser("synced-refresh", help="update count, code_hash, version, and tags of a synced id")
    refresh.add_argument("id")
    refresh.add_argument("--reason", help="Version Log entry (default: Refreshed count and code_hash.)")
    refresh.set_defaults(handler=cmd_synced_refresh)
    return value


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
