#!/usr/bin/env python3
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import config  # noqa: E402
import progress  # noqa: E402
import synced  # noqa: E402

PATHS = config.load_paths()
REPO_ROOT = config.REPO_ROOT
EXCLUDE_DIRS = PATHS.exclude_dirs

HEX16 = r"[0-9a-f]{16}"
KEBAB = r"[a-z0-9]+(?:-[a-z0-9]+)*"
MANAGED_FILENAME_RE = re.compile(rf"^{HEX16}-{KEBAB}\.md$")

INDEX_ENTRY_FIELDS = ["File", "Summary", "Related Files", "Related Symbols"]

REQUIRED_HEADINGS = {
    PATHS.try_n_fail: [
        "## Goal",
        "## Attempts",
        "## Revisit Condition",
    ],
    PATHS.todos: [
        "## Next Step",
    ],
}
TITLED_DIRS = {PATHS.todos}
WORKFLOW_DOC_DIRS = {"specs", "spec-logs"}
PROGRESS_DOC_DIRS = {"progress", "progress-logs"}
FACT_DOC_DIRS = {"facts"}
RETIRED_DOC_DIRS = {"adr", "rejections", "handoff"}


def rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def iter_docs_root_files():
    if not PATHS.docs_root.is_dir():
        return
    for path in PATHS.docs_root.rglob("*"):
        if not path.is_file():
            continue
        docs_parts = path.relative_to(PATHS.docs_root).parts
        if "stale" in docs_parts or (
            docs_parts and docs_parts[0] in WORKFLOW_DOC_DIRS | PROGRESS_DOC_DIRS | FACT_DOC_DIRS | RETIRED_DOC_DIRS
        ):
            continue
        if any(part in EXCLUDE_DIRS for part in path.relative_to(REPO_ROOT).parts):
            continue
        yield path


def git_tracked_files():
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files"],
        check=True,
        capture_output=True,
        text=True,
    )
    return [REPO_ROOT / line for line in result.stdout.splitlines() if line]


def check_index_and_staleness(errors: list):
    managed_dirs = {}
    for path in iter_docs_root_files():
        if MANAGED_FILENAME_RE.match(path.name):
            managed_dirs.setdefault(path.parent, []).append(path)

    for directory, files in managed_dirs.items():
        index_md = directory / "index.md"
        stale_dir = directory / "stale"

        if not index_md.exists():
            errors.append(f"{rel(directory)}: missing required index.md")
        if not (directory / "stale.md").is_file():
            errors.append(f"{rel(directory)}: missing required stale.md")
        if not stale_dir.is_dir():
            errors.append(f"{rel(directory)}: missing required stale/ directory")
        if not index_md.exists():
            continue

        content = index_md.read_text(encoding="utf-8", errors="replace")
        blocks = [b.strip() for b in re.split(r"(?m)^---\s*$", content) if b.strip()]

        listed_files = set()
        for block in blocks:
            entry = {}
            for line in block.splitlines():
                m = re.match(r"^(File|Summary|Related Files|Related Symbols):\s*(.*)$", line)
                if m:
                    entry[m.group(1)] = m.group(2).strip()
            missing_fields = [f for f in INDEX_ENTRY_FIELDS if f not in entry]
            if missing_fields:
                errors.append(
                    f"{rel(index_md)}: entry missing field(s) {missing_fields} in block: {block[:60]!r}"
                )
                continue
            listed_files.add(entry["File"])
            if not (directory / entry["File"]).exists():
                errors.append(
                    f"{rel(index_md)}: entry references nonexistent file {entry['File']!r}"
                )

        actual_files = {f.name for f in files}
        unlisted = actual_files - listed_files
        for name in sorted(unlisted):
            errors.append(f"{rel(directory)}: {name} is not listed in index.md")

        stray = listed_files - actual_files - {"index.md"}
        for name in sorted(stray):
            errors.append(f"{rel(index_md)}: lists {name!r} but no such file exists")


def check_synced_comments(errors: list):
    try:
        tracked = synced.tracked_files(REPO_ROOT)
    except (subprocess.CalledProcessError, FileNotFoundError):
        tracked = []

    block_map, structural = synced.scan(REPO_ROOT, tracked, PATHS.docs_root, EXCLUDE_DIRS)
    errors.extend(structural)
    broken = {error.sid for error in structural}
    occurrences = {
        sid: [(block.path, block.version, block.count) for block in blocks]
        for sid, blocks in block_map.items()
    }
    synced_dir = PATHS.synced_comments

    for sid, locs in occurrences.items():
        tracking_file = synced_dir / f"{sid}.md"
        if not tracking_file.exists():
            errors.append(
                f"synced id {sid}: referenced in {[l[0] for l in locs]} but "
                f"{rel(synced_dir)}/{sid}.md does not exist"
            )
            continue

        fm = synced.parse_tracking_frontmatter(
            tracking_file.read_text(encoding="utf-8", errors="replace")
        )
        if fm is None or "version" not in fm or "count" not in fm or "code_hash" not in fm:
            errors.append(
                f"{rel(tracking_file)}: missing/invalid frontmatter "
                f"(version, count, code_hash)"
            )
            continue

        fm_version = int(fm["version"])
        fm_count = int(fm["count"])
        is_obsolete = fm.get("obsolete", "false").lower() == "true"

        if is_obsolete and locs:
            errors.append(
                f"synced id {sid}: marked obsolete in {rel(tracking_file)} "
                f"but still referenced in {[l[0] for l in locs]}"
            )
        elif not is_obsolete and sid not in broken:
            expected_hash = synced.block_hash(block_map[sid])
            if expected_hash != fm["code_hash"]:
                errors.append(
                    f"synced id {sid}: code between the tag and `synced end: {sid}` in "
                    f"{sorted({l[0] for l in locs})} no longer matches code_hash "
                    f"{fm['code_hash']} in {rel(tracking_file)} (recomputed "
                    f"{expected_hash}); run python3 .harness/bin/records.py synced-refresh {sid}"
                )

        actual_count = len(locs)
        for file_name, version, tagged_count in locs:
            if version != fm_version:
                errors.append(
                    f"{file_name}: synced id {sid} has version {version}, "
                    f"expected {fm_version} (from {rel(tracking_file)})"
                )
            if tagged_count != fm_count:
                errors.append(
                    f"{file_name}: synced id {sid} tag has count {tagged_count}, "
                    f"expected {fm_count} (from {rel(tracking_file)})"
                )
        if fm_count != actual_count:
            errors.append(
                f"{rel(tracking_file)}: declares count {fm_count} but "
                f"{actual_count} code location(s) actually reference it "
                f"({[l[0] for l in locs]})"
            )


def check_required_headings(errors: list, only=None):
    for directory, headings in REQUIRED_HEADINGS.items():
        if only is not None and directory != only:
            continue
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.md")):
            if not MANAGED_FILENAME_RE.match(path.name):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            missing = [
                h for h in headings
                if not re.search(rf"(?m)^{re.escape(h)}\s*$", text)
            ]
            if directory in TITLED_DIRS and not re.search(r"(?m)^# \S", text):
                missing.insert(0, "# <title>")
            if missing:
                errors.append(f"{rel(path)}: missing required heading(s) {missing}")


def check_progress(errors: list):
    if not PATHS.progress.is_dir():
        return
    current = sorted(path for path in PATHS.progress.glob("*.md") if path.is_file())
    if len(current) > 1:
        errors.append(
            f"{rel(PATHS.progress)}: holds {len(current)} progress files ({', '.join(p.name for p in current)}); "
            f"keep only the current session's and move the others to {rel(PATHS.progress_logs)}/"
        )
    for path in current:
        parsed = progress.parse(path.read_text(encoding="utf-8", errors="replace"))
        for line, message in progress.format_findings(parsed):
            errors.append(f"{rel(path)}:{line}: {message}")


def check_progress_secrets(errors: list):
    suffixes = config.load_mask_host_suffixes()
    for directory in (PATHS.progress, PATHS.progress_logs):
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*.md")):
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for line, category in progress.unmasked(text, suffixes):
                errors.append(
                    f"{rel(path)}:{line}: unmasked {category}; replace it with [masked:{category}]"
                )


RULE_FILE_DIR = ".harness/instructions"
IN_PROGRESS_GIT_STATES = ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply")


def git_dir() -> Path | None:
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "--git-dir"], capture_output=True, text=True
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return (REPO_ROOT / result.stdout.strip()).resolve()


def check_session_progress(errors: list):
    session_id = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    if not session_id or os.environ.get("HARNESS_UPDATE_COMMIT") == "1":
        return
    if not (progress.change_dir(REPO_ROOT, session_id) / "modified").is_file():
        return
    try:
        directory = git_dir()
    except OSError:
        return
    if directory is None or any((directory / name).exists() for name in IN_PROGRESS_GIT_STATES):
        return
    owned = []
    for folder in (PATHS.progress, PATHS.progress_logs):
        owned.extend(progress.session_files(folder, session_id))
    progress_rel, logs_rel = rel(PATHS.progress), rel(PATHS.progress_logs)
    if not owned:
        errors.append(
            f"session {session_id} changed the project but no progress in {progress_rel}/ or {logs_rel}/ has "
            f"`session: {session_id}`; write one and stage it with this commit"
        )
        return
    for path in owned:
        label = rel(path)
        staged = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "--verify", "--quiet", f":{label}"],
                                capture_output=True, text=True)
        worktree = progress.git_file_hash(REPO_ROOT, label)
        if staged.returncode != 0 or staged.stdout.strip() != worktree:
            errors.append(f"{label}: progress of session {session_id} is not staged with this commit; run `git add {label}`")
        parsed = progress.parse(path.read_text(encoding="utf-8", errors="replace"))
        if progress.is_record_only(parsed) and progress.code_marker(REPO_ROOT, session_id).exists():
            errors.append(
                f"{label}:1: record-only progress in a session that changed code; run any Edit to let the hook "
                "upgrade it, or write the full structure"
            )
        if path.parent == PATHS.progress_logs:
            for line, message in progress.format_findings(parsed):
                errors.append(f"{label}:{line}: {message}")


def main() -> int:
    errors: list = []
    violated: set = set()

    def run(rule_file: str, check, *args):
        before = len(errors)
        check(errors, *args)
        if len(errors) > before:
            violated.add(rule_file)

    run("index-and-staleness.md", check_index_and_staleness)
    run("synced-comments.md", check_synced_comments)
    run("try-n-fail.md", check_required_headings, PATHS.try_n_fail)
    run("todos.md", check_required_headings, PATHS.todos)
    run("progress.md", check_progress)
    run("progress.md", check_progress_secrets)
    run("progress.md", check_session_progress)

    if errors:
        order = [
            "index-and-staleness.md",
            "synced-comments.md",
            "try-n-fail.md",
            "todos.md",
            "progress.md",
        ]
        rule_files = ", ".join(f"{RULE_FILE_DIR}/{name}" for name in order if name in violated)
        print("harness rule violations found:\n", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        print(f"\nRule files: {rule_files}", file=sys.stderr)
        print(f"{len(errors)} violation(s). Commit blocked.", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
