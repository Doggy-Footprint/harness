import hashlib
from concurrent.futures import ThreadPoolExecutor
import json
import random
import shlex
import re

from . import section, testrun, validate
from .languages import changed_lines, classify_path, diff_paths

TOOLS = {"python": "mutmut", "typescript": "stryker", "go": "go-mutesting", "rust": "cargo-mutants"}
WORKDIR = "/testbed"
_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")
LIST_COMMANDS = {
    "go-mutesting": (
        "printf '%s\\n' '#!/bin/sh' 'diff -u \"$MUTATE_ORIGINAL\" \"$MUTATE_CHANGED\"' 'exit 0' "
        "> /tmp/evaluation-mutesting-diff.sh && chmod 0755 /tmp/evaluation-mutesting-diff.sh "
        "&& go-mutesting --exec /tmp/evaluation-mutesting-diff.sh {packages} 2>&1"
    ),
    "cargo-mutants": "cargo mutants --list --json --diff --file {files} 2>/dev/null",
}


def mutant_id(path: str, line: int, diff: str) -> str:
    return hashlib.sha256(f"{path}\0{line}\0{diff}".encode()).hexdigest()[:16]


def _row(path: str, line: int, diff: str) -> dict:
    return {"id": mutant_id(path, line, diff), "path": path, "line": line, "diff": diff}


_TMP_COPY = re.compile(r"^/tmp/go-mutesting-\d+/(.*?)(?:\.\d+)?$")


def _clean_path(raw: str) -> str:
    raw = raw.split("\t")[0].strip()
    m = _TMP_COPY.match(raw)
    if m:
        return m.group(1)
    for prefix in ("a/", "b/", WORKDIR + "/"):
        if raw.startswith(prefix):
            raw = raw[len(prefix):]
    return raw


def _first_changed_line(diff: str) -> int:
    new_line = None
    for text in diff.splitlines():
        m = _HUNK_RE.match(text)
        if m:
            new_line = int(m.group(2))
            continue
        if new_line is None:
            continue
        if text.startswith("+") and not text.startswith("+++"):
            return new_line
        if text.startswith("-") and not text.startswith("---"):
            return new_line
        new_line += 1
    return 0


def _diff_blocks(raw: str) -> list[dict]:
    lines = raw.splitlines()
    rows, i = [], 0
    while i < len(lines):
        if not (lines[i].startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ ")):
            i += 1
            continue
        block, i = [lines[i], lines[i + 1]], i + 2
        while i < len(lines) and lines[i][:1] in ("@", " ", "+", "-", "\\") and not (
            lines[i].startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ ")
        ):
            block.append(lines[i])
            i += 1
        if any(t.startswith("@@") for t in block):
            body = "\n".join(block) + "\n"
            rows.append(_row(_clean_path(block[0][4:]), _first_changed_line(body), body))
    return rows


def _unified(path: str, source: str, start: int, end: int, replacement: str, line: int) -> str:
    lines = source.split("\n")
    old = lines[line - 1] if 0 < line <= len(lines) else ""
    line_start = sum(len(x) + 1 for x in lines[: line - 1])
    new = (source[line_start:start] + replacement + source[end:]).split("\n")[0]
    return f"--- a/{path}\n+++ b/{path}\n@@ -{line},1 +{line},1 @@\n-{old}\n+{new}\n"


def _stryker(raw: str) -> list[dict]:
    report = json.loads(raw)
    rows = []
    for path, info in (report.get("files") or {}).items():
        if _declaration(path):
            continue
        source = info.get("source", "")
        offsets = [0]
        for text in source.split("\n"):
            offsets.append(offsets[-1] + len(text) + 1)
        for m in info.get("mutants", []):
            loc = m["location"]
            (sl, sc), (el, ec) = (loc["start"]["line"], loc["start"]["column"]), (loc["end"]["line"], loc["end"]["column"])
            start, end = offsets[sl - 1] + sc - 1, offsets[el - 1] + ec - 1
            rows.append(_row(path, sl, _unified(path, source, start, end, m.get("replacement", ""), sl)))
    return rows


def _cargo_mutants(raw: str) -> list[dict]:
    rows = []
    for m in json.loads(raw):
        diff = m.get("diff") or ""
        path = m["file"]
        line = m.get("line") or (m.get("span") or {}).get("start", {}).get("line") or _first_changed_line(diff)
        rows.append(_row(path, int(line), diff))
    return rows


_NORMALIZERS = {
    "mutmut": _diff_blocks,
    "go-mutesting": _diff_blocks,
    "stryker": _stryker,
    "cargo-mutants": _cargo_mutants,
}


def normalize(tool: str, raw: str) -> list[dict]:
    if tool not in _NORMALIZERS:
        raise ValueError(f"unknown mutation tool: {tool}")
    rows = _NORMALIZERS[tool](raw)
    return sorted({r["id"]: r for r in rows}.values(), key=lambda r: r["id"])


def restrict(mutants: list[dict], changed: dict[str, set[int]]) -> list[dict]:
    return [m for m in mutants if m["line"] in changed.get(m["path"], ())]


def sample(mutants: list[dict], cap: int, seed: int) -> list[dict]:
    ordered = sorted(mutants, key=lambda m: m["id"])
    if len(ordered) <= cap:
        return ordered
    return random.Random(seed).sample(ordered, cap)


def apply_diff(text: str, diff: str) -> str:
    lines = text.split("\n")
    shift = 0
    cur = None
    for raw in diff.splitlines():
        m = re.match(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)", raw)
        if m:
            cur = int(m.group(1)) - 1 + shift
            continue
        if cur is None or raw.startswith(("---", "+++", "\\")):
            continue
        tag, body = raw[:1], raw[1:]
        if tag == " ":
            cur += 1
        elif tag == "-":
            if cur >= len(lines) or lines[cur] != body:
                raise ValueError("mutant diff does not apply")
            del lines[cur]
            shift -= 1
        elif tag == "+":
            lines.insert(cur, body)
            cur += 1
            shift += 1
    return "\n".join(lines)


MUTMUT_SCRIPT = """
import difflib, sys
from mutmut import ALL, Context, list_mutations, mutate

for path in sys.argv[1:]:
    with open(path) as fh:
        source = fh.read()
    for mid in list_mutations(Context(source=source, mutation_id=ALL, filename=path)):
        mutated, _ = mutate(Context(source=source, mutation_id=mid, filename=path))
        sys.stdout.write("".join(difflib.unified_diff(
            source.splitlines(True), mutated.splitlines(True), "a/" + path, "b/" + path)))
"""


STRYKER_CONFIG = "/tmp/stryker.conf.json"
STRYKER_REPORT = "/tmp/mutation.json"


def _declaration(path: str) -> bool:
    return path.endswith(".d.ts")


def stryker_config(paths: list[str]) -> dict:
    return {
        "mutate": [p for p in paths if not _declaration(p)], "testRunner": "command", "commandRunner": {"command": "true"},
        "reporters": ["json"], "jsonReporter": {"fileName": STRYKER_REPORT},
        "tempDirName": "/tmp/stryker-tmp", "cleanTempDir": True, "concurrency": 4,
    }


def list_command(language: str, paths: list[str]) -> list[str]:
    tool = TOOLS[language]
    if tool == "stryker":
        config = shlex.quote(json.dumps(stryker_config(paths)))
        return ["sh", "-c", f"printf %s {config} > {STRYKER_CONFIG} && npx stryker run {STRYKER_CONFIG} "
                f">/dev/null 2>&1; cat {STRYKER_REPORT}"]
    if tool == "mutmut":
        return ["python", "-c", MUTMUT_SCRIPT, *paths]
    template = LIST_COMMANDS[tool]
    packages = sorted({"./" + p.rsplit("/", 1)[0] if "/" in p else "." for p in paths})
    script = template.format(
        paths=",".join(paths), globs=",".join(paths), files=" --file ".join(paths),
        packages=" ".join(packages),
    )
    return ["sh", "-c", script]


def build_mutants(task: dict, *, docker, cfg: dict, cache_dir) -> list[dict]:
    mcfg = section(cfg, "mutants")
    language = task["language"]
    src_diff = task["gold_split"]["src"]
    changed = changed_lines(src_diff)
    paths = [p for p in diff_paths(src_diff) if classify_path(language, p) == "src" and p in changed]
    if language == "typescript":
        paths = [p for p in paths if not _declaration(p)]
    if not paths:
        return []
    with docker.container(task["image"], network=False) as c:
        testrun.apply_tree(c, validate.merge_tree(task))
        code, out, timed_out = c.exec(
            list_command(language, paths), timeout=cfg.get("eval", {}).get("timeout_s", 900), workdir=WORKDIR
        )
    if timed_out:
        return []
    chosen = sample(
        restrict(normalize(TOOLS[language], out), changed), mcfg.get("cap", 40), mcfg.get("seed", 1)
    )
    selection = validate.gold_selection(task)
    merged = validate.merge_tree(task)

    def evaluate(m: dict) -> dict:
        try:
            mutated = apply_diff(task["gold_after"][m["path"]], m["diff"])
        except (KeyError, ValueError):
            return {**m, "gold": "build_error"}
        result = testrun.run_tests(
            task, {**merged, m["path"]: mutated}, selection, docker=docker, cfg=cfg, cache_dir=cache_dir
        )
        if result["status"] != "ok":
            status = "timeout" if result["status"] == "timeout" else "build_error"
        else:
            fails = [t for t in [*task["f2p"], *task["p2p"]] if result["results"].get(t) in ("fail", "error")]
            status = "killed" if fails else "survived"
        return {**m, "gold": status}

    # Each mutant runs in its own container; 40 sequential suite runs per task take most of an hour.
    with ThreadPoolExecutor(max_workers=max(1, mcfg.get("workers", 1))) as pool:
        return list(pool.map(evaluate, chosen))
