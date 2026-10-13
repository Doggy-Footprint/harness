import json
import os
import re
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

RULES_PATH = Path(__file__).parent / "fixtures" / "path_rules.json"
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def load_rules(path: str | Path | None = None) -> dict:
    return json.loads(Path(path or RULES_PATH).read_text())


def _glob_regex(glob: str) -> str:
    out = []
    i = 0
    while i < len(glob):
        if glob.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif glob.startswith("**", i):
            out.append(".*")
            i += 2
        elif glob[i] == "*":
            out.append("[^/]*")
            i += 1
        elif glob[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(glob[i]))
            i += 1
    return "".join(out)


@lru_cache(maxsize=None)
def _compiled(glob: str) -> re.Pattern:
    return re.compile(f"^{_glob_regex(glob)}$")


def _matches_any(path: str, globs) -> bool:
    return any(_compiled(g).match(path) for g in globs)


def classify_path(path: str, repo: str, *, is_new: bool = False, rules: dict | None = None) -> str:
    rules = rules or load_rules()
    if _matches_any(path, rules["excluded"]):
        return "excluded"
    if is_new and "/" not in path:
        return "scratch"
    if any(re.search(p, path) for p in rules["test_patterns"]):
        return "test"
    return "src"


_ESC = {"a": 7, "b": 8, "f": 12, "n": 10, "r": 13, "t": 9, "v": 11, '"': 34, "\\": 92}


def _unquote(text: str) -> str:
    # git C-quotes names holding control characters, non-ASCII bytes (default core.quotePath),
    # `"` or `\`: letter escapes or exactly three octal digits per raw byte.
    out = bytearray()
    i = 1
    while text[i] != '"':
        c = text[i]
        if c != "\\":
            out += c.encode("utf-8")
            i += 1
        elif text[i + 1] in _ESC:
            out.append(_ESC[text[i + 1]])
            i += 2
        else:
            out.append(int(text[i + 1:i + 4], 8))
            i += 4
    return out.decode("utf-8", "surrogateescape")


def _name(raw: str) -> str:
    return _unquote(raw) if raw.startswith('"') else raw


def _head_path(head: str) -> str:
    # Both names are identical and identically quoted unless rename/copy lines exist.
    if head.startswith('"'):
        return _unquote(head)[2:]
    return head[2:(len(head) - 5) // 2 + 2]


def _header_lines(section: str) -> list[str]:
    lines = []
    for ln in section.split("\n")[1:]:
        if ln.startswith("@@"):
            break
        lines.append(ln)
    return lines


def _header_paths(section: str, header: list[str]) -> tuple[str, str]:
    old = new = None
    for ln in header:
        for kind in ("rename", "copy"):
            if ln.startswith(kind + " from "):
                old = _name(ln[len(kind) + 6:])
            elif ln.startswith(kind + " to "):
                new = _name(ln[len(kind) + 4:])
    if old is None:
        old = new = _head_path(section.split("\n", 1)[0][len("diff --git "):])
    return old, new


def file_sections(diff: str) -> list[dict]:
    parts = re.split(r"(?m)^(?=diff --git )", diff)
    out = []
    for part in parts:
        if not part.startswith("diff --git "):
            continue
        head_lines = _header_lines(part)
        is_new = any(ln.startswith("new file mode") for ln in head_lines)
        is_deleted = any(ln.startswith("deleted file mode") for ln in head_lines)
        old, new = _header_paths(part, head_lines)
        out.append(
            {"path": new, "old_path": old, "is_new": is_new, "is_deleted": is_deleted, "text": part}
        )
    return out


def split_patch(diff: str, repo: str, rules: dict | None = None) -> dict[str, str]:
    rules = rules or load_rules()
    buckets = {"src": [], "test": [], "scratch": [], "excluded": []}
    for sec in file_sections(diff):
        path = sec["old_path"] if sec["is_deleted"] else sec["path"]
        cls = classify_path(path, repo, is_new=sec["is_new"], rules=rules)
        buckets[cls].append(sec["text"])
    return {k: "".join(v) for k, v in buckets.items()}


def changed_lines(diff: str) -> dict[str, list[int]]:
    out: dict[str, list[int]] = {}
    for sec in file_sections(diff):
        if sec["is_deleted"]:
            continue
        lines_added: list[int] = []
        cur = 0
        in_hunk = False
        for ln in sec["text"].split("\n"):
            m = _HUNK.match(ln)
            if m:
                cur = int(m.group(1))
                in_hunk = True
            elif not in_hunk or ln.startswith("\\"):
                continue
            elif ln.startswith("+"):
                lines_added.append(cur)
                cur += 1
            elif ln.startswith("-"):
                continue
            else:
                cur += 1
        out[sec["path"]] = sorted(set(lines_added))
    return out


def apply_to_texts(files: dict[str, str | None], patch: str) -> dict[str, str | None]:
    result_keys = list(files)
    for sec in file_sections(patch):
        if sec["path"] not in result_keys:
            result_keys.append(sec["path"])
    with tempfile.TemporaryDirectory(prefix="selfcheck-apply-") as td:
        root = Path(td)
        subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
        for rel, text in files.items():
            if text is None:
                continue
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(text.encode("utf-8"))
        if patch:
            proc = subprocess.run(
                ["git", "apply", "--whitespace=nowarn", "-"],
                cwd=root,
                input=patch.encode("utf-8"),
                capture_output=True,
            )
            if proc.returncode != 0:
                raise ValueError(f"patch does not apply: {proc.stderr.decode(errors='replace')}")
        out: dict[str, str | None] = {}
        for rel in result_keys:
            p = root / rel
            out[rel] = p.read_bytes().decode("utf-8", errors="replace") if p.is_file() else None
        return out


class SourceView:
    """Byte-offset view of a source file; ast col offsets are UTF-8 byte offsets."""

    def __init__(self, text: str):
        self.data = text.encode("utf-8")
        self.starts = [0]
        for m in re.finditer(rb"\n", self.data):
            self.starts.append(m.end())

    def offset(self, lineno: int, col: int) -> int:
        return self.starts[lineno - 1] + col

    def span(self, node) -> tuple[int, int]:
        return (
            self.offset(node.lineno, node.col_offset),
            self.offset(node.end_lineno, node.end_col_offset),
        )

    def position(self, off: int) -> tuple[int, int]:
        line = max(i for i, s in enumerate(self.starts) if s <= off)
        col = len(self.data[self.starts[line]:off].decode("utf-8", errors="replace"))
        return line + 1, col

    def text(self, a: int, b: int) -> str:
        return self.data[a:b].decode("utf-8")

    def replaced(self, a: int, b: int, repl: str) -> str:
        return (self.data[:a] + repl.encode("utf-8") + self.data[b:]).decode("utf-8")


def _git_env() -> dict:
    env = dict(os.environ)
    env.update(GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null", GIT_CONFIG_NOSYSTEM="1")
    return env


def diff_texts(base: dict[str, str | None], new: dict[str, str | None]) -> str:
    paths = sorted(set(base) | set(new))
    with tempfile.TemporaryDirectory(prefix="selfcheck-diff-") as td:
        root = Path(td)

        def git(*args):
            return subprocess.run(
                ["git", "-c", "core.autocrlf=false", "-c", "core.safecrlf=false", *args],
                cwd=root, env=_git_env(), capture_output=True, check=True,
            ).stdout.decode("utf-8")

        git("init", "-q", ".")
        for p in paths:
            if base.get(p) is not None:
                (root / p).parent.mkdir(parents=True, exist_ok=True)
                (root / p).write_bytes(base[p].encode("utf-8"))
        git("add", "-A")
        git("-c", "user.name=x", "-c", "user.email=x@x", "commit", "-q", "--allow-empty", "-m", "base")
        for p in paths:
            f = root / p
            if f.exists():
                f.unlink()
            if new.get(p) is not None:
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_bytes(new[p].encode("utf-8"))
        git("add", "-A")
        return git(
            "diff", "--cached", "--no-color", "--no-ext-diff", "--no-renames",
            "--src-prefix=a/", "--dst-prefix=b/",
        )
