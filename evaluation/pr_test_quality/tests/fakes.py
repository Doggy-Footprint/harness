import contextlib
import copy
import difflib
import hashlib
import json
import os
import re
import shlex
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOKEN = "sk-ant-oat01-TESTTOKEN-9f3b7c1d2e8a4b65"
MISSING = object()
HARNESS_REPO = {}

SPEC_CFG = {
    "mining": {
        "merged_after": "2026-07-01", "min_stars": 200, "per_repo_max": 3,
        "target_per_language": 40, "title_exclude": ["^Bump ", "(?i)^revert"],
    },
    "validation": {"repeats": 3, "timeout_s": 600},
    "eval": {"timeout_s": 900},
    "report": {"min_mutants": 10},
    "brief": {"model": "claude-opus-5-5", "effort": "medium", "attempts": 3, "timeout_s": 600},
    "usersim": {"model": "claude-opus-5-5", "effort": "medium", "timeout_s": 900},
    "judge": {"model": "claude-opus-5-5", "effort": "medium"},
    "agent": {
        "model": "claude-sonnet-5-5", "effort": "medium", "wall_clock_min": 180,
        "max_user_turns": 8, "concurrency": 3,
    },
    "gce": {"project": "harness-eval-d31ee3"},
    "gates": {"g1_max_b0_resolved": 0.80, "g2_min_valid": 0.50, "g3_min_consistency": 0.70,
              "g4_max_anchor_lowest": 0.50},
}


def deep_merge(base, over):
    out = copy.deepcopy(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def shipped_config():
    path = ROOT / "evaluation" / "pr_test_quality" / "config.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def spec_cfg(data_dir=None, **over):
    cfg = deep_merge(shipped_config(), SPEC_CFG)
    if data_dir is not None:
        cfg["data_dir"] = str(data_dir)
    return deep_merge(cfg, over) if over else cfg


def find(obj, *needles):
    """First value whose key contains every needle (case-insensitive), depth-first."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            low = str(key).lower()
            if all(n in low for n in needles):
                return value
        for value in obj.values():
            hit = find(value, *needles)
            if hit is not MISSING:
                return hit
    elif isinstance(obj, list):
        for value in obj:
            hit = find(value, *needles)
            if hit is not MISSING:
                return hit
    return MISSING


def find_str_key(obj, *needles):
    """First (key, str value) whose key contains every needle."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(value, str) and all(n in str(key).lower() for n in needles):
                return key, value
        for value in obj.values():
            hit = find_str_key(value, *needles)
            if hit:
                return hit
    return None


def set_token_file(cfg, tmp):
    """Point whichever cfg key names the OAuth token file at a temp file and return its path."""
    path = Path(tmp) / "oauth_token"
    path.write_text(TOKEN, encoding="utf-8")
    path.chmod(0o600)

    def rewrite(node):
        hit = False
        if isinstance(node, dict):
            for key, value in list(node.items()):
                if isinstance(value, str) and "token" in str(key).lower():
                    node[key] = str(path)
                    hit = True
                elif isinstance(value, dict):
                    hit = rewrite(value) or hit
        return hit

    if not rewrite(cfg):
        cfg.setdefault("agent", {})["token_file"] = str(path)
        cfg.setdefault("gce", {})["token_file"] = str(path)
    return path


def sha256(text):
    data = text if isinstance(text, bytes) else text.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def udiff(path, old, new):
    """git-style unified diff built with difflib (independent of the code under test)."""
    a = [] if old is None else old.splitlines(keepends=True)
    b = [] if new is None else new.splitlines(keepends=True)
    head = ["diff --git a/%s b/%s\n" % (path, path)]
    if old is None:
        head.append("new file mode 100644\n")
    if new is None:
        head.append("deleted file mode 100644\n")
    fa = "/dev/null" if old is None else "a/" + path
    fb = "/dev/null" if new is None else "b/" + path
    body = list(difflib.unified_diff(a, b, fa, fb, n=3))
    return "".join(head + body)


def diff_files(diff):
    """Paths named by `diff --git` headers, in order."""
    return [m.group(1) for m in re.finditer(r"^diff --git a/(\S+) b/\S+$", diff, re.M)]


class TmpCase(unittest.TestCase):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def cfg(self, **over):
        return spec_cfg(self.tmp / "data", **over)


class FakeCall:
    """Scripted `call_fn`: items are str, Exception (raised) or callables(prompt) -> str."""

    def __init__(self, script, *, repeat_last=True):
        self.script = list(script) if isinstance(script, (list, tuple)) else [script]
        self.repeat_last = repeat_last
        self.calls = []
        self.lock = threading.Lock()

    def __call__(self, prompt, *, model, effort, timeout_s):
        with self.lock:
            self.calls.append({"prompt": prompt, "model": model, "effort": effort, "timeout_s": timeout_s})
            idx = len(self.calls) - 1
            if idx >= len(self.script):
                if not self.repeat_last:
                    raise AssertionError("call_fn called more often than scripted")
                idx = len(self.script) - 1
            item = self.script[idx]
        if isinstance(item, BaseException):
            raise item
        if callable(item):
            return item(prompt)
        return item

    @property
    def prompts(self):
        return [c["prompt"] for c in self.calls]


class FakeRun:
    def __init__(self, handler=None):
        self.handler = handler
        self.calls = []

    def __call__(self, argv, *, input=None, timeout=None):
        self.calls.append({"argv": list(argv), "input": input, "timeout": timeout})
        if self.handler:
            out = self.handler(list(argv), input)
            if out is not None:
                return out
        return 0, "", ""

    @property
    def argvs(self):
        return [c["argv"] for c in self.calls]

    def all_text(self):
        return "\n".join(" ".join(c["argv"]) for c in self.calls)


class DockerError(RuntimeError):
    pass


class DockerUnreachable(RuntimeError):
    pass


class ImageMissing(RuntimeError):
    pass


class FakeContainer:
    def __init__(self, docker, name, image, kwargs):
        self.docker = docker
        self.name = name
        self.image = image
        self.kwargs = kwargs
        self.fs = {}
        self.staged = []
        self.execs = []
        self.out_files = {}
        self.junit_xml = None
        self.alive = True
        self.driver_inputs = []
        self.copied = []
        self.reads = []
        self.copyouts = []

    def _stage(self, kind, dest, text):
        with self.docker.lock:
            self.staged.append((kind, dest, text))
            self.docker.staged_all.append((kind, dest, text))

    def files(self):
        return {p: b.decode("utf-8", "replace") for p, b in self.fs.items()}

    def tree_text(self):
        return "\n".join(self.files().values())

    def write_text(self, dest, text):
        self._stage("write", dest, text)
        self.fs[dest] = text.encode("utf-8")

    def copy_in(self, local, dest):
        local = Path(local)
        if local.is_dir():
            for item in sorted(local.rglob("*")):
                if item.is_file():
                    target = dest.rstrip("/") + "/" + item.relative_to(local).as_posix()
                    data = item.read_bytes()
                    self._stage("copy", target, data.decode("utf-8", "replace"))
                    self.fs[target] = data
            return
        data = local.read_bytes()
        if dest.endswith("/"):
            dest = dest + local.name
        self._stage("copy", dest, data.decode("utf-8", "replace"))
        self.copied.append((dest, data))
        self.fs[dest] = data

    def _agent_state(self):
        fn = getattr(self.docker, "agent_state", None)
        return fn(self) if fn else None

    def read_bytes(self, src):
        self.reads.append(src)
        state = self._agent_state()
        if state is not None and src.startswith("/testbed/"):
            entry = state.get(src[len("/testbed/"):])
            if entry is not None:
                return entry[1].encode("utf-8") if entry[1] is not None else None
        if src.endswith(".xml") and self.junit_xml is not None:
            return self.junit_xml.encode("utf-8")
        if src in self.fs:
            return self.fs[src]
        base = src.rsplit("/", 1)[-1]
        if base in self.out_files:
            return self.out_files[base]
        return None

    def copy_out(self, src, local):
        self.copyouts.append(src)
        local = Path(local)
        if src.endswith(".xml") and self.junit_xml is not None:
            local.parent.mkdir(parents=True, exist_ok=True)
            target = local / src.rsplit("/", 1)[-1] if local.is_dir() else local
            target.write_text(self.junit_xml, encoding="utf-8")
            return
        local.mkdir(parents=True, exist_ok=True)
        for name, data in self.out_files.items():
            target = local / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        hook = getattr(self.docker, "copy_out_hook", None)
        if hook:
            hook(local)

    def exec(self, argv, *, timeout=None, user=None, workdir=None):
        argv = list(argv)
        joined = " ".join(argv)
        with self.docker.lock:
            self.execs.append({"argv": argv, "timeout": timeout, "user": user, "workdir": workdir})
            self.docker.staged_all.append(("exec", joined, joined))
        policy = self.docker.exec_policy
        if policy:
            out = policy(self, argv)
            if out is not None:
                return out
        if re.search(r"\brm\b", joined):
            try:
                tokens = argv + shlex.split(joined)
            except ValueError:
                tokens = argv
            for tok in tokens:
                self.fs.pop(tok, None)
        if self.docker.driver_policy and re.search(r"python[\d.]*\s+(-\S+\s+)*\S*driver", joined):
            return self._run_driver(timeout)
        if any(k in joined for k in ("pytest", "vitest", "jest", "gotestsum", "nextest", "go test", "cargo test")):
            return self._run_tests(timeout)
        state = self._agent_state()
        if state is not None and argv[:1] == ["git"] and "show" in argv:
            path = argv[-1].split(":", 1)[-1]
            base = state.get(path, (None, None))[0]
            return (0, base, False) if base is not None else (128, "fatal: path not in start commit", False)
        if state is not None and argv[:1] == ["git"] and "diff" in argv and "--name-status" not in argv:
            return 0, "".join(udiff(p, b, a) for p, (b, a) in sorted(state.items())), False
        if argv[:1] == ["git"] and "rev-parse" in argv:
            return 0, "0123456789abcdef0123456789abcdef01234567\n", False
        if argv[:1] == ["git"] and "diff" in argv:
            return 0, self.docker.diff_text(self) if callable(self.docker.diff_text) else self.docker.diff_text, False
        return 0, "", False

    def _run_tests(self, timeout):
        pol = self.docker.junit_policy
        if pol is None:
            return 0, "", False
        out = pol(self)
        if out == "timeout":
            return None, "", True
        self.junit_xml = out
        return (self.docker.junit_exit if out is not None else 1), "", False

    def _run_driver(self, timeout):
        raw = None
        for path, data in self.fs.items():
            if path.endswith("input.json"):
                raw = data.decode("utf-8")
        inp = json.loads(raw) if raw else None
        self.driver_inputs.append(inp)
        if self.docker.driver_delay:
            time.sleep(self.docker.driver_delay)
        outcome = self.docker.driver_policy(self, inp)
        self.out_files.update(outcome.get("files", {}))
        if outcome.get("timed_out"):
            return None, "", True
        return outcome.get("exit", 0), outcome.get("output", ""), False

    def start(self):
        self.alive = True

    def stop(self):
        pass

    def remove(self):
        self.docker._release(self)


class FakeDocker:
    """Module-like object with the docker_exec surface; records every call."""

    DockerError = DockerError
    DockerUnreachable = DockerUnreachable
    ImageMissing = ImageMissing

    def __init__(self, *, exec_policy=None, driver_policy=None, junit_policy=None, diff_text="",
                 driver_delay=0.0, missing_images=()):
        self.exec_policy = exec_policy
        self.driver_policy = driver_policy
        self.junit_policy = junit_policy
        self.diff_text = diff_text
        self.driver_delay = driver_delay
        self.junit_exit = 0
        self.missing_images = set(missing_images)
        self.lock = threading.Lock()
        self.containers = []
        self.agent_started = []
        self.proxies = []
        self.networks = []
        self.log = []
        self.live = 0
        self.max_live = 0
        self.agent_live = 0
        self.agent_max = 0
        self.staged_all = []
        self.counter = 0

    def _new(self, image, kwargs, name=None):
        with self.lock:
            self.counter += 1
            cont = FakeContainer(self, name or "c%d" % self.counter, image, kwargs)
            self.containers.append(cont)
            self.live += 1
            self.max_live = max(self.max_live, self.live)
        return cont

    def _release(self, cont):
        with self.lock:
            if cont.alive:
                cont.alive = False
                self.live -= 1
                if getattr(cont, "is_agent", False):
                    self.agent_live -= 1

    @property
    def runs(self):
        return len(self.containers)

    def image_id(self, image):
        self.log.append(("image_id", image))
        if image in self.missing_images:
            raise ImageMissing(image)
        return "sha256:" + hashlib.sha256(image.encode()).hexdigest()

    @contextlib.contextmanager
    def container(self, image, *, network=False):
        cont = self._new(image, {"network": network})
        try:
            yield cont
        finally:
            self._release(cont)

    def start_container(self, image, *, name, network, labels, cpus, memory, mounts):
        cont = self._new(image, {"network": network, "labels": dict(labels), "cpus": cpus,
                                 "memory": memory, "mounts": list(mounts)}, name)
        self.agent_started.append(cont)
        with self.lock:
            cont.is_agent = True
            self.agent_live += 1
            self.agent_max = max(self.agent_max, self.agent_live)
        with self.lock:
            self.staged_all.append(("start_container", name, json.dumps(
                {"image": image, "network": network, "labels": labels, "cpus": str(cpus),
                 "memory": memory, "mounts": list(mounts)}, sort_keys=True)))
        return cont

    def Container(self, name):
        for c in reversed(self.containers):
            if c.name == name:
                return c
        raise DockerError("no such container: %s" % name)

    def container_exists(self, name):
        return any(c.name == name and c.alive for c in self.containers)

    def remove_container(self, name):
        for c in self.containers:
            if c.name == name:
                self._release(c)

    def ensure_network(self, name, internal=True):
        self.networks.append((name, internal))

    def start_proxy(self, image, *, name, networks, labels, conf_text):
        self.proxies.append({"image": image, "name": name, "networks": list(networks),
                             "labels": dict(labels), "conf_text": conf_text})
        with self.lock:
            self.staged_all.append(("proxy", name, conf_text))
        return self._new(image, {"proxy": True}, name)

    def build(self, context_dir, tag, *, timeout):
        self.log.append(("build", str(context_dir), tag, timeout))
        return 0, "ok"

    def staged_text(self):
        return "\n".join(t for _, _, t in self.staged_all) + "\n" + "\n".join(d for _, d, _ in self.staged_all)


def pytest_junit(results):
    """JUnit XML in pytest's shape for ids `<file>::[<Class>::]<name>`."""
    cases = []
    for tid, status in results.items():
        parts = tid.split("::")
        file, name = parts[0], parts[-1]
        mid = ".".join(parts[1:-1])
        classname = file[:-3].replace("/", ".") + ("." + mid if mid else "")
        inner = {"pass": "", "fail": '<failure message="boom">x</failure>',
                 "error": '<error message="boom">x</error>', "skip": '<skipped message="s"/>'}[status]
        cases.append('<testcase classname="%s" name="%s" file="%s" time="0.01">%s</testcase>'
                     % (classname, name.replace('"', "&quot;"), file, inner))
    return ('<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite name="pytest" tests="%d">%s'
            "</testsuite></testsuites>" % (len(cases), "".join(cases)))


def snapshot(root):
    root = Path(root)
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


GOLD_SRC_PY = "def clamp(value, lo, hi):\n    return max(lo, min(value, hi))\n"
BASE_SRC_PY = "def identity(value):\n    return value\n"

LANG_FIXTURES = {
    "python": {
        "src_path": "src/calc/ops.py",
        "src_old": BASE_SRC_PY,
        "src_new": BASE_SRC_PY + "\n\ndef clamp(value, lo, hi):\n    return max(lo, min(value, hi))\n",
        "test_path": "tests/test_ops.py",
        "test_new": (
            "from calc.ops import clamp\n\n\n"
            "def build_gold_fixture_zq():\n    return [1, 2, 3]\n\n\n"
            "def test_clamp_upper_bound_zq():\n"
            "    title = \"plain-not-forbidden-yy\"\n"
            "    assert describe(5) == \"five-marker-zq\"\n"
            "    assert tag(1) == \"ab\"\n"
            "    assert tag(2) == \"  x \"\n\n\n"
            "def test_param_case_zq(case):\n    assert case\n"),
        "f2p": ["tests/test_ops.py::test_clamp_upper_bound_zq", "tests/test_ops.py::test_param_case_zq[3-x]"],
        "name": "test_clamp_upper_bound_zq",
        "defined": "build_gold_fixture_zq",
        "literal": "five-marker-zq",
        "plain": "plain-not-forbidden-yy",
    },
    "typescript": {
        "src_path": "src/ops.ts",
        "src_old": "export const IDENT = 1;\n",
        "src_new": ("export const IDENT = 1;\n"
                    "export function clamp(value: number, lo: number, hi: number): number {\n"
                    "  return Math.max(lo, Math.min(value, hi));\n}\n"),
        "test_path": "src/ops.test.ts",
        "test_new": (
            "import { clamp } from \"./ops\";\n"
            "function buildGoldFixtureZq() { return [1, 2, 3]; }\n"
            "describe(\"clamp\", () => {\n"
            "  it(\"caps at upper bound zq\", () => {\n"
            "    const title = \"plain-not-forbidden-yy\";\n"
            "    expect(describeNum(5)).toBe(\"five-marker-zq\");\n"
            "    expect(tag(1)).toBe(\"ab\");\n"
            "  });\n});\n"),
        "f2p": ["src/ops.test.ts::clamp::caps at upper bound zq"],
        "name": "caps at upper bound zq",
        "defined": "buildGoldFixtureZq",
        "literal": "five-marker-zq",
        "plain": "plain-not-forbidden-yy",
    },
    "go": {
        "src_path": "ops/ops.go",
        "src_old": "package ops\n\nfunc identity(v int) int { return v }\n",
        "src_new": ("package ops\n\nfunc identity(v int) int { return v }\n\n"
                    "func Clamp(value, lo, hi int) int {\n\tif value < lo {\n\t\treturn lo\n\t}\n"
                    "\tif value > hi {\n\t\treturn hi\n\t}\n\treturn value\n}\n"),
        "test_path": "ops/ops_test.go",
        "test_new": (
            "package ops\n\nimport (\n\t\"testing\"\n\t\"github.com/stretchr/testify/assert\"\n)\n\n"
            "func buildGoldFixtureZq() []int { return []int{1, 2, 3} }\n\n"
            "func TestClampUpperZq(t *testing.T) {\n"
            "\ttitle := \"plain-not-forbidden-yy\"\n"
            "\tassert.Equal(t, Describe(5), \"five-marker-zq\")\n"
            "\tassert.Equal(t, Tag(1), \"ab\")\n}\n"),
        "f2p": ["ops::TestClampUpperZq"],
        "name": "TestClampUpperZq",
        "defined": "buildGoldFixtureZq",
        "literal": "five-marker-zq",
        "plain": "plain-not-forbidden-yy",
    },
    "rust": {
        "src_path": "src/lib.rs",
        "src_old": "fn identity(v: i32) -> i32 { v }\n",
        "src_new": ("fn identity(v: i32) -> i32 { v }\n\n"
                    "pub fn clamp(value: i32, lo: i32, hi: i32) -> i32 {\n    value.max(lo).min(hi)\n}\n"),
        "test_path": "tests/clamp.rs",
        "test_new": (
            "use calc::clamp;\n\n"
            "fn build_gold_fixture_zq() -> Vec<i32> { vec![1, 2, 3] }\n\n"
            "#[test]\nfn clamps_upper_zq() {\n"
            "    let title = \"plain-not-forbidden-yy\";\n"
            "    assert_eq!(describe(5), \"five-marker-zq\");\n"
            "    assert_eq!(tag(1), \"ab\");\n}\n"),
        "f2p": ["clamp::clamps_upper_zq"],
        "name": "clamps_upper_zq",
        "defined": "build_gold_fixture_zq",
        "literal": "five-marker-zq",
        "plain": "plain-not-forbidden-yy",
    },
}

MERGE_SHA = "c0ffee00c0ffee00c0ffee00c0ffee00c0ffee11"
BASE_SHA = "ba5e0000ba5e0000ba5e0000ba5e0000ba5e0022"


def make_task(language="python", *, pr=7, repo="acme/calc", brief=None, mutants=None, **over):
    fx = LANG_FIXTURES[language]
    src_diff = udiff(fx["src_path"], fx["src_old"], fx["src_new"])
    test_diff = udiff(fx["test_path"], None, fx["test_new"])
    owner, name = repo.split("/")
    task = {
        "task_id": "%s__%s-%d" % (owner, name, pr),
        "language": language, "repo": repo, "pr": pr,
        "base_sha": BASE_SHA, "merge_sha": MERGE_SHA,
        "image": "eval/%s__%s:%s" % (owner, name, BASE_SHA[:12]),
        "recipe": None,
        "gold_patch": src_diff + test_diff,
        "gold_split": {"src": src_diff, "tests": test_diff, "harness": "", "other": ""},
        "gold_base": {fx["src_path"]: fx["src_old"], fx["test_path"]: None},
        "gold_after": {fx["src_path"]: fx["src_new"], fx["test_path"]: fx["test_new"]},
        "f2p": list(fx["f2p"]), "p2p": [],
        "valid": True, "reason": "", "brief": brief, "mutants": mutants or [], "pilot": False,
    }
    task.update(over)
    return task


def interface_request(task):
    """Request text that names each interface signature and its path, ends with the closing sentence."""
    from evaluation.pr_test_quality import brief as brief_mod
    sigs = brief_mod.interface_signatures(task["language"], task["gold_split"]["src"])
    parts = ["I need a small helper added to the library."]
    for s in sigs:
        parts.append("Please add %s in %s." % (s["signature"], s["path"]))
    parts.append("It should keep the value inside the given range.")
    parts.append("Implement this and add automated tests.")
    return " ".join(parts)


def brief_json(task, request=None, statements=None, ambiguous=None):
    if statements is None:
        statements = [{"id": "S%d" % (i + 1), "text": "Behavior number %d holds." % (i + 1), "f2p": [t]}
                      for i, t in enumerate(task["f2p"])]
    if ambiguous is None:
        ambiguous = ["S2"] if len(statements) >= 2 else []
    return json.dumps({
        "request": request if request is not None else interface_request(task),
        "statements": statements,
        "ambiguous": ambiguous,
    })


class RelayFs:
    """In-memory container whose exec understands the handful of POSIX tools a relay poller may use."""

    def __init__(self):
        self.fs = {}
        self.polled = []
        self.lock = threading.Lock()
        self.staged = []

    def _children(self, directory):
        directory = directory.rstrip("/")
        with self.lock:
            return sorted(p.rsplit("/", 1)[1] for p in self.fs if p.rsplit("/", 1)[0] == directory)

    def _note(self, directory):
        with self.lock:
            if directory not in self.polled:
                self.polled.append(directory)

    def _simple(self, tokens):
        if not tokens:
            return 0, ""
        cmd, args = tokens[0], tokens[1:]
        paths = [a for a in args if a.startswith("/")]
        if cmd == "ls":
            if paths:
                self._note(paths[-1].rstrip("/"))
                return 0, "\n".join(self._children(paths[-1])) + "\n"
            return 0, ""
        if cmd == "find":
            if paths:
                self._note(paths[0].rstrip("/"))
                pattern = args[args.index("-name") + 1] if "-name" in args else "*"
                import fnmatch
                return 0, "".join(paths[0].rstrip("/") + "/" + n + "\n" for n in self._children(paths[0])
                                  if fnmatch.fnmatch(n, pattern))
            return 0, ""
        if cmd == "cat":
            data = self.fs.get(paths[0]) if paths else None
            return (0, data.decode("utf-8")) if data is not None else (1, "cat: no such file\n")
        if cmd == "rm":
            for p in paths:
                self.fs.pop(p, None)
            return 0, ""
        if cmd == "mv" and len(paths) == 2:
            data = self.fs.pop(paths[0], None)
            if data is None:
                return 1, "mv: no such file\n"
            self.fs[paths[1]] = data
            return 0, ""
        if cmd in ("test", "[") and paths:
            return (0 if paths[0] in self.fs else 1), ""
        return 0, ""

    def exec(self, argv, *, timeout=None, user=None, workdir=None):
        argv = list(argv)
        self.staged.append(" ".join(argv))
        if argv[:2] in (["sh", "-c"], ["bash", "-c"]) and len(argv) > 2:
            code, out = 0, ""
            for part in re.split(r"&&|;|\n", argv[2]):
                try:
                    toks = shlex.split(part)
                except ValueError:
                    continue
                code, o = self._simple(toks)
                out += o
                if code:
                    break
            return code, out, False
        code, out = self._simple(argv)
        return code, out, False

    def write_text(self, dest, text):
        self.staged.append(text)
        with self.lock:
            self.fs[dest] = text.encode("utf-8")

    def copy_in(self, local, dest):
        data = Path(local).read_bytes()
        if dest.endswith("/"):
            dest += Path(local).name
        self.staged.append(data.decode("utf-8", "replace"))
        with self.lock:
            self.fs[dest] = data

    def read_bytes(self, src):
        self._note(src.rsplit("/", 1)[0])
        with self.lock:
            return self.fs.get(src)

    def copy_out(self, src, local):
        local = Path(local)
        data = self.fs.get(src)
        if data is not None:
            local.parent.mkdir(parents=True, exist_ok=True)
            (local / src.rsplit("/", 1)[1] if local.is_dir() else local).write_bytes(data)

    def start(self):
        pass

    def stop(self):
        pass

    def remove(self):
        pass

    def put_request(self, directory, n, obj):
        with self.lock:
            self.fs["%s/req-%d.json" % (directory.rstrip("/"), n)] = json.dumps(obj).encode("utf-8")

    def responses(self, directory):
        out = {}
        with self.lock:
            for path, data in self.fs.items():
                if path.rsplit("/", 1)[0] == directory.rstrip("/") and path.rsplit("/", 1)[1].startswith("resp-") \
                        and path.endswith(".json"):
                    out[path.rsplit("/", 1)[1]] = data.decode("utf-8")
        return out

    def wait_for(self, predicate, timeout=10.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = predicate()
            if value:
                return value
            time.sleep(0.01)
        return predicate()


@contextlib.contextmanager
def failing_replace(suffix):
    """Make rename/replace onto a path ending in `suffix` fail; every other rename works."""
    from unittest import mock
    real_replace, real_rename, real_path = os.replace, os.rename, Path.replace

    def guard(real):
        def inner(src, dst, *a, **k):
            if str(dst).endswith(suffix):
                raise OSError("simulated crash between write and rename")
            return real(src, dst, *a, **k)
        return inner

    def path_inner(self, target):
        if str(target).endswith(suffix):
            raise OSError("simulated crash between write and rename")
        return real_path(self, target)

    with mock.patch("os.replace", guard(real_replace)), mock.patch("os.rename", guard(real_rename)), \
            mock.patch.object(Path, "replace", path_inner):
        yield
