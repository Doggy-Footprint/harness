#!/usr/bin/env python3
import argparse
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate  # noqa: E402

SOURCE_HARNESS = Path(__file__).resolve().parents[1] / "harness"
VERSION = (SOURCE_HARNESS / "VERSION").read_text(encoding="utf-8").strip()

REPORT_SECTIONS = ["write", "merge", "skip", "conflict", "manual review", "info"]

GITIGNORE_LINES = [
    "agent-docs/specs/.active",
    "agent-docs/specs/.running/",
    "agent-docs/specs/.seed/",
    ".harness/sessions/.running/",
    ".harness/**/__pycache__",
]
HOOK_MANAGER_FILES = [
    ".husky/pre-commit",
    "lefthook.yml",
    "lefthook.yaml",
    ".lefthook.yml",
    ".pre-commit-config.yaml",
]
INFO_PATHS = [
    ".claude/CLAUDE.md",
    "CLAUDE.local.md",
    ".cursor/rules",
    ".cursorrules",
    ".github/copilot-instructions.md",
    "adr",
    "docs/adr",
    "doc/adr",
    "docs/decisions",
    ".gitlab-ci.yml",
    ".circleci",
    "Jenkinsfile",
    "azure-pipelines.yml",
    "bitbucket-pipelines.yml",
]


class MigrationConflict(Exception):
    def __init__(self, conflicts: list[str]):
        self.conflicts = conflicts
        super().__init__("; ".join(conflicts))


class MigrationDeclined(Exception):
    pass


class InvalidManifestVersion(Exception):
    pass


def parse_version(value: str) -> tuple[int, ...]:
    if not isinstance(value, str) or not re.fullmatch(r"\d+\.\d+\.\d+", value):
        raise InvalidManifestVersion(value)
    return tuple(int(part) for part in value.split("."))


def format_version(version: tuple[int, ...]) -> str:
    return ".".join(str(part) for part in version)


def _stale_record_paths(target: Path) -> list[Path]:
    docs_root = target / "agent-docs"
    if not docs_root.is_dir():
        return []
    return sorted(
        path for path in docs_root.rglob("stale.md")
        if "stale" not in path.relative_to(docs_root).parts
    )


STALE_ARCHIVE_TITLE = "# Stale Index Archive\n"
STALE_ARCHIVE_HEADER = STALE_ARCHIVE_TITLE + "<!-- harness:stale-index-archive -->\n\n"


def _index_blocks(content: str) -> list[str]:
    return [block for block in re.split(r"(?m)^---[ \t]*\n?", content) if block.strip()]


def _index_block_matches(block: str, filename: str) -> bool:
    return bool(re.search(rf"(?m)^File:[ \t]*{re.escape(filename)}[ \t]*$", block))


def _write_index_blocks(blocks: list[str]) -> str:
    if not blocks:
        return ""
    return "\n---\n".join(block.rstrip("\n") for block in blocks) + "\n"


def _write_stale_archive(blocks: list[str]) -> str:
    archive = STALE_ARCHIVE_TITLE + "\n"
    for block in blocks:
        archive += block.rstrip("\n") + "\n---\n"
    return archive


def migrate_stale_records(target: Path, dry_run: bool) -> list[str]:
    moves: list[tuple[Path, Path]] = []
    stale_records = _stale_record_paths(target)
    conflicts: list[str] = []
    index_updates: dict[Path, str] = {}
    archive_updates: dict[Path, str] = {}
    destinations: set[Path] = set()
    for record in stale_records:
        record_content = record.read_text(encoding="utf-8")
        if record_content.startswith(STALE_ARCHIVE_TITLE):
            continue

        index_path = record.parent / "index.md"
        index_blocks = _index_blocks(index_path.read_text(encoding="utf-8")) if index_path.is_file() else []
        archived_blocks: list[str] = []
        remaining_blocks = index_blocks
        for line in record_content.splitlines():
            entry = line.strip()
            if not entry:
                continue
            listed_path = Path(entry)
            source = record.parent / listed_path
            destination = record.parent / "stale" / listed_path.name
            if listed_path.is_absolute() or ".." in listed_path.parts or source.parent != record.parent:
                conflicts.append(f"{record.relative_to(target)}: invalid stale entry {entry!r}")
            elif not source.is_file():
                conflicts.append(f"{record.relative_to(target)}: listed source {entry!r} is missing")
            elif destination.exists():
                conflicts.append(f"{record.relative_to(target)}: archive destination {destination.relative_to(target)} already exists")
            elif destination in destinations:
                conflicts.append(f"{record.relative_to(target)}: archive destination {destination.relative_to(target)} is listed more than once")
            else:
                destinations.add(destination)
                moves.append((source, destination))
                matching_blocks = [
                    block for block in remaining_blocks if _index_block_matches(block, listed_path.name)
                ]
                archived_blocks.extend(matching_blocks)
                remaining_blocks = [block for block in remaining_blocks if block not in matching_blocks]

        if index_path.is_file() and remaining_blocks != index_blocks:
            index_updates[index_path] = _write_index_blocks(remaining_blocks)
        archive_updates[record] = _write_stale_archive(archived_blocks)

    if conflicts:
        raise MigrationConflict(conflicts)

    planned = [f"move {source.relative_to(target)} to {destination.relative_to(target)}" for source, destination in moves]
    planned.extend(f"update {path.relative_to(target)}" for path in sorted(index_updates))
    planned.extend(f"archive stale index records in {path.relative_to(target)}" for path in sorted(archive_updates))
    if dry_run:
        return planned

    for source, destination in moves:
        destination.parent.mkdir(parents=True, exist_ok=True)
        source.rename(destination)
    for path, content in index_updates.items():
        path.write_text(content, encoding="utf-8")
    for path, content in archive_updates.items():
        path.write_text(content, encoding="utf-8")
    return planned


def migrate_stale_index_logs(target: Path, dry_run: bool) -> list[str]:
    updates: dict[Path, str] = {}
    for record in _stale_record_paths(target):
        content = record.read_text(encoding="utf-8")
        if content.startswith(STALE_ARCHIVE_HEADER):
            continue
        if content.startswith(STALE_ARCHIVE_TITLE):
            updates[record] = STALE_ARCHIVE_HEADER + content[len(STALE_ARCHIVE_TITLE):].lstrip("\n")
        else:
            updates[record] = STALE_ARCHIVE_HEADER + content

    planned = [f"format stale index archive {path.relative_to(target)}" for path in sorted(updates)]
    if dry_run:
        return planned
    for path, content in updates.items():
        path.write_text(content, encoding="utf-8")
    return planned


def migrate_workflow_markers(target: Path, dry_run: bool) -> list[str]:
    return []


def migrate_workflow_specs(target: Path, dry_run: bool) -> list[str]:
    contracts = target / "agent-docs" / "contracts"
    legacy_skill_link = target / ".claude" / "skills" / "contract-workflow"
    gitignore = target / ".gitignore"
    legacy_gitignore_lines = {
        "agent-docs/contracts/.running/",
        "agent-docs/contracts/.seed/",
    }
    conflicts = []
    if contracts.is_dir():
        contract_files = sorted(path for path in contracts.glob("*.md") if path.is_file())
        seed_files = sorted(
            path for path in (contracts / ".seed").rglob("*") if path.is_file()
        ) if (contracts / ".seed").is_dir() else []
        other_files = sorted(
            path for path in contracts.rglob("*")
            if path.is_file()
            and path not in contract_files
            and path not in seed_files
            and ".running" not in path.relative_to(contracts).parts
        )
        if contract_files:
            conflicts.append(
                "agent-docs/contracts contains active contract documents; finish or hand off the workflow before updating"
            )
        if seed_files:
            conflicts.append(
                "agent-docs/contracts/.seed contains an unrestored backup; restore it before updating"
            )
        if other_files:
            conflicts.append("agent-docs/contracts contains unrecognized files")
    if legacy_skill_link.is_symlink():
        expected = "../../.agents/skills/contract-workflow"
        if os.readlink(legacy_skill_link) != expected:
            conflicts.append(f"{legacy_skill_link.relative_to(target)} points to a user target")
    elif legacy_skill_link.exists():
        conflicts.append(f"{legacy_skill_link.relative_to(target)} is user-owned")
    if conflicts:
        raise MigrationConflict(conflicts)

    planned = []
    if contracts.is_dir():
        planned.append("remove empty legacy agent-docs/contracts workflow state")
    if legacy_skill_link.is_symlink():
        planned.append("remove legacy .claude/skills/contract-workflow symlink")
    gitignore_content = gitignore.read_text(encoding="utf-8") if gitignore.is_file() else None
    filtered_gitignore = None
    if gitignore_content is not None:
        filtered_lines = [
            line for line in gitignore_content.splitlines()
            if line not in legacy_gitignore_lines
        ]
        filtered_gitignore = "\n".join(filtered_lines) + ("\n" if filtered_lines else "")
        if filtered_gitignore != gitignore_content:
            planned.append("remove legacy contract workflow entries from .gitignore")
    if dry_run:
        return planned
    if contracts.is_dir():
        shutil.rmtree(contracts)
    if legacy_skill_link.is_symlink():
        legacy_skill_link.unlink()
    if filtered_gitignore is not None and filtered_gitignore != gitignore_content:
        gitignore.write_text(filtered_gitignore, encoding="utf-8")
    return planned


def migrate_verifier_budget(target: Path, dry_run: bool) -> list[str]:
    updates = {}
    conflicts = []
    specs = target / "agent-docs" / "specs"
    for path in sorted(specs.glob("*.md")):
        content = path.read_text(encoding="utf-8")
        parts = content.split("---", 2)
        if len(parts) != 3 or parts[0].strip():
            conflicts.append(f"{path.relative_to(target)} has invalid frontmatter")
            continue
        header, body = parts[1:]
        if not re.search(r"(?m)^max_correction_rounds:", header):
            continue
        if re.search(r"(?m)^status: (complete|limit|aborted)\s*$", header):
            continue
        version = re.search(r"(?m)^version: ([1-9][0-9]*)\s*$", header)
        counters = re.findall(r"(?m)^\| verifier invocations \| ([0-9]+) \|\s*$", body)
        if (not version or len(counters) != 1
                or body.count("# Version Log\n") != 1
                or re.search(r"(?m)^max_verifier_invocations:", header)):
            conflicts.append(
                f"{path.relative_to(target)} needs an unambiguous version, verifier count, and Version Log before migration"
            )
            continue
        next_version = int(version.group(1)) + 1
        header = re.sub(r"(?m)^version: [0-9]+", f"version: {next_version}", header)
        header = re.sub(r"(?m)^max_correction_rounds:[^\n]*", "max_verifier_invocations: 2", header)
        body = body.replace(
            "# Version Log\n",
            f"# Version Log\n## v{next_version}\n"
            "- Harness 0.8.0 migration: ordinary corrections have no count limit; "
            "verifier invocations are limited to two total per run. "
            "This supersedes the prior correction-limit policy. "
            f"Preserved verifier invocations: {counters[0]}; do not reset on resume.\n\n",
            1,
        )
        updates[path] = "---" + header + "---" + body
    if conflicts:
        raise MigrationConflict(conflicts)
    planned = [f"migrate verifier budget in {path.relative_to(target)}" for path in updates]
    if not dry_run:
        for path, content in updates.items():
            path.write_text(content, encoding="utf-8")
    return planned


def migrate_verification_scope(target: Path, dry_run: bool) -> list[str]:
    return [
        "install bounded verification and persistent audit-state instructions",
        "preserve existing specs, archived records, and verifier counts; before resume, "
        "reconcile obligation scope and audit state, obtaining approval for policy changes",
    ]


def migrate_test_design_coverage(target: Path, dry_run: bool) -> list[str]:
    return [
        "install ISO/IEC/IEEE 29119-4 test design technique and coverage target instructions",
        "preserve existing specs, archived records, and verifier counts; before resume, "
        "declare each obligation's technique, coverage items, and target for user approval",
    ]


MIGRATIONS = (
    (parse_version("0.3.0"), "archive stale records", migrate_stale_records),
    (parse_version("0.4.0"), "format stale index archives", migrate_stale_index_logs),
    (parse_version("0.6.0"), "install workflow telemetry markers", migrate_workflow_markers),
    (parse_version("0.7.0"), "replace contract workflow with persistent specs", migrate_workflow_specs),
    (parse_version("0.8.0"), "limit verifier to two invocations; uncap ordinary corrections", migrate_verifier_budget),
    (parse_version("0.9.0"), "bound verification scope and retain audit decisions", migrate_verification_scope),
    (parse_version("0.10.0"), "declare 29119-4 test design techniques and coverage targets", migrate_test_design_coverage),
)


def run_migrations(
    target: Path,
    installed_version: str,
    dry_run: bool,
    input_fn: Callable[[str], str],
) -> bool:
    installed = parse_version(installed_version)
    current = parse_version(VERSION)
    if installed > current:
        raise InvalidManifestVersion(installed_version)

    applicable_migrations = [
        (migration_version, label, migration)
        for migration_version, label, migration in sorted(MIGRATIONS, key=lambda migration: migration[0])
        if installed < migration_version <= current
    ]
    planned_migrations = []
    for migration_version, label, migration in applicable_migrations:
        planned = migration(target, dry_run=True)
        planned_migrations.append((migration_version, label, migration, planned))
        version = format_version(migration_version)
        print(f"migration {version}: {label}")
        for item in planned:
            print(f"- {item}")
        if dry_run:
            print("- confirmation required (dry-run: not requested)")

    if dry_run:
        return True

    for migration_version, label, _migration, _planned in planned_migrations:
        version = format_version(migration_version)
        if input_fn(f"Apply migration {version} ({label})? [y/N] ").strip().lower() != "y":
            raise MigrationDeclined()

    for _migration_version, _label, migration, _planned in planned_migrations:
        migration(target, dry_run=False)
    return True


def iter_skill_dirs():
    return sorted(d for d in (SOURCE_HARNESS / "skills").iterdir() if d.is_dir())


def new_report():
    return {section: [] for section in REPORT_SECTIONS}


def print_report(report):
    for section in REPORT_SECTIONS:
        items = report[section]
        if not items:
            continue
        print(f"== {section} ==")
        for item in items:
            print(f"- {item}")


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_git(target: Path, args: list):
    return subprocess.run(
        ["git", "-C", str(target)] + args, capture_output=True, text=True
    )


def is_git_worktree(target: Path) -> bool:
    if not target.exists():
        return False
    result = run_git(target, ["rev-parse", "--is-inside-work-tree"])
    return result.returncode == 0 and result.stdout.strip() == "true"


def render_owned_files(no_ci: bool) -> dict:
    owned = {}
    for path in SOURCE_HARNESS.rglob("*"):
        if path.is_dir():
            continue
        if "__pycache__" in path.relative_to(SOURCE_HARNESS).parts:
            continue
        rel = ".harness/" + path.relative_to(SOURCE_HARNESS).as_posix()
        owned[rel] = path.read_bytes()

    for agent_path in sorted((SOURCE_HARNESS / "agents").glob("*.md")):
        name = agent_path.stem
        fields, body = generate.parse_agent_source(agent_path.read_text(encoding="utf-8"))
        owned[f".claude/agents/{name}.md"] = generate.render_claude_agent_md(fields, body).encode("utf-8")
        owned[f".codex/agents/{name}.toml"] = generate.render_codex_agent_toml(fields, body).encode("utf-8")

    for skill_src in iter_skill_dirs():
        for path in sorted(skill_src.rglob("*")):
            if path.is_dir():
                continue
            rel = f".agents/skills/{skill_src.name}/" + path.relative_to(skill_src).as_posix()
            owned[rel] = path.read_bytes()

    if not no_ci:
        ci_src = SOURCE_HARNESS / "ci" / "harness-comment-warning.yml"
        owned[".github/workflows/harness-comment-warning.yml"] = ci_src.read_bytes()

    return owned


def check_owned_conflicts(target: Path, owned: dict, old_manifest_files: dict) -> list:
    conflicts = []
    for relpath in owned:
        if relpath in old_manifest_files:
            continue
        if (target / relpath).exists():
            conflicts.append(f"{relpath} already exists")
    return conflicts


def apply_owned_files(target: Path, owned: dict, old_manifest_files: dict, dry_run: bool, report: dict) -> dict:
    new_manifest = {}
    for relpath, content in owned.items():
        new_sha = hashlib.sha256(content).hexdigest()
        disk_path = target / relpath
        disk_sha = sha256_of(disk_path) if disk_path.exists() else None
        old_sha = old_manifest_files.get(relpath)
        if disk_sha is None or disk_sha == old_sha:
            if not dry_run:
                disk_path.parent.mkdir(parents=True, exist_ok=True)
                disk_path.write_bytes(content)
            report["write"].append(relpath)
            new_manifest[relpath] = new_sha
        elif disk_sha == new_sha:
            new_manifest[relpath] = new_sha
        else:
            report["skip"].append(f"{relpath} (user-modified)")
            new_manifest[relpath] = old_sha

    for relpath, old_sha in old_manifest_files.items():
        if relpath in owned:
            continue
        disk_path = target / relpath
        if not disk_path.exists():
            continue
        disk_sha = sha256_of(disk_path)
        if disk_sha == old_sha:
            if not dry_run:
                disk_path.unlink()
            report["write"].append(f"delete {relpath}")
        else:
            report["skip"].append(f"{relpath} (user-modified, not deleted)")
            new_manifest[relpath] = old_sha

    for name in ("pre-commit", "post-merge"):
        path = target / ".harness" / "git" / name
        if not dry_run and path.exists():
            os.chmod(path, 0o755)

    for skill_src in iter_skill_dirs():
        link = target / ".claude" / "skills" / skill_src.name
        if not dry_run:
            link.parent.mkdir(parents=True, exist_ok=True)
            if not link.exists() and not link.is_symlink():
                os.symlink(f"../../.agents/skills/{skill_src.name}", link)

    return new_manifest


def _group_is_harness(group: dict) -> bool:
    return any("/.harness/" in h.get("command", "") for h in group.get("hooks", []))


def merge_hooks_dict(existing: dict, new_hooks: dict) -> dict:
    result = dict(existing)
    hooks = dict(result.get("hooks", {}))
    for event, new_groups in new_hooks["hooks"].items():
        old_groups = hooks.get(event, [])
        kept = [g for g in old_groups if not _group_is_harness(g)]
        combined = kept + new_groups
        if combined:
            hooks[event] = combined
        elif event in hooks:
            del hooks[event]
    result["hooks"] = hooks
    return result


def merge_hook_files(target: Path, dry_run: bool, report: dict):
    hooks_spec = generate.load_hooks_spec(SOURCE_HARNESS / "hooks" / "hooks.spec.json")
    renders = (
        (".claude/settings.json", generate.render_claude_settings_hooks(hooks_spec)),
        (".codex/hooks.json", generate.render_codex_hooks(hooks_spec)),
    )
    for relpath, new_hooks in renders:
        path = target / relpath
        existing = {}
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
        merged = merge_hooks_dict(existing, new_hooks)
        if merged == existing:
            continue
        text = json.dumps(merged, indent=2, ensure_ascii=False) + "\n"
        if not dry_run:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        report["merge"].append(relpath)


HEADING_RE = re.compile(r"(?m)^#{1,2}\s+(.+?)\s*$")
MARKER_RE = re.compile(r"<!-- harness:begin [^\n]*-->\n(.*?)<!-- harness:end -->\n?", re.DOTALL)


def install_or_merge_agents_md(target: Path, dry_run: bool, report: dict):
    block_body = (SOURCE_HARNESS / "instructions" / "harness-block.md").read_text(encoding="utf-8")
    begin = f"<!-- harness:begin {VERSION} -->"
    end = "<!-- harness:end -->"
    wrapped = f"{begin}\n{block_body.rstrip(chr(10))}\n{end}\n"
    path = target / "AGENTS.md"
    block_headings = {m.group(1).strip().lower() for m in HEADING_RE.finditer(block_body)}

    if not path.exists():
        content = "# Project Definition\n\n[#TODO][3-5 lines of description of the project]\n\n" + wrapped
        if not dry_run:
            path.write_text(content, encoding="utf-8")
        report["write"].append("AGENTS.md")
        return

    existing = path.read_text(encoding="utf-8")
    match = MARKER_RE.search(existing)
    if match:
        new_content = existing[: match.start()] + wrapped + existing[match.end():]
        external = existing[: match.start()] + existing[match.end():]
    else:
        new_content = existing.rstrip("\n") + "\n\n" + wrapped
        external = existing

    if not dry_run:
        path.write_text(new_content, encoding="utf-8")
    report["merge"].append("AGENTS.md")

    for heading_match in HEADING_RE.finditer(external):
        heading = heading_match.group(1).strip()
        if heading.lower() in block_headings:
            report["manual review"].append(
                f"AGENTS.md: heading '{heading}' outside the managed block duplicates one inside it"
            )


def install_claude_md(target: Path, dry_run: bool, report: dict, original_agents_md_bytes):
    path = target / "CLAUDE.md"
    if not path.exists():
        if not dry_run:
            path.write_text("@AGENTS.md\n", encoding="utf-8")
        report["write"].append("CLAUDE.md")
        return

    content_bytes = path.read_bytes()
    if original_agents_md_bytes is not None and content_bytes == original_agents_md_bytes:
        if not dry_run:
            path.write_text("@AGENTS.md\n", encoding="utf-8")
        report["merge"].append("CLAUDE.md")
        return

    text = content_bytes.decode("utf-8", errors="replace")
    first_line = text.splitlines()[0] if text else ""
    if first_line.strip() == "@AGENTS.md":
        report["skip"].append("CLAUDE.md (already imports AGENTS.md)")
        return

    new_text = "@AGENTS.md\n\n" + text
    if not dry_run:
        path.write_text(new_text, encoding="utf-8")
    report["merge"].append("CLAUDE.md")
    report["manual review"].append("CLAUDE.md: prepended @AGENTS.md import; check for duplicated content")


def ensure_agent_docs_dirs(target: Path, dry_run: bool, report: dict):
    for name in ("adr", "rejections", "handoff", "requirements"):
        directory = target / "agent-docs" / name
        path = directory / "index.md"
        if not path.exists():
            if not dry_run:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("", encoding="utf-8")
            report["write"].append(str(path.relative_to(target)))
        stale_record = directory / "stale.md"
        if not stale_record.exists():
            if not dry_run:
                stale_record.parent.mkdir(parents=True, exist_ok=True)
                stale_record.write_text(STALE_ARCHIVE_HEADER, encoding="utf-8")
            report["write"].append(str(stale_record.relative_to(target)))
        stale_gitkeep = directory / "stale" / ".gitkeep"
        if not stale_gitkeep.exists():
            if not dry_run:
                stale_gitkeep.parent.mkdir(parents=True, exist_ok=True)
                stale_gitkeep.write_text("", encoding="utf-8")
            report["write"].append(str(stale_gitkeep.relative_to(target)))
    gitkeep = target / "agent-docs" / "synced-comments" / ".gitkeep"
    if not gitkeep.exists():
        if not dry_run:
            gitkeep.parent.mkdir(parents=True, exist_ok=True)
            gitkeep.write_text("", encoding="utf-8")
        report["write"].append(str(gitkeep.relative_to(target)))


def ensure_gitignore(target: Path, dry_run: bool, report: dict):
    path = target / ".gitignore"
    if not path.exists():
        if not dry_run:
            path.write_text("\n".join(GITIGNORE_LINES) + "\n", encoding="utf-8")
        report["write"].append(".gitignore")
        return
    existing = path.read_text(encoding="utf-8")
    existing_lines = set(existing.splitlines())
    missing = [line for line in GITIGNORE_LINES if line not in existing_lines]
    if missing:
        prefix = "" if existing == "" or existing.endswith("\n") else "\n"
        if not dry_run:
            path.write_text(existing + prefix + "\n".join(missing) + "\n", encoding="utf-8")
        report["merge"].append(".gitignore")


def ensure_git_hooks(target: Path, dry_run: bool, report: dict):
    current = run_git(target, ["config", "--get", "core.hooksPath"]).stdout.strip()
    if current == ".harness/git":
        return
    manager_present = bool(current) or any((target / f).exists() for f in HOOK_MANAGER_FILES)
    if manager_present:
        report["manual review"].append(
            "git hook manager detected; add these invocations to your hooks: "
            '`.harness/git/pre-commit "$@"` (pre-commit), `.harness/git/post-merge "$@"` (post-merge)'
        )
        return
    if not dry_run:
        run_git(target, ["config", "core.hooksPath", ".harness/git"])
    report["write"].append("git config core.hooksPath=.harness/git")


def collect_info_items(target: Path, report: dict):
    for candidate in INFO_PATHS:
        if (target / candidate).exists():
            report["info"].append(f"{candidate} present (not touched)")
    result = run_git(target, ["ls-files"])
    if result.returncode == 0:
        for line in result.stdout.splitlines():
            if line != "AGENTS.md" and line.endswith("/AGENTS.md"):
                report["info"].append(f"{line} present (not touched)")


def finish_common(target: Path, dry_run: bool, report: dict):
    agents_md_path = target / "AGENTS.md"
    original_agents_md = agents_md_path.read_bytes() if agents_md_path.exists() else None

    merge_hook_files(target, dry_run, report)
    install_or_merge_agents_md(target, dry_run, report)
    install_claude_md(target, dry_run, report, original_agents_md)
    ensure_agent_docs_dirs(target, dry_run, report)
    ensure_gitignore(target, dry_run, report)
    ensure_git_hooks(target, dry_run, report)
    collect_info_items(target, report)


def check_settings_json_validity(target: Path, report: dict) -> bool:
    ok = True
    for relpath in (".claude/settings.json", ".codex/hooks.json"):
        path = target / relpath
        if path.exists():
            try:
                json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                report["conflict"].append(f"{relpath} is not valid JSON")
                ok = False
    return ok


def cmd_install(target: Path, dry_run: bool, no_ci: bool) -> int:
    report = new_report()

    if not is_git_worktree(target):
        report["conflict"].append(f"{target} is not a git work tree")
        print_report(report)
        return 1

    manifest_path = target / ".harness" / "manifest.json"
    if manifest_path.exists():
        report["conflict"].append(".harness/manifest.json already exists; already installed, use update")
        print_report(report)
        return 1

    owned = render_owned_files(no_ci)
    for c in check_owned_conflicts(target, owned, {}):
        report["conflict"].append(c)

    for skill_src in iter_skill_dirs():
        skill_dir = target / ".agents" / "skills" / skill_src.name
        if skill_dir.exists():
            report["conflict"].append(f".agents/skills/{skill_src.name} already exists")
        link = target / ".claude" / "skills" / skill_src.name
        if link.exists() or link.is_symlink():
            report["conflict"].append(f".claude/skills/{skill_src.name} already exists")

    check_settings_json_validity(target, report)

    if report["conflict"]:
        print_report(report)
        return 1

    new_manifest_files = apply_owned_files(target, owned, {}, dry_run, report)
    finish_common(target, dry_run, report)

    if not dry_run:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps({"version": VERSION, "files": new_manifest_files}, indent=2) + "\n",
            encoding="utf-8",
        )
    report["write"].append(".harness/manifest.json")

    print_report(report)
    return 0


def cmd_update(target: Path, dry_run: bool, no_ci: bool) -> int:
    report = new_report()

    if not is_git_worktree(target):
        report["conflict"].append(f"{target} is not a git work tree")
        print_report(report)
        return 1

    manifest_path = target / ".harness" / "manifest.json"
    if not manifest_path.exists():
        report["conflict"].append(".harness/manifest.json not found; run install first")
        print_report(report)
        return 1

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        report["conflict"].append(".harness/manifest.json is not valid JSON")
        print_report(report)
        return 1

    old_files = manifest.get("files", {})
    owned = render_owned_files(no_ci)
    for c in check_owned_conflicts(target, owned, old_files):
        report["conflict"].append(c)

    check_settings_json_validity(target, report)

    if report["conflict"]:
        print_report(report)
        return 1

    try:
        run_migrations(target, manifest.get("version"), dry_run, input)
    except InvalidManifestVersion:
        report["conflict"].append("InvalidManifestVersion: .harness/manifest.json version is absent or malformed")
        print_report(report)
        return 1
    except MigrationConflict as error:
        report["conflict"].extend(f"MigrationConflict: {conflict}" for conflict in error.conflicts)
        print_report(report)
        return 1
    except MigrationDeclined:
        report["conflict"].append("MigrationDeclined: migration was not confirmed")
        print_report(report)
        return 1

    new_manifest_files = apply_owned_files(target, owned, old_files, dry_run, report)
    finish_common(target, dry_run, report)

    if not dry_run:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps({"version": VERSION, "files": new_manifest_files}, indent=2) + "\n",
            encoding="utf-8",
        )
    report["write"].append(".harness/manifest.json")

    print_report(report)
    return 0


def cmd_doctor(target: Path) -> int:
    report = new_report()

    if not is_git_worktree(target):
        report["conflict"].append(f"{target} is not a git work tree")
        print_report(report)
        return 1

    manifest_path = target / ".harness" / "manifest.json"
    if not manifest_path.exists():
        report["conflict"].append("manifest missing")
    else:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for relpath, sha in manifest.get("files", {}).items():
            path = target / relpath
            if not path.exists():
                report["conflict"].append(f"{relpath}: missing")
            elif sha256_of(path) != sha:
                report["conflict"].append(f"{relpath}: modified (sha mismatch)")

    hooks_spec = generate.load_hooks_spec(SOURCE_HARNESS / "hooks" / "hooks.spec.json")
    renders = (
        (".claude/settings.json", generate.render_claude_settings_hooks(hooks_spec)),
        (".codex/hooks.json", generate.render_codex_hooks(hooks_spec)),
    )
    for relpath, new_hooks in renders:
        path = target / relpath
        existing = None
        if path.exists():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                report["conflict"].append(f"{relpath}: invalid JSON")
        else:
            existing = {}
        if existing is not None:
            for event, groups in new_hooks["hooks"].items():
                existing_groups = existing.get("hooks", {}).get(event, [])
                for group in groups:
                    if group not in existing_groups:
                        report["conflict"].append(f"{relpath}: missing harness hook entry for {event}")

    block_body = (SOURCE_HARNESS / "instructions" / "harness-block.md").read_text(encoding="utf-8")
    agents_md = target / "AGENTS.md"
    if not agents_md.exists():
        report["conflict"].append("AGENTS.md missing")
    else:
        text = agents_md.read_text(encoding="utf-8")
        match = MARKER_RE.search(text)
        if not match:
            report["conflict"].append("AGENTS.md: managed block missing")
        elif match.group(1).rstrip("\n") != block_body.rstrip("\n"):
            report["conflict"].append("AGENTS.md: managed block content differs from harness/instructions/harness-block.md")

    claude_md = target / "CLAUDE.md"
    if not claude_md.exists():
        report["conflict"].append("CLAUDE.md missing")
    else:
        claude_text = claude_md.read_text(encoding="utf-8")
        first_line = claude_text.splitlines()[0] if claude_text else ""
        if first_line.strip() != "@AGENTS.md":
            report["conflict"].append("CLAUDE.md: first line is not @AGENTS.md")

    current_hooks_path = run_git(target, ["config", "--get", "core.hooksPath"]).stdout.strip()
    integrated = current_hooks_path == ".harness/git"
    if not integrated:
        for f in HOOK_MANAGER_FILES:
            path = target / f
            if path.is_file():
                try:
                    if ".harness/git/pre-commit" in path.read_text(encoding="utf-8"):
                        integrated = True
                        break
                except OSError:
                    pass
    if not integrated:
        report["conflict"].append("git hooks not integrated with .harness/git")

    collect_info_items(target, report)

    print_report(report)
    return 1 if report["conflict"] else 0


IMPORT_SCAN_DIRS = [".harness", ".agents/skills", ".claude/agents", ".claude/skills", ".codex/agents"]
IMPORT_SCAN_SKIP = ("__pycache__", "/sessions/", "manifest.json")


def _decode(data: bytes):
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def collect_drift(target: Path, manifest: dict, owned: dict) -> dict:
    drift = {
        "target": str(target),
        "target_version": manifest.get("version"),
        "harness_version": VERSION,
        "modified": [],
        "missing": [],
        "added": [],
        "unchanged": 0,
    }
    files = manifest.get("files", {})
    for relpath, sha in sorted(files.items()):
        path = target / relpath
        if not path.exists():
            drift["missing"].append(relpath)
            continue
        current = path.read_bytes()
        if hashlib.sha256(current).hexdigest() == sha:
            drift["unchanged"] += 1
            continue
        entry = {"path": relpath, "baseline": "harness source" if relpath in owned else "unavailable"}
        base_text = _decode(owned[relpath]) if relpath in owned else None
        cur_text = _decode(current)
        if base_text is not None and cur_text is not None:
            entry["diff"] = "".join(
                difflib.unified_diff(
                    base_text.splitlines(keepends=True),
                    cur_text.splitlines(keepends=True),
                    fromfile=f"harness/{relpath}",
                    tofile=f"target/{relpath}",
                )
            )
        else:
            entry["diff"] = None
        drift["modified"].append(entry)

    for scan in IMPORT_SCAN_DIRS:
        root = target / scan
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            relpath = path.relative_to(target).as_posix()
            if relpath in files or any(skip in "/" + relpath for skip in IMPORT_SCAN_SKIP):
                continue
            drift["added"].append(relpath)
    return drift


def cmd_import(target: Path, as_json: bool) -> int:
    if not is_git_worktree(target):
        print(f"{target} is not a git work tree", file=sys.stderr)
        return 1
    manifest_path = target / ".harness" / "manifest.json"
    if not manifest_path.exists():
        print(f"{target}: harness is not installed (no .harness/manifest.json)", file=sys.stderr)
        return 1

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    drift = collect_drift(target, manifest, render_owned_files(no_ci=False))

    if as_json:
        print(json.dumps(drift, indent=2, ensure_ascii=False))
        return 0

    print(f"== versions ==\n  target: {drift['target_version']}\n  harness: {drift['harness_version']}")
    print(f"== unchanged ==\n  {drift['unchanged']} file(s)")
    if drift["missing"]:
        print("== missing ==")
        for relpath in drift["missing"]:
            print(f"  {relpath}")
    if drift["added"]:
        print("== added ==")
        for relpath in drift["added"]:
            print(f"  {relpath}")
    print("== modified ==")
    if not drift["modified"]:
        print("  none")
    for entry in drift["modified"]:
        print(f"  {entry['path']} (baseline: {entry['baseline']})")
        if entry["diff"]:
            for line in entry["diff"].splitlines():
                print(f"    {line}")
        else:
            print("    no textual diff available")
    return 0


def main(argv) -> int:
    parser = argparse.ArgumentParser(prog="harness.py")
    parser.add_argument("command", choices=["install", "update", "upgrade", "doctor", "import"])
    parser.add_argument("target")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-ci", action="store_true")
    parser.add_argument("--json", action="store_true", help="machine-readable output (import only)")
    args = parser.parse_args(argv)
    target = Path(args.target).resolve()

    if args.command == "install":
        return cmd_install(target, args.dry_run, args.no_ci)
    if args.command in ("update", "upgrade"):
        return cmd_update(target, args.dry_run, args.no_ci)
    if args.command == "import":
        return cmd_import(target, args.json)
    return cmd_doctor(target)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
