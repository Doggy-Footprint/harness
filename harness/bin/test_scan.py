#!/usr/bin/env python3
import argparse
import ast
import fnmatch
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HEAVY_MOCK_THRESHOLD = 5
SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build",
    "target", ".harness", ".agents", ".claude", ".codex",
}
INVENTORY_DIRS = {"test", "tests", "spec", "__tests__"}
JS_EXTENSIONS = ("js", "jsx", "ts", "tsx", "mjs", "cjs")
BODY_TEST_LOOKAHEAD = 10

# The single table of per-language patterns. Add a language or tune a signal here only.
# "start" matches the line that begins a test; "name" is a group of "start" or, when
# "name_after" is set, a separate regex searched on the lines following the match.
LANGUAGES = {
    "python": {
        "globs": ["test_*.py", "*_test.py"],
        "dir_globs": {},
        "require": None,
        "start": None,
        "name_after": None,
        "brace": None,
        "skip": r"pytest\.mark\.skip(?:if)?\b|unittest\.skip(?:If|Unless)?\b|\bpytest\.skip\s*\(|\bself\.skipTest\s*\(|\bpytest\.importorskip\s*\(",
        "xfail": r"pytest\.mark\.xfail\b|\bpytest\.xfail\s*\(|\bexpectedFailure\b",
        "focused": None,
        "assert": r"\bassert\w*|\bpytest\.(?:raises|warns|fail)\b|\bself\.fail\s*\(",
        "sleep": r"\b(?:time|asyncio)\.sleep\s*\(",
        "mock": r"\b(?:Magic|Async)?Mock\s*\(|\b(?:mock\.)?patch(?:\.object|\.dict|\.multiple)?\s*\(|\bmocker\.\w+|\bmonkeypatch\.\w+|\bcreate_autospec\s*\(",
    },
    "javascript": {
        "globs": [f"*.{kind}.{ext}" for kind in ("test", "spec") for ext in JS_EXTENSIONS],
        "dir_globs": {"__tests__": [f"*.{ext}" for ext in JS_EXTENSIONS]},
        "require": None,
        "start": r"(?<![\w.$])(?:it|test|xit|xtest|fit)(?:\.(?:skip|only|concurrent|failing|fails|todo))*\s*\(\s*(?P<q>['\"`])(?P<name>.*?)(?P=q)",
        "name_after": None,
        "brace": r"(?:=>|\))\s*\{",
        "skip": r"\.skip\b|(?<![\w.$])x(?:it|test)\s*\(",
        "xfail": r"\.(?:failing|fails)\b",
        "focused": r"\.only\b|(?<![\w.$])fit\s*\(",
        "assert": r"\bexpect(?:Type)?(?:Of)?\s*[(.]|\bassert\w*|\.should\b|\bt\.(?:is|true|false|deepEqual|equal|throws)\b",
        "sleep": r"\bsetTimeout\s*\(|\bsleep\s*\(",
        "mock": r"\b(?:jest|vi)\.(?:fn|mock|doMock|spyOn)\s*\(|\bsinon\.(?:stub|spy|mock|fake)\w*\s*\(",
    },
    "go": {
        "globs": ["*_test.go"],
        "dir_globs": {},
        "require": None,
        "start": r"^func\s+(?P<name>Test\w*)\s*\(\s*\w+\s+\*testing\.T\s*\)",
        "name_after": None,
        "brace": None,
        "skip": r"\bt\.Skip(?:f|Now)?\s*\(",
        "xfail": None,
        "focused": None,
        "assert": r"\bt\.(?:Error|Errorf|Fatal|Fatalf|Fail|FailNow)\s*\(|\b(?:assert|require)\.\w+",
        "sleep": r"\btime\.Sleep\s*\(",
        "mock": r"\bgomock\.\w+|\bNewMock\w*\s*\(|\.EXPECT\s*\(|\.On\s*\(",
    },
    "rust": {
        "globs": ["*.rs"],
        "dir_globs": {},
        "require": r"#\[test\]",
        "start": r"^\s*#\[test\]",
        "name_after": r"\bfn\s+(?P<name>\w+)",
        "brace": None,
        "skip": r"#\[ignore\b",
        "xfail": None,
        "focused": None,
        "assert": r"\bassert\w*!|\bpanic!|\bunreachable!",
        "sleep": r"\bsleep\s*\(",
        "mock": r"\bmock!\s*\{|\bautomock\b|\bMock\w+::new\s*\(|\.expect_\w+\s*\(",
    },
    "java": {
        "globs": ["*Test.java", "*Tests.java"],
        "dir_globs": {},
        "require": None,
        "start": r"^\s*@Test\b",
        "name_after": r"\bvoid\s+(?P<name>\w+)\s*\(",
        "brace": None,
        "skip": r"@Disabled\b|@Ignore\b|\bAssumptions?\.\w+\s*\(",
        "xfail": None,
        "focused": None,
        "assert": r"\bassert\w*\s*\(|\bverify\w*\s*\(|\bfail\s*\(|\bexpectThrows\s*\(",
        "sleep": r"\bThread\.sleep\s*\(|\bTimeUnit\.\w+\.sleep\s*\(",
        "mock": r"\bMockito\.\w+\s*\(|@Mock\b|\bmock\s*\(|\bwhen\s*\(|\bspy\s*\(|\bdoReturn\s*\(",
    },
}
LANGUAGE_ORDER = ("python", "javascript", "go", "rust", "java")
FLAG_NAMES = ("skip", "xfail", "focused", "no_assert", "empty", "sleep", "heavy_mock", "duplicate_name")


def read_text(path: Path) -> str:
    return path.read_bytes().decode("utf-8", errors="replace")


def classify(rel: Path, text_loader) -> str | None:
    name = rel.name
    for language in LANGUAGE_ORDER:
        spec = LANGUAGES[language]
        matched = any(fnmatch.fnmatchcase(name, glob) for glob in spec["globs"])
        if not matched:
            matched = any(
                directory in rel.parts[:-1] and any(fnmatch.fnmatchcase(name, glob) for glob in globs)
                for directory, globs in spec["dir_globs"].items()
            )
        if not matched:
            continue
        if spec["require"] and not re.search(spec["require"], text_loader()):
            continue
        return language
    return None


def find_files(root: Path) -> list:
    found = []
    for current, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for name in sorted(names):
            path = Path(current) / name
            if path.is_file():
                found.append(path.relative_to(root))
    return sorted(found, key=lambda p: p.as_posix())


def count(pattern, text: str) -> int:
    return len(re.findall(pattern, text)) if pattern else 0


def signal_flags(language: str, body: str) -> set:
    spec = LANGUAGES[language]
    flags = set()
    for flag in ("skip", "xfail", "focused", "sleep"):
        if count(spec[flag], body):
            flags.add(flag)
    if not count(spec["assert"], body):
        flags.add("no_assert")
    if count(spec["mock"], body) >= HEAVY_MOCK_THRESHOLD:
        flags.add("heavy_mock")
    return flags


def python_tests(text: str) -> list:
    tree = ast.parse(text)
    lines = text.splitlines()
    tests = []

    def visit(statements):
        for node in statements:
            if isinstance(node, ast.ClassDef):
                visit(node.body)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
                first = min([node.lineno] + [d.lineno for d in node.decorator_list])
                body = "\n".join(lines[first - 1:node.end_lineno])
                flags = signal_flags("python", body)
                if all(
                    isinstance(s, ast.Pass) or (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))
                    for s in node.body
                ):
                    flags.add("empty")
                tests.append({"name": node.name, "line": node.lineno, "flags": flags})

    visit(tree.body)
    return tests


def brace_is_empty(language: str, body: str, search_from: int) -> bool:
    spec = LANGUAGES[language]
    if spec["brace"]:
        match = re.compile(spec["brace"]).search(body, search_from)
        if not match:
            return False
        open_at = match.end() - 1
    else:
        open_at = body.find("{", search_from)
        if open_at < 0:
            return False
    depth = 0
    for index in range(open_at, len(body)):
        if body[index] == "{":
            depth += 1
        elif body[index] == "}":
            depth -= 1
            if depth == 0:
                return body[open_at + 1:index].strip() == ""
    return body[open_at + 1:].strip() == ""


def generic_tests(language: str, text: str) -> list:
    spec = LANGUAGES[language]
    start_re = re.compile(spec["start"])
    name_re = re.compile(spec["name_after"]) if spec["name_after"] else None
    lines = text.splitlines()
    starts = []
    for index, line in enumerate(lines):
        match = start_re.search(line)
        if not match:
            continue
        if name_re is None:
            starts.append((index, index, match.group("name"), match.end()))
            continue
        for ahead in range(index, min(len(lines), index + 1 + BODY_TEST_LOOKAHEAD)):
            name_match = name_re.search(lines[ahead], match.end() if ahead == index else 0)
            if name_match:
                starts.append((index, ahead, name_match.group("name"), name_match.end()))
                break
    boundaries = []
    for index, line in enumerate(lines):
        if start_re.search(line):
            boundaries.append(index)
    tests = []
    for start, name_line, name, name_end in starts:
        following = [b for b in boundaries if b > start]
        end = following[0] if following else len(lines)
        body = "\n".join(lines[start:end])
        offset = sum(len(l) + 1 for l in lines[start:name_line]) + name_end
        flags = signal_flags(language, body)
        if brace_is_empty(language, body, offset):
            flags.add("empty")
        tests.append({"name": name, "line": name_line + 1, "flags": flags})
    return tests


def extract_tests(language: str, text: str) -> list:
    tests = python_tests(text) if language == "python" else generic_tests(language, text)
    names = [t["name"] for t in tests]
    for test in tests:
        if names.count(test["name"]) > 1:
            test["flags"].add("duplicate_name")
        test["flags"] = sorted(test["flags"])
    return sorted(tests, key=lambda t: (t["line"], t["name"]))


def run_git(root: Path, args: list) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True, timeout=30, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def harness_install_time(root: Path) -> int | None:
    out = run_git(root, ["log", "--diff-filter=A", "--format=%ct", "--", ":(top,literal).harness/VERSION"])
    if not out:
        return None
    times = [int(line) for line in out.split() if line.isdigit()]
    return min(times) if times else None


def commit_info(root: Path, rel: str) -> tuple:
    out = run_git(root, ["log", "-1", "--format=%ct %cI", "--", f":(literal){rel}"])
    if not out or not out.strip():
        return None, None
    stamp, _, iso = out.strip().partition(" ")
    return (int(stamp), iso) if stamp.isdigit() and iso else (None, None)


def runner_candidates(root: Path, has_python_tests: bool) -> list:
    found = []
    pytest_evidence = None
    if (root / "pytest.ini").is_file():
        pytest_evidence = "pytest.ini"
    elif (root / "conftest.py").is_file():
        pytest_evidence = "conftest.py"
    elif (root / "pyproject.toml").is_file() and "[tool.pytest" in read_text(root / "pyproject.toml"):
        pytest_evidence = "pyproject.toml [tool.pytest"
    if pytest_evidence:
        found.append({"runner": "pytest", "command": "pytest", "evidence": pytest_evidence})
    elif has_python_tests:
        found.append({
            "runner": "unittest",
            "command": "python3 -m unittest discover",
            "evidence": "python test files without pytest configuration",
        })
    package = root / "package.json"
    if package.is_file():
        try:
            scripts = json.loads(read_text(package)).get("scripts")
        except (ValueError, AttributeError):
            scripts = None
        if isinstance(scripts, dict) and "test" in scripts:
            found.append({"runner": "npm", "command": "npm test", "evidence": "package.json scripts.test"})
    for marker, runner, command in (
        ("go.mod", "go", "go test ./..."),
        ("Cargo.toml", "cargo", "cargo test"),
        ("pom.xml", "maven", "mvn test"),
    ):
        if (root / marker).is_file():
            found.append({"runner": runner, "command": command, "evidence": marker})
    for marker in ("build.gradle", "build.gradle.kts"):
        if (root / marker).is_file():
            wrapper = (root / "gradlew").is_file()
            found.append({
                "runner": "gradle",
                "command": "./gradlew test" if wrapper else "gradle test",
                "evidence": marker + (", gradlew" if wrapper else ""),
            })
            break
    return found


def scan(root: Path) -> dict:
    root = Path(root)
    harness_time = harness_install_time(root)
    files = []
    inventory = []
    flag_totals = {}
    for rel in find_files(root):
        path = root / rel
        cache = []

        def load(path=path, cache=cache):
            if not cache:
                cache.append(read_text(path))
            return cache[0]

        try:
            language = classify(rel, load)
        except OSError:
            continue
        if language is None:
            if any(part in INVENTORY_DIRS for part in rel.parts[:-1]):
                inventory.append(rel.as_posix())
            continue
        parse_error = False
        try:
            tests = extract_tests(language, load())
        except OSError:
            continue
        except (SyntaxError, ValueError, RecursionError):
            tests, parse_error = [], True
        commit_time, last_commit = commit_info(root, rel.as_posix())
        predates = None if commit_time is None or harness_time is None else commit_time < harness_time
        for test in tests:
            for flag in test["flags"]:
                flag_totals[flag] = flag_totals.get(flag, 0) + 1
        files.append({
            "path": rel.as_posix(),
            "language": language,
            "last_commit": last_commit,
            "predates_harness": predates,
            "parse_error": parse_error,
            "tests": tests,
        })
    return {
        "root": str(root),
        "runner_candidates": runner_candidates(root, any(f["language"] == "python" for f in files)),
        "files": files,
        "inventory": sorted(inventory),
        "summary": {
            "files": len(files),
            "tests": sum(len(f["tests"]) for f in files),
            "flags": {flag: flag_totals[flag] for flag in sorted(flag_totals)},
        },
    }


def main(argv: list) -> int:
    parser = argparse.ArgumentParser(prog="test_scan.py")
    parser.add_argument("path", nargs="?", default=".")
    args = parser.parse_args(argv)
    root = Path(args.path)
    if not root.is_dir():
        print(f"test_scan: {args.path} is not an existing directory", file=sys.stderr)
        return 2
    print(json.dumps(scan(root), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
