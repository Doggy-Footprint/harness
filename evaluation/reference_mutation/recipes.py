import hashlib
import json
import re
import shlex
import shutil
from pathlib import Path

from . import atomic_write, section
from . import languages
from .languages import LANGUAGES

DOCKER_DIR = Path(__file__).parent / "docker"
TESTBED = "/testbed"
JUNIT_DEFAULT = "/tmp/evaluation-junit.xml"
NEXTEST_CONFIG = "/opt/evaluation/nextest.toml"
DEFAULT_TOOLS = {
    "python": ["pytest==8.3.5", "pytest-cov==6.1.1", "hypothesis==6.131.0", "mutmut==2.5.1"],
    "typescript": ["@stryker-mutator/core@10.0.0", "fast-check@4.10.2"],
    "typescript_jest": ["jest-junit@17.0.0"],
    "typescript_mocha": ["mocha-junit-reporter@2.2.1"],
    "go": ["github.com/avito-tech/go-mutesting/cmd/go-mutesting@v0.0.0-20261002081621-9ce5f731e321",
           "gotest.tools/gotestsum@v1.13.0"],
    "rust": ["cargo-mutants@27.1.0", "cargo-nextest@0.9.149"],
    "rust_dev": ["proptest@1.7.0"],
    "managers": {"poetry": "poetry==2.1.3", "pdm": "pdm==2.24.0", "bun": "bun@1.2.0"},
}
IGNORES = {
    "python": ("__pycache__/", "*.pyc", ".pytest_cache/", ".hypothesis/", ".mutmut-cache", ".coverage", ".venv/"),
    "typescript": ("node_modules/", "reports/", ".stryker-tmp/", "coverage/"),
    "go": ("coverage.out",),
    "rust": ("target/", "mutants.out/"),
}
GO_FLOOR = (1, 24)
GIT_USER = ("evaluation", "evaluation@localhost")
BASE_IMAGES = {
    "python": "python:3.12-bookworm",
    "typescript": "node:22-bookworm",
    "go": "golang:1.24-bookworm",
    "rust": "rust:1-bookworm",
}


class RecipeError(RuntimeError):
    pass


def _json(text: str | None) -> dict:
    try:
        obj = json.loads(text or "{}")
    except ValueError:
        return {}
    return obj if isinstance(obj, dict) else {}


_PY_DEV_DEPS = (
    "import subprocess, tomllib; d = tomllib.load(open(\"pyproject.toml\", \"rb\")); "
    "g = d.get(\"dependency-groups\", {}); o = d.get(\"project\", {}).get(\"optional-dependencies\", {}); "
    "r = [x for k in (\"dev\", \"test\", \"tests\", \"testing\") for x in g.get(k, []) + o.get(k, [])] "
    "+ d.get(\"tool\", {}).get(\"uv\", {}).get(\"dev-dependencies\", []); "
    "r = [x for x in r if isinstance(x, str)]; "
    "r and subprocess.run([\".venv/bin/pip\", \"install\", *r], check=True)"
)


def _python(files: dict[str, str]) -> dict:
    manager = next((m for lock, m in (("uv.lock", "uv"), ("poetry.lock", "poetry"), ("pdm.lock", "pdm")) if lock in files), None)
    if manager is None:
        if not any(f in files for f in ("pyproject.toml", "requirements.txt", "setup.py", "setup.cfg")):
            raise RecipeError("no python manifest: expected uv.lock, poetry.lock, pdm.lock, pyproject.toml or requirements.txt")
        manager = "pip"
    install = {
        "uv": ["uv sync --frozen --all-extras --dev"],
        "poetry": ["poetry config virtualenvs.in-project true", "poetry install --no-interaction"],
        "pdm": ["pdm config venv.in_project true", "pdm install"],
        "pip": [
            "python -m venv .venv",
            ".venv/bin/pip install -e . || true",
            "if [ -f requirements.txt ]; then .venv/bin/pip install -r requirements.txt; fi",
            # Without a lock, test-only dependencies live in pyproject tables that `pip install -e .` skips.
            f"if [ -f pyproject.toml ]; then .venv/bin/python -c '{_PY_DEV_DEPS}' || true; fi",
        ],
    }[manager]
    return {
        "manager": manager, "install": install,
        "test": {"runner": "pytest", "argv_template": ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "--junitxml={junit}", "{selection}"]},
    }


def _typescript(files: dict[str, str]) -> dict:
    locks = (("pnpm-lock.yaml", "pnpm"), ("yarn.lock", "yarn"), ("bun.lock", "bun"), ("bun.lockb", "bun"), ("package-lock.json", "npm"))
    manager = next((m for lock, m in locks if lock in files), None)
    if manager is None:
        raise RecipeError("no lockfile: expected pnpm-lock.yaml, yarn.lock, bun.lock, bun.lockb or package-lock.json")
    pkg = _json(files.get("package.json"))
    deps = {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}
    if "vitest" in deps:
        runner = "vitest"
    elif "jest" in deps:
        runner = "jest"
    elif "mocha" in deps:
        runner = "mocha"
    elif "node --test" in str((pkg.get("scripts") or {}).get("test", "")):
        runner = "node-test"
    else:
        raise RecipeError("no supported test runner (vitest, jest, mocha, node --test)")
    bins = "./node_modules/.bin"
    install = {
        "npm": ["npm ci"],
        "pnpm": ["corepack enable", "pnpm install --frozen-lockfile"],
        "yarn": ["corepack enable", "yarn install --frozen-lockfile"],
        "bun": ["bun install --frozen-lockfile"],
    }[manager]
    if runner == "vitest":
        argv = [f"{bins}/vitest", "run", "--reporter=junit", "--outputFile={junit}", "{selection}"]
    elif runner == "jest":
        argv = [
            "env", "JEST_JUNIT_OUTPUT_FILE={junit}", "JEST_JUNIT_CLASSNAME={filepath}::{classname}",
            "JEST_JUNIT_TITLE={title}", "JEST_JUNIT_ANCESTOR_SEPARATOR= > ",
            f"{bins}/jest", "--ci", "--reporters=jest-junit", "--runTestsByPath", "--", "{selection}",
        ]
    elif runner == "mocha":
        argv = [f"{bins}/mocha", "--reporter", "mocha-junit-reporter", "--reporter-options",
                "mochaFile={junit}", "{selection}"]
    else:
        argv = ["node", "--test", "--test-reporter=junit", "--test-reporter-destination={junit}", "{selection}"]
    return {"manager": manager, "install": install, "test": {"runner": runner, "argv_template": argv}}


def _go(files: dict[str, str]) -> dict:
    if "go.mod" not in files:
        raise RecipeError("go.mod missing: cannot detect a go module")
    return {
        "manager": "go", "install": ["go mod download"],
        "test": {"runner": "gotestsum", "argv_template": ["gotestsum", "--junitfile={junit}", "--", "-count=1", "{selection}"]},
    }


def _rust(files: dict[str, str]) -> dict:
    if "Cargo.toml" not in files:
        raise RecipeError("Cargo.toml missing: cannot detect a cargo project")
    return {
        "manager": "cargo", "install": ["cargo fetch"],
        "test": {"runner": "cargo-nextest", "argv_template": ["{nextest}"]},
    }


_DETECT = {"python": _python, "typescript": _typescript, "go": _go, "rust": _rust}


def _base_image(language: str, files: dict[str, str]) -> str:
    if language == "go":
        m = re.search(r"^go\s+(\d+)\.(\d+)", files.get("go.mod", ""), re.M)
        floor = max((int(m.group(1)), int(m.group(2))), GO_FLOOR) if m else GO_FLOOR
        return f"golang:{floor[0]}.{floor[1]}-bookworm"
    if language == "python":
        m = re.match(r"\s*(3\.\d+)", files.get(".python-version", ""))
        return f"python:{m.group(1)}-bookworm" if m else BASE_IMAGES[language]
    return BASE_IMAGES[language]


def detect(language: str, files: dict[str, str]) -> dict:
    if language not in LANGUAGES:
        raise RecipeError(f"unsupported language: {language}")
    recipe = _DETECT[language](files)
    return {"language": language, **recipe, "base_image": _base_image(language, files)}


def _selection_args(recipe: dict, selection: list[str]) -> list[str]:
    runner = recipe["test"]["runner"]
    if runner == "gotestsum":
        dirs = sorted({"./" + p.rsplit("/", 1)[0] if "/" in p else "." for p in selection})
        return dirs or ["./..."]
    return list(selection)


def _nextest_script(selection: list[str], junit_path: str) -> str:
    binaries = [Path(p).stem for p in selection if p.startswith("tests/") and p.endswith(".rs")]
    whole = len(binaries) != len(selection) or not selection
    filt = "" if whole else " -E " + shlex.quote(" | ".join(f"binary({b})" for b in binaries))
    return (
        f"cargo nextest run --config-file {NEXTEST_CONFIG} --profile junit --no-fail-fast{filt}; "
        f"rc=$?; cp {TESTBED}/target/nextest/junit/junit.xml {shlex.quote(junit_path)} 2>/dev/null; exit $rc"
    )


# The Node junit reporter records no file; wrapping each file's suites in a nameless <testsuite file=...> lets junit.parse build file-prefixed ids.
_NODE_MERGE = (
    "const fs=require('fs');const [dir,out,...files]=process.argv.slice(1);"
    "const esc=s=>s.replace(/&/g,'&amp;').replace(/\"/g,'&quot;').replace(/</g,'&lt;');"
    "let body='';files.forEach((f,k)=>{let x;try{x=fs.readFileSync(dir+'/'+k+'.xml','utf8')}catch(e){return}"
    "x=x.replace(/<\\?xml[^>]*\\?>/,'').replace(/<\\/?testsuites\\b[^>]*>/g,'');"
    "body+='<testsuite name=\"\" file=\"'+esc(f)+'\">'+x+'</testsuite>'});"
    "if(body)fs.writeFileSync(out,'<testsuites>'+body+'</testsuites>')"
)


def _node_test_script(selection: list[str], junit_path: str) -> str:
    files = " ".join(shlex.quote(p) for p in selection)
    return (
        'd=$(mktemp -d); rc=0; k=0; '
        f"for f in {files}; do "
        'node --test --test-reporter=junit --test-reporter-destination="$d/$k.xml" "$f" || rc=1; k=$((k+1)); done; '
        f"node -e {shlex.quote(_NODE_MERGE)} \"$d\" {shlex.quote(junit_path)} {files}; exit $rc"
    )


def test_argv(recipe: dict, selection: list[str], junit_path: str) -> list[str]:
    template = recipe["test"]["argv_template"]
    if recipe["test"]["runner"] == "cargo-nextest":
        return ["sh", "-c", _nextest_script(selection, junit_path)]
    if recipe["test"]["runner"] == "node-test":
        return ["sh", "-c", _node_test_script(selection, junit_path)]
    out: list[str] = []
    for token in template:
        if token == "{selection}":
            out += _selection_args(recipe, selection)
        else:
            out.append(token.replace("{junit}", junit_path))
    return out


_NEXTEST_TOML = "printf '%s\\n' '[profile.junit.junit]' 'path = \"junit.xml\"'"


def _tools(cfg: dict) -> dict:
    return {**DEFAULT_TOOLS, **((cfg or {}).get("tools") or {})}


def _tool_steps(recipe: dict, tools: dict) -> list[str]:
    language, manager = recipe["language"], recipe["manager"]
    if language == "python":
        spec = " ".join(shlex.quote(t) for t in tools["python"])
        return [f"RUN {({'uv': 'uv pip install', 'poetry': 'poetry run pip install', 'pdm': 'pdm run pip install', 'pip': '.venv/bin/pip install'})[manager]} {spec}"]
    if language == "typescript":
        runner = recipe["test"]["runner"]
        extra = list(tools["typescript"]) + list(tools.get({"jest": "typescript_jest", "mocha": "typescript_mocha"}.get(runner, ""), []))
        spec = " ".join(extra)
        # yarn classic and pnpm refuse to add to a workspace root without -W / -w; yarn berry rejects -W.
        add = {"npm": f"npm install --no-save {spec}", "pnpm": f"(pnpm add -D -w {spec} || pnpm add -D {spec})",
               "yarn": f"(yarn add -D -W {spec} || yarn add -D {spec})", "bun": f"bun add -d {spec}"}[manager]
        return [f"RUN {add}"]
    if language == "go":
        return [f"RUN GOTOOLCHAIN=auto GOBIN=/usr/local/bin go install {tool}" for tool in tools["go"]]
    mutants_tools = " ".join(tools["rust"])
    dev = " ".join(tools["rust_dev"])
    return [
        f"RUN cd / && CARGO_INSTALL_ROOT=/usr/local cargo install --locked {mutants_tools}",
        f"RUN mkdir -p /opt/evaluation && {_NEXTEST_TOML} > {NEXTEST_CONFIG}",
        "RUN cp Cargo.toml /tmp/Cargo.toml.orig && (cp Cargo.lock /tmp/Cargo.lock.orig || true) "
        f"&& (cargo add --dev {dev} && cargo fetch || true) "
        "&& cp /tmp/Cargo.toml.orig Cargo.toml && (cp /tmp/Cargo.lock.orig Cargo.lock || rm -f Cargo.lock)",
    ]


def _manifest_guard(recipe: dict) -> tuple[list[str], list[str]]:
    if recipe["language"] != "typescript":
        return [], []
    names = {"npm": ["package.json", "package-lock.json"], "pnpm": ["package.json", "pnpm-lock.yaml"],
             "yarn": ["package.json", "yarn.lock"], "bun": ["package.json", "bun.lock", "bun.lockb"]}[recipe["manager"]]
    save = "mkdir -p /tmp/manifests && for f in " + " ".join(names) + "; do [ -f $f ] && cp $f /tmp/manifests/$f; done; true"
    restore = "for f in " + " ".join(names) + "; do [ -f /tmp/manifests/$f ] && cp /tmp/manifests/$f $f; done; true"
    return [f"RUN {save}"], [f"RUN {restore}"]


def dockerfile(recipe: dict, cfg: dict) -> str:
    save, restore = _manifest_guard(recipe)
    pre = ["RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates curl build-essential pkg-config libssl-dev && rm -rf /var/lib/apt/lists/*"]
    if recipe["language"] == "rust":
        # Build scripts of common crates (libz-sys via cmake, bindgen via libclang, prost via protoc) need these.
        pre.append("RUN apt-get update && apt-get install -y --no-install-recommends cmake clang libclang-dev protobuf-compiler && rm -rf /var/lib/apt/lists/*")
    if recipe["manager"] == "uv":
        pre.append("COPY --from=ghcr.io/astral-sh/uv:0.6.5 /uv /usr/local/bin/uv")
    tools = _tools(cfg)
    managers = tools["managers"]
    if recipe["manager"] in ("poetry", "pdm"):
        pre.append(f"RUN pip install --no-cache-dir {managers[recipe['manager']]}")
    if recipe["manager"] == "bun":
        pre.append(f"RUN npm install -g {managers['bun']}")
    env = []
    if recipe["language"] == "python":
        env.append(f"ENV PATH={TESTBED}/.venv/bin:$PATH VIRTUAL_ENV={TESTBED}/.venv")
    if recipe["language"] == "typescript":
        env.append(f"ENV PATH={TESTBED}/node_modules/.bin:$PATH")
    installs = [f"RUN {cmd}" for cmd in recipe["install"]]
    user, email = GIT_USER
    commit = (
        "RUN rm -rf .git && git init -q && git add -A "
        f"&& git -c user.name={user} -c user.email={email} commit -q -m 'evaluation: base tree' "
        "&& git config --system --add safe.directory /testbed "
        f"&& git config --system core.excludesFile /etc/evaluation-gitignore"
    )
    patterns = r"\n".join(IGNORES[recipe["language"]]) + r"\n"
    ignore = f"RUN printf '{patterns}' > /etc/evaluation-gitignore"
    writable = {"go": " /go", "rust": " /usr/local/cargo"}.get(recipe["language"], "")
    chown = (
        "RUN (id nonroot >/dev/null 2>&1 || useradd -m nonroot) "
        f"&& chown -R nonroot:nonroot /testbed && chmod -R a+rwX{writable or ' /testbed'}"
    )
    lines = [
        f"FROM {recipe['base_image']}",
        *pre,
        f"WORKDIR {TESTBED}",
        "COPY repo/ /testbed/",
        *env,
        *save, *installs, *_tool_steps(recipe, tools), *restore,
        ignore, commit, chown,
    ]
    return "\n".join(lines) + "\n"


def agent_dockerfile(project_image: str, tools_image: str) -> str:
    text = (DOCKER_DIR / "agent.Dockerfile").read_text()
    return text.replace("{{PROJECT}}", project_image).replace("{{TOOLS}}", tools_image)


def tools_dockerfile() -> str:
    return (DOCKER_DIR / "tools.Dockerfile").read_text()


def _digest(*parts: str) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update(part.encode())
        h.update(b"\0")
    return h.hexdigest()[:12]


def image_name(task_id: str, recipe: dict, cfg: dict) -> str:
    return f"evaluation-proj.{task_id.lower()}:{_digest(dockerfile(recipe, cfg))}"


def agent_image_name(project_image: str) -> str:
    repo, _, tag = project_image.rpartition(":")
    return f"{repo.replace('evaluation-proj.', 'evaluation-agent.', 1)}:{tag}"


def tools_image_name() -> str:
    return f"evaluation-tools:{_digest(tools_dockerfile())}"


def _git(run_fn, argv: list[str], cwd: str, timeout: int = 900) -> str:
    code, out, err = run_fn(["git", "-C", cwd, *argv], timeout=timeout)
    if code != 0:
        raise RecipeError(f"git {' '.join(argv)} failed: {(err or out).strip()[-300:]}")
    return out


def _manifest_files(run_fn, repo_dir: str, sha: str) -> dict[str, str]:
    names = (
        "uv.lock", "poetry.lock", "pdm.lock", "pyproject.toml", "requirements.txt", "setup.py", "setup.cfg",
        ".python-version", "pnpm-lock.yaml", "yarn.lock", "bun.lock", "bun.lockb", "package-lock.json",
        "package.json", "go.mod", "Cargo.toml", "rust-toolchain", "rust-toolchain.toml",
    )
    out = {}
    for name in names:
        code, text, _ = run_fn(["git", "-C", repo_dir, "show", f"{sha}:{name}"], timeout=60)
        if code == 0:
            out[name] = text
    return out


class Undecodable(ValueError):
    pass


def _read_at(run_fn, repo_dir: str, sha: str, path: str) -> str | None:
    try:
        code, text, _ = run_fn(["git", "-C", repo_dir, "show", f"{sha}:{path}"], timeout=60)
    except UnicodeDecodeError as exc:
        raise Undecodable(path) from exc
    if code != 0:
        return None
    if "\ufffd" in text:
        raise Undecodable(path)
    return text


def build_task(candidate: dict, *, docker, cfg: dict, run_fn, work_dir, log_dir) -> dict:
    language, repo = candidate["language"], candidate["repo"]
    task_id = f"{repo.replace('/', '__')}-{candidate['pr']}"
    base = {"task_id": task_id, "language": language, "repo": repo, "pr": candidate["pr"],
            "base_sha": candidate["base_sha"], "merge_sha": candidate["merge_sha"],
            "title": candidate.get("title", ""), "body": candidate.get("body", ""),
            "issue_bodies": candidate.get("issue_bodies", []), "pilot": False}
    work = Path(work_dir) / task_id
    repo_dir = str(work / "src")
    try:
        if not (work / "src" / ".git").exists():
            work.mkdir(parents=True, exist_ok=True)
            code, out, err = run_fn(["git", "clone", "--quiet", f"https://github.com/{repo}.git", repo_dir], timeout=1800)
            if code != 0:
                raise RecipeError(f"git clone failed: {(err or out).strip()[-300:]}")
        recipe = detect(language, _manifest_files(run_fn, repo_dir, candidate["base_sha"]))
    except RecipeError as exc:
        return {**base, "valid": False, "reason": f"build_error: {exc}", "build_error": str(exc)}
    diff = _git(run_fn, ["diff", "--binary", "--no-color", "--no-ext-diff", "--no-renames", candidate["base_sha"], candidate["merge_sha"]], repo_dir)
    gold_base, gold_after, undecodable = {}, {}, set()
    for path in sorted({s.path for s in languages.parse_diff(diff)}):
        try:
            gold_base[path] = _read_at(run_fn, repo_dir, candidate["base_sha"], path)
            gold_after[path] = _read_at(run_fn, repo_dir, candidate["merge_sha"], path)
        except Undecodable:
            gold_base.pop(path, None)
            undecodable.add(path)
    readable = "".join(s.text() for s in languages.parse_diff(diff) if s.path not in undecodable)
    split = languages.split_diff(language, readable)
    if any(languages.classify_path(language, p) in ("src", "test") for p in undecodable):
        return {**base, "valid": False, "reason": "binary", "gold_patch": diff}
    context = Path(work) / "context"
    sha_record, staging = context / "base_sha", context / "repo.tmp"
    recorded = sha_record.read_text().strip() if sha_record.is_file() else None
    if recorded != candidate["base_sha"] or not (context / "repo").is_dir():
        context.mkdir(parents=True, exist_ok=True)
        sha_record.unlink(missing_ok=True)
        for stale in (context / "repo", staging):
            shutil.rmtree(stale, ignore_errors=True)
        q = shlex.quote
        code, out, err = run_fn(
            ["sh", "-c", f"git -C {q(repo_dir)} archive {candidate['base_sha']} | (mkdir -p {q(str(staging))} && tar -x -C {q(str(staging))}) "
                         f"&& mv {q(str(staging))} {q(str(context / 'repo'))}"],
            timeout=600,
        )
        if code != 0:
            shutil.rmtree(staging, ignore_errors=True)
            message = f"git archive failed: {(err or out).strip()[-300:]}"
            return {**base, "valid": False, "reason": f"build_error: {message}", "build_error": message}
        atomic_write(sha_record, candidate["base_sha"] + "\n")
    atomic_write(context / "Dockerfile", dockerfile(recipe, cfg))
    image = image_name(task_id, recipe, cfg)
    timeout = section(cfg, "build").get("timeout_s", 3600)
    code, log = docker.build(context, image, timeout=timeout)
    record = {**base, "image": image, "recipe": recipe, "gold_patch": diff, "gold_split": split,
              "gold_base": gold_base, "gold_after": gold_after, "f2p": [], "p2p": [],
              "valid": None, "reason": "", "brief": None, "mutants": []}
    if code != 0:
        atomic_write(Path(log_dir) / f"{task_id}.log", "\n".join(log.splitlines()[-50:]) + "\n")
        return {**record, "valid": False, "reason": "build_error: image build failed", "build_error": "image build failed"}
    return record


def build_agent_image(task: dict, *, docker, cfg: dict, work_dir, log_dir) -> str:
    tools = tools_image_name()
    try:
        docker.image_id(tools)
    except docker.ImageMissing:
        ctx = Path(work_dir) / "tools-context"
        ctx.mkdir(parents=True, exist_ok=True)
        atomic_write(ctx / "Dockerfile", tools_dockerfile())
        code, log = docker.build(ctx, tools, timeout=section(cfg, "build").get("timeout_s", 3600))
        if code != 0:
            raise RecipeError("tools image build failed:\n" + "\n".join(log.splitlines()[-50:]))
    name = agent_image_name(task["image"])
    ctx = Path(work_dir) / task["task_id"] / "agent-context"
    ctx.mkdir(parents=True, exist_ok=True)
    atomic_write(ctx / "Dockerfile", agent_dockerfile(task["image"], tools))
    code, log = docker.build(ctx, name, timeout=section(cfg, "build").get("timeout_s", 3600))
    if code != 0:
        atomic_write(Path(log_dir) / f"{task['task_id']}-agent.log", "\n".join(log.splitlines()[-50:]) + "\n")
        raise RecipeError(f"agent image build failed for {task['task_id']}")
    return name
