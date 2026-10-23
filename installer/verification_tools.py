"""Offers to install fuzzing and mutation tools that workflow-approach specs can declare."""

import json
import os
import re
import shutil
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

# Every per-language definition lives here; adding a language means adding one entry.
# "managers": (lockfiles, command prefix) in priority order; "fallback" applies when no lockfile matches
# (None means the language is blocked without one). "fixed": per-package complete commands.
LANGUAGES = (
    {
        "language": "python",
        "manifest": "pyproject.toml",
        "packages": ("hypothesis", "mutmut"),
        "managers": (
            (("uv.lock",), ("uv", "add", "--dev")),
            (("poetry.lock",), ("poetry", "add", "--group", "dev")),
            (("pdm.lock",), ("pdm", "add", "-dG", "dev")),
        ),
        "fallback": None,
    },
    {
        "language": "javascript",
        "manifest": "package.json",
        "packages": ("fast-check", "@stryker-mutator/core"),
        "managers": (
            (("pnpm-lock.yaml",), ("pnpm", "add", "-D")),
            (("yarn.lock",), ("yarn", "add", "-D")),
            (("bun.lock", "bun.lockb"), ("bun", "add", "-d")),
        ),
        "fallback": ("npm", "install", "--save-dev"),
    },
    {
        "language": "go",
        "manifest": "go.mod",
        "packages": ("go-mutesting",),
        "marker": "github.com/avito-tech/go-mutesting",
        "fixed": {
            "go-mutesting": ("go", "get", "-tool", "github.com/avito-tech/go-mutesting/cmd/go-mutesting@latest"),
        },
    },
    {
        "language": "rust",
        "manifest": "Cargo.toml",
        "packages": ("proptest", "cargo-mutants"),
        "crate_tables": ("dependencies", "dev-dependencies"),
        "path_executables": {"cargo-mutants": "cargo-mutants"},
        "fixed": {
            "proptest": ("cargo", "add", "--dev", "proptest"),
            "cargo-mutants": ("cargo", "install", "cargo-mutants"),
        },
    },
)

JS_DEPENDENCY_TABLES = ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies")
PREFERENCE_KEY = "verification_tools_prompt"
INSTALL_TIMEOUT_SECONDS = 600
REQUIREMENT_NAME_RE = re.compile(r"[A-Za-z0-9._-]+")


@dataclass(frozen=True)
class Plan:
    language: str
    packages: tuple[str, ...]
    commands: tuple[tuple[str, ...], ...]
    blocker: str | None


def preferences_file() -> Path:
    return Path(os.environ.get("HARNESS_PREFERENCES_FILE") or Path.home() / ".harness" / "preferences.json")


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _python_names(node, found: set[str]) -> None:
    if isinstance(node, str):
        match = REQUIREMENT_NAME_RE.match(node)
        if match:
            found.add(_normalize(match.group()))
    elif isinstance(node, dict):
        for key, value in node.items():
            _python_names(key, found)
            _python_names(value, found)
    elif isinstance(node, list):
        for value in node:
            _python_names(value, found)


def _present_packages(spec: dict, target: Path) -> set[str] | str:
    """Return the installed package names, or a blocker message when the manifest is unusable."""
    manifest = target / spec["manifest"]
    try:
        text = manifest.read_text(encoding="utf-8")
        language = spec["language"]
        if language == "python":
            data = tomllib.loads(text)
            found: set[str] = set()
            _python_names(data, found)
            return found
        if language == "javascript":
            data = json.loads(text)
            if not isinstance(data, dict):
                return f"{spec['manifest']} top level is not an object"
            names: set[str] = set()
            for table in JS_DEPENDENCY_TABLES:
                if isinstance(data.get(table), dict):
                    names.update(data[table])
            return names
        if language == "go":
            return {package for package in spec["packages"] if spec["marker"] in text}
        data = tomllib.loads(text)
        names = set()
        for table in spec["crate_tables"]:
            if isinstance(data.get(table), dict):
                names.update(data[table])
        return names
    except (OSError, ValueError) as error:
        return f"cannot read {spec['manifest']}: {error}"


def _plan_for(spec: dict, target: Path, which) -> Plan | None:
    language = spec["language"]
    present = _present_packages(spec, target)
    if isinstance(present, str):
        return Plan(language, spec["packages"], (), present)
    for package, executable in spec.get("path_executables", {}).items():
        if which(executable):
            present.add(package)
    missing = tuple(package for package in spec["packages"] if package not in present)
    if not missing:
        return None

    if "fixed" in spec:
        commands = tuple(spec["fixed"][package] for package in missing)
    else:
        prefix = next(
            (
                manager_prefix
                for lockfiles, manager_prefix in spec["managers"]
                if any((target / lockfile).exists() for lockfile in lockfiles)
            ),
            spec["fallback"],
        )
        if prefix is None:
            lockfiles = ", ".join(lockfile for lockfiles, _ in spec["managers"] for lockfile in lockfiles)
            return Plan(language, missing, (), f"no lockfile found ({lockfiles}) to choose a package manager")
        commands = ((*prefix, *missing),)

    for executable in dict.fromkeys(command[0] for command in commands):
        if not which(executable):
            return Plan(language, missing, commands, f"{executable} not found on PATH")
    return Plan(language, missing, commands, None)


def detect_plans(target: Path, which: Callable[[str], str | None] = shutil.which) -> list[Plan]:
    plans = []
    for spec in LANGUAGES:
        if (target / spec["manifest"]).is_file():
            plan = _plan_for(spec, target, which)
            if plan is not None:
                plans.append(plan)
    return plans


def _load_preferences() -> dict | None:
    path = preferences_file()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    repositories = data.get("repositories", {})
    if not isinstance(repositories, dict) or not all(isinstance(entry, dict) for entry in repositories.values()):
        return None
    return data


def _save_preferences(data: dict) -> bool:
    path = preferences_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    except OSError:
        return False
    return True


def is_never(target: Path) -> bool:
    data = _load_preferences()
    if data is None:
        return False
    entry = data.get("repositories", {}).get(str(target.resolve()), {})
    return entry.get(PREFERENCE_KEY) == "never"


def set_never(target: Path) -> bool:
    data = _load_preferences()
    if data is None:
        return False
    data.setdefault("repositories", {}).setdefault(str(target.resolve()), {})[PREFERENCE_KEY] = "never"
    return _save_preferences(data)


def clear_never(target: Path) -> bool:
    data = _load_preferences()
    if data is None:
        return False
    key = str(target.resolve())
    entry = data.get("repositories", {}).get(key)
    if entry is None or PREFERENCE_KEY not in entry:
        return True
    del entry[PREFERENCE_KEY]
    if not entry:
        del data["repositories"][key]
    return _save_preferences(data)


def _command_text(commands: tuple[tuple[str, ...], ...]) -> str:
    return " && ".join(" ".join(command) for command in commands)


def _install(plan: Plan, target: Path, report: dict, run: Callable) -> None:
    for index, command in enumerate(plan.commands):
        try:
            result = run(
                list(command),
                cwd=target,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=INSTALL_TIMEOUT_SECONDS,
            )
            reason = None
            if result.returncode != 0:
                output = ((result.stderr or "").strip() or (result.stdout or "").strip()).splitlines()
                reason = output[0] if output else f"exit code {result.returncode}"
        except (OSError, subprocess.TimeoutExpired) as error:
            reason = f"{type(error).__name__}: {error}".splitlines()[0]
        if reason is not None:
            report["manual review"].append(
                f"{plan.language} verification tool install failed ({reason}); "
                f"run manually: {_command_text(plan.commands[index:])}"
            )
            return
    report["write"].append(f"{plan.language} verification tools: {', '.join(plan.packages)}")


def offer(
    target: Path,
    dry_run: bool,
    ask_tools: bool,
    report: dict,
    input_fn: Callable[[str], str] = input,
    run: Callable = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
) -> None:
    plans = detect_plans(target, which)
    for plan in plans:
        if plan.blocker is not None:
            hint = f"; run manually: {_command_text(plan.commands)}" if plan.commands else ""
            report["manual review"].append(
                f"{plan.language} verification tools not installed ({plan.blocker}){hint}"
            )
    askable = [plan for plan in plans if plan.blocker is None]
    if not askable:
        return

    if dry_run:
        for plan in askable:
            report["info"].append(f"{plan.language}: would offer to run {_command_text(plan.commands)}")
        return

    if ask_tools:
        if is_never(target) and not clear_never(target):
            report["manual review"].append("could not clear the saved 'never' answer for verification tools")
    elif is_never(target):
        report["skip"].append("verification tool install not offered (answered never; use --ask-tools to be asked again)")
        return

    for plan in askable:
        prompt = f"Install {plan.language} verification tools: {_command_text(plan.commands)} ? [y/N/never] "
        try:
            answer = input_fn(prompt).strip().lower()
        except EOFError:
            answer = ""
        if answer in ("y", "yes"):
            _install(plan, target, report, run)
        elif answer == "never":
            if not set_never(target):
                report["manual review"].append(
                    f"could not save the 'never' answer for verification tools to {preferences_file()}"
                )
            return
        else:
            report["skip"].append(f"{plan.language} verification tools not installed (not confirmed)")
