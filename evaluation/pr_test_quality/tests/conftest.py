import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from evaluation.pr_test_quality.tests import fakes

_TMP = tempfile.TemporaryDirectory(prefix="eval-harness-repo-")
_ROOT = Path(_TMP.name) / "repo"


def _git(*args):
    env = dict(os.environ, GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null", GIT_CONFIG_NOSYSTEM="1")
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-C", str(_ROOT), *args],
                          env=env, capture_output=True, text=True, check=True).stdout.strip()


def _build_repo():
    files = {
        "AGENTS.md": "agents\n", "CLAUDE.md": "claude\n", "installer/harness.py": "print('install')\n",
        "harness/payload.txt": "payload\n", "evaluation/other.py": "x = 1\n", "README.md": "readme\n",
    }
    for name, text in files.items():
        path = _ROOT / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    _git("init", "-q")
    _git("add", "-A")
    _git("commit", "-q", "-m", "fixture")
    fakes.HARNESS_REPO.update({"root": _ROOT, "head": _git("rev-parse", "HEAD")})


_build_repo()


@pytest.fixture(autouse=True)
def isolated_repo_root(monkeypatch):
    from evaluation.pr_test_quality import gce, run
    monkeypatch.setattr(run, "REPO_ROOT", _ROOT)
    monkeypatch.setattr(gce, "REPO_ROOT", _ROOT)
    yield
