# Speed up the test suite

## Goal
Shorten the full Test command (`python -m unittest discover -s tests`), which each workflow run executes several times.

## Observation
- 2026-11-10: 1166 tests took 489 s; 1067 tests took 456–637 s on the same machine.
- Most tests install the harness into a temporary git repo and run hooks or the installer as subprocesses.

## Next Step
- Measure per-module and per-test time (for example `python -m unittest -v` with timestamps) and list the slowest modules before choosing a change.

## Related
- tests/test_installer.py, tests/test_progress.py, tests/test_hook_owned_progress.py
