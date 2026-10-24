import ast
import hashlib
import random
import re
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import evaluate, patches
from .evaluate import PASS

OPERATORS = ("ROR", "LCR", "AOR", "NEG", "CRP", "SDL", "RVR", "BCR")

_ROR_SWAP = {"<": "<=", "<=": "<", ">": ">=", ">=": ">", "==": "!=", "!=": "==", "is": "is not", "is not": "is", "in": "not in", "not in": "in"}
_ROR_TOKENS = {
    ast.Lt: "<", ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">=", ast.Eq: "==", ast.NotEq: "!=",
    ast.Is: "is", ast.IsNot: "is not", ast.In: "in", ast.NotIn: "not in",
}
_ROR_REGEX = {
    "<": r"<(?!=)", "<=": r"<=", ">": r">(?!=)", ">=": r">=", "==": r"==", "!=": r"!=",
    "is": r"\bis\b", "is not": r"\bis\s+not\b", "in": r"\bin\b", "not in": r"\bnot\s+in\b",
}
_AOR = {
    ast.Add: ("+", r"\+", "-"),
    ast.Sub: ("-", r"-", "+"),
    ast.Mult: ("*", r"(?<!\*)\*(?!\*)", "/"),
    ast.Div: ("/", r"(?<!/)/(?!/)", "*"),
    ast.FloorDiv: ("//", r"//", "/"),
    ast.Mod: ("%", r"%", "*"),
}
_SDL_TYPES = (
    ast.Expr, ast.Assign, ast.AugAssign, ast.AnnAssign, ast.Delete, ast.Raise,
    ast.Assert, ast.Return, ast.Import, ast.ImportFrom,
)


def _masked(src: patches.SourceView, a: int, b: int) -> str:
    # Between two operands only parens, whitespace, comments and the operator can occur.
    chunk = src.text(a, b)
    return re.sub(r"#[^\n]*", lambda m: " " * len(m.group()), chunk)


def _find_token(src: patches.SourceView, a: int, b: int, pattern: str):
    chunk = _masked(src, a, b)
    found = list(re.finditer(pattern, chunk))
    if len(found) != 1:
        return None
    m = found[0]
    start = a + len(chunk[: m.start()].encode("utf-8"))
    return start, start + len(m.group().encode("utf-8")), m.group()


def _candidates(src: patches.SourceView, tree: ast.AST, docstrings: set[int]):
    in_fstring = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            for sub in ast.walk(node):
                in_fstring.add(id(sub))
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            left = node.left
            for op, right in zip(node.ops, node.comparators):
                tok = _ROR_TOKENS[type(op)]
                a, b = src.span(left)[1], src.span(right)[0]
                hit = _find_token(src, a, b, _ROR_REGEX[tok])
                if hit:
                    yield "ROR", hit[0], hit[1], _ROR_SWAP[tok]
                left = right
        elif isinstance(node, ast.BoolOp):
            word, other = ("and", "or") if isinstance(node.op, ast.And) else ("or", "and")
            for left, right in zip(node.values, node.values[1:]):
                hit = _find_token(src, src.span(left)[1], src.span(right)[0], rf"\b{word}\b")
                if hit:
                    yield "LCR", hit[0], hit[1], other
        elif isinstance(node, ast.BinOp) and type(node.op) in _AOR:
            tok, regex, repl = _AOR[type(node.op)]
            hit = _find_token(src, src.span(node.left)[1], src.span(node.right)[0], regex)
            if hit:
                yield "AOR", hit[0], hit[1], repl
        elif isinstance(node, (ast.If, ast.While, ast.IfExp)):
            a, b = src.span(node.test)
            yield "NEG", a, b, f"not ({src.text(a, b)})"
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            a, _ = src.span(node)
            b, _ = src.span(node.operand)
            if src.text(a, a + 3) == "not" and not re.search(r"#", src.text(a, b)):
                yield "NEG", a, b, ""
        elif isinstance(node, ast.Constant) and id(node) not in in_fstring and id(node) not in docstrings:
            a, b = src.span(node)
            v = node.value
            if v is True or v is False:
                yield "CRP", a, b, "False" if v else "True"
            elif isinstance(v, int):
                yield "CRP", a, b, str(v + 1)
            elif isinstance(v, str):
                yield "CRP", a, b, '"XX"' if v == "" else '""'
        elif isinstance(node, ast.Return):
            if node.value is not None and not (
                isinstance(node.value, ast.Constant) and node.value.value is None
            ):
                a, b = src.span(node.value)
                yield "RVR", a, b, "None"
        elif isinstance(node, ast.Break):
            a, b = src.span(node)
            yield "BCR", a, b, "continue"
        elif isinstance(node, ast.Continue):
            a, b = src.span(node)
            yield "BCR", a, b, "break"
        if isinstance(node, _SDL_TYPES):
            if id(node.value if isinstance(node, ast.Expr) else node) in docstrings:
                continue
            if isinstance(node, ast.AnnAssign) and node.value is None:
                continue
            a, b = src.span(node)
            yield "SDL", a, b, "pass"


def _skip_docstring_constants(tree: ast.AST) -> set[int]:
    skip = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            skip.add(id(node.value))
    return skip


def _line_hunks(gold_patch: str) -> dict[str, dict[int, int]]:
    out: dict[str, dict[int, int]] = {}
    idx = -1
    for sec in patches.file_sections(gold_patch):
        lines: dict[int, int] = {}
        cur = 0
        in_hunk = False
        for ln in sec["text"].split("\n"):
            m = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", ln)
            if m:
                idx += 1
                cur = int(m.group(1))
                in_hunk = True
            elif not in_hunk or ln.startswith("\\"):
                continue
            elif ln.startswith("+"):
                lines[cur] = idx
                cur += 1
            elif not ln.startswith("-"):
                cur += 1
        if not sec["is_deleted"]:
            out[sec["path"]] = lines
    return out


class _DiffMaker:
    def __init__(self, path: str, base: str | None):
        self._td = tempfile.TemporaryDirectory(prefix="selfcheck-diff-")
        self.root = Path(self._td.name)
        self.path = path
        self.new = base is None
        self._git("init", "-q", ".")
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if base is not None:
            target.write_bytes(base.encode("utf-8"))
            self._git("add", "--", path)
            self._git("-c", "user.name=x", "-c", "user.email=x@x", "commit", "-qm", "base")

    def _git(self, *args):
        return subprocess.run(
            ["git", "-c", "core.autocrlf=false", "-c", "core.safecrlf=false", *args],
            cwd=self.root, env=patches._git_env(), capture_output=True, check=True,
        ).stdout.decode("utf-8")

    def diff(self, mutated: str) -> str:
        (self.root / self.path).write_bytes(mutated.encode("utf-8"))
        if self.new:
            self._git("add", "-N", "--", self.path)
        return self._git(
            "diff", "--no-color", "--no-ext-diff", "--no-renames",
            "--src-prefix=a/", "--dst-prefix=b/", "--", self.path,
        )

    def close(self):
        self._td.cleanup()


def _mutant_id(path, line, col, operator, replacement) -> str:
    key = f"{path}|{line}|{col}|{operator}|{replacement}"
    return "m" + hashlib.sha256(key.encode()).hexdigest()[:10]


def generate(
    base_sources: dict[str, str | None],
    gold_sources: dict[str, str],
    gold_patch: str,
    *,
    sample: int,
    seed: int,
) -> list[dict]:
    changed = {p: set(v) for p, v in patches.changed_lines(gold_patch).items()}
    hunks = _line_hunks(gold_patch)
    sections = {s["path"]: s for s in patches.file_sections(gold_patch)}
    found: list[dict] = []
    for path in sorted(gold_sources):
        if not path.endswith(".py") or path not in changed or path not in sections:
            continue
        sec = sections[path]
        if sec["is_deleted"] or (sec["old_path"] != path and not sec["is_new"]):
            continue
        gold = gold_sources[path]
        try:
            tree = ast.parse(gold)
        except SyntaxError:
            continue
        src = patches.SourceView(gold)
        docstrings = _skip_docstring_constants(tree)
        seen: set[str] = set()
        for operator, a, b, repl in _candidates(src, tree, docstrings):
            line, col = src.position(a)
            if line not in changed[path]:
                continue
            original = src.text(a, b)
            mutated = src.replaced(a, b, repl)
            if mutated == gold or mutated in seen:
                continue
            try:
                ast.parse(mutated)
            except (SyntaxError, ValueError):
                continue
            seen.add(mutated)
            found.append(
                {
                    "id": _mutant_id(path, line, col, operator, repl),
                    "path": path,
                    "line": line,
                    "col": col,
                    "operator": operator,
                    "original": original,
                    "replacement": repl,
                    "group": f"{hunks[path].get(line, 0)}:{operator}",
                    "_mutated": mutated,
                }
            )
    found.sort(key=lambda m: (m["path"], m["line"], m["col"], m["operator"], m["replacement"]))
    chosen = _sample(found, sample, seed)
    makers: dict[str, _DiffMaker] = {}
    out = []
    try:
        for m in chosen:
            path = m["path"]
            if path not in makers:
                makers[path] = _DiffMaker(path, base_sources.get(path))
            section = makers[path].diff(m["_mutated"])
            patch = gold_patch.replace(sections[path]["text"], section, 1)
            item = {k: v for k, v in m.items() if k != "_mutated"}
            item["patch"] = patch
            out.append(item)
    finally:
        for mk in makers.values():
            mk.close()
    return out


def _sample(found: list[dict], sample: int, seed: int) -> list[dict]:
    if len(found) <= sample:
        return found
    groups: dict[str, list[dict]] = {}
    for m in found:
        groups.setdefault(m["group"], []).append(m)
    rng = random.Random(seed)
    order = sorted(groups)
    rng.shuffle(order)
    picked: list[dict] = []
    while len(picked) < sample and any(groups.values()):
        for g in order:
            if len(picked) >= sample:
                break
            if groups[g]:
                picked.append(groups[g].pop(rng.randrange(len(groups[g]))))
    picked.sort(key=lambda m: (m["path"], m["line"], m["col"], m["operator"], m["replacement"]))
    return picked


def detect(
    instance: dict,
    mutants: list[dict],
    *,
    validation: dict,
    evaluate_fn=evaluate.evaluate,
    compile_fn=evaluate.compile_ok,
    workers: int = 2,
) -> list[dict]:
    watched = list(instance["FAIL_TO_PASS"]) + [
        t for t in validation["p2p_effective"] if t not in instance["FAIL_TO_PASS"]
    ]

    def one(m: dict) -> dict:
        if not compile_fn(instance, m["patch"], [m["path"]]):
            return {**m, "compile_ok": False, "killed": False, "timeout": False}
        res = evaluate_fn(instance, m["patch"], instance["test_patch"])
        timed_out = bool(res.get("timed_out"))
        killed = timed_out or any(res["status"].get(t) not in PASS for t in watched)
        return {**m, "compile_ok": True, "killed": killed, "timeout": timed_out}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(one, mutants))
