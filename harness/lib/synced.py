import hashlib
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

SYNCED_ID_RE = r"[0-9a-f]{12}"
TAG_RE = re.compile(rf"synced id:\s*({SYNCED_ID_RE})\s*,\s*version:\s*(\d+)\s*,\s*count:\s*(\d+)")
END_RE = re.compile(rf"synced end:\s*({SYNCED_ID_RE})")

TEXT_FILE_EXTS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".kt",
    ".c", ".h", ".cpp", ".hpp", ".cc", ".rb", ".php", ".swift", ".md",
    ".sh", ".yaml", ".yml", ".json", ".toml",
}
HASH_COMMENT_EXTS = {".py", ".sh", ".yaml", ".yml", ".toml", ".rb"}
SLASH_COMMENT_EXTS = {
    ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".kt",
    ".c", ".h", ".cpp", ".hpp", ".cc", ".swift",
}
HASH_AND_SLASH_COMMENT_EXTS = {".php"}


class StructuralError(str):
    def __new__(cls, message: str, sid: str):
        value = super().__new__(cls, message)
        value.sid = sid
        return value


@dataclass
class Block:
    path: str
    tag_line: int
    end_line: int | None
    version: int
    count: int
    lines: list[str] = field(default_factory=list)


def comment_markers(path: Path | str) -> tuple[str, ...]:
    suffix = Path(path).suffix
    if suffix in HASH_COMMENT_EXTS:
        return ("#",)
    if suffix in SLASH_COMMENT_EXTS:
        return ("//",)
    if suffix in HASH_AND_SLASH_COMMENT_EXTS:
        return ("#", "//")
    return ()


def parse_tracking_frontmatter(text: str) -> dict | None:
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not match:
        return None
    fields = {}
    for line in match.group(1).splitlines():
        pair = re.match(r"^(\w+):\s*(.*)$", line.strip())
        if pair:
            fields[pair.group(1)] = pair.group(2).strip()
    return fields


def tracked_files(repo_root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files"], check=True, capture_output=True, text=True
    )
    return [repo_root / line for line in result.stdout.splitlines() if line]


def _scan_file(relative: str, text: str, markers: tuple[str, ...]) -> tuple[list[tuple[str, Block]], list[str]]:
    found: list[tuple[str, Block]] = []
    errors: list[str] = []
    open_blocks: dict[str, list[Block]] = {}
    for number, line in enumerate(text.splitlines(), 1):
        for match in END_RE.finditer(line):
            sid = match.group(1)
            closing = open_blocks.pop(sid, [])
            for block in closing:
                block.end_line = number
            if not closing:
                errors.append(StructuralError(
                    f"{relative}:{number}: `synced end: {sid}` has no synced id {sid} tag before it", sid
                ))
        for match in TAG_RE.finditer(line):
            sid = match.group(1)
            block = Block(relative, number, None, int(match.group(2)), int(match.group(3)))
            found.append((sid, block))
            open_blocks.setdefault(sid, []).append(block)
        for blocks in open_blocks.values():
            for block in blocks:
                if block.tag_line == number:
                    continue
                if TAG_RE.search(line) or END_RE.search(line):
                    continue
                if markers and line.strip().startswith(markers):
                    continue
                block.lines.append(line)
    for sid, block in found:
        if block.end_line is None:
            errors.append(StructuralError(
                f"{relative}:{block.tag_line}: synced id {sid} has no later `synced end: {sid}` line; "
                "add it where the tagged block ends",
                sid,
            ))
    return found, errors


def scan(
    repo_root: Path, paths: list[Path], docs_root: Path, exclude_dirs
) -> tuple[dict[str, list[Block]], list[str]]:
    root = repo_root.resolve()
    docs = docs_root.resolve()
    blocks: dict[str, list[Block]] = {}
    errors: list[str] = []
    for path in paths:
        absolute = path if path.is_absolute() else repo_root / path
        if absolute.suffix not in TEXT_FILE_EXTS:
            continue
        try:
            resolved = absolute.resolve()
            relative = resolved.relative_to(root)
        except (OSError, ValueError):
            continue
        if any(part in exclude_dirs for part in relative.parts) or resolved.is_relative_to(docs):
            continue
        try:
            text = absolute.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        found, file_errors = _scan_file(relative.as_posix(), text, comment_markers(absolute))
        for sid, block in found:
            blocks.setdefault(sid, []).append(block)
        errors.extend(file_errors)
    return blocks, errors


def block_hash(blocks: list[Block]) -> str:
    digest = hashlib.sha256()
    for block in sorted(blocks, key=lambda item: (item.path, item.tag_line)):
        for line in block.lines:
            digest.update((line + "\n").encode("utf-8"))
    return digest.hexdigest()[:12]
