import json
import os
import re
import unittest
from pathlib import Path

CUTOFF = (0, 40, 0)
ENV = "HARNESS_LEGACY_MIGRATION_TESTS"


def skip_legacy_update(args):
    if os.environ.get(ENV) == "1" or tuple(args[:1]) != ("update",):
        return
    for arg in args[1:]:
        try:
            version = json.loads((Path(arg) / ".harness" / "manifest.json").read_text())["version"]
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if isinstance(version, str) and re.fullmatch(r"\d+\.\d+\.\d+", version):
            if tuple(int(p) for p in version.split(".")) < CUTOFF:
                raise unittest.SkipTest(f"update from {version} runs migrations before 0.40.0; set {ENV}=1 to run")
