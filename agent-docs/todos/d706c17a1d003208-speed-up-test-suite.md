---
commit: 8aaa75e6f9fa6764c61337df7f1460d6481149b7
---

# Speed up the test suite

## Goal
Shorten the full Test command (`python -m unittest discover -s tests`), which each workflow run executes several times.

## Observation
- 2026-11-10: 1166 tests took 489 s; 1067 tests took 456–637 s on the same machine.
- Most tests install the harness into a temporary git repo and run hooks or the installer as subprocesses.
- 2026-11-13 (harness 0.45.0): 1219 tests took 457 s, user 234 s + sys 180 s at 90% CPU on a 10-core machine, so the run is single-core and dominated by process creation and file I/O. Re-check: `time python3 -m unittest discover -s tests`.
- Update tests starting below 0.40.0 are skipped by default (`tests/legacy_migrations.py`, `HARNESS_LEGACY_MIGRATION_TESTS=1` runs them); skipping 109 of them saved only 504 s → 457 s.
- One `harness.py install` into a temp repo: 0.11 s. One commit through the harness git hooks staging a fresh install: 0.65–0.95 s, mostly `warn_new_comments.py --staged` running `git show` per staged file; with `--no-verify`: about 0.01 s.
- A subagent timed every git commit/merge through a PATH shim (8 runs, measured while another full suite ran, so absolute values may be high): about 74 hook-running commits, about 47 s in total. 63 assert hook behaviour, 7 are setup only (about 6 s saved with `--no-verify`, mainly `DocRecordsTestCase.commit_all` in tests/test_doc_records.py and two setup commits in tests/test_installer.py), 4 unclear (`work_session` in tests/test_progress_retire.py, the update auto-commit in tests/test_update_commit.py).
- Other measured savings: tests/test_message_nudge.py commits the whole install through pre-commit though it checks only commit-msg (about 3.5 s); some legacy-skipped tests install and hook-commit before reaching the skip (2–3 s).
- `test_progress.TestPromptRecording`: 14 tests, 9.0 s, of which hook commits 1.4 s; the rest is installs and Claude hook payload subprocesses (about 0.55 s per test). Hook-commit work is about 3% of the suite at best.
- tests/test_isolation_telemetry.py and tests/test_session_metrics.py import hypothesis/pytest; without them they fail to load. `uv run --no-project --with pytest --with hypothesis python -m unittest ...` runs them.

## Next Step
- Try running test modules in parallel (one process per file, 10 cores) after checking that no test writes shared state outside its temp directory; compare wall time with the serial run.
- Then measure per-module time and look at Claude hook payload subprocess count per test, which the 2026-11-13 measurements point to as the larger cost than git hooks.

## Related
- tests/test_installer.py, tests/test_progress.py, tests/test_hook_owned_progress.py, tests/test_doc_records.py, tests/test_message_nudge.py, tests/legacy_migrations.py
