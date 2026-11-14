---
commit: 40078a67b4015352344c64edf927ac9a5583f928
---

# Tests leave session-lock files in the real telemetry directory

## Goal
Keep the test suite from writing into `~/.harness/telemetry/`.

## Observation
- `session_metrics._state_lock()` in `harness/lib/session_metrics.py` opens `<repo slug>-<repo identity>.session-lock` in `telemetry._telemetry_directory()`. That directory is `~/.harness/telemetry` unless `HARNESS_TELEMETRY_DIR` is set (`harness/lib/telemetry.py`). The file is never removed.
- Tests that run installed hooks inside temporary repositories without setting `HARNESS_TELEMETRY_DIR` therefore create one empty lock file per temporary repository. The file name embeds the temporary path, for example `-private-var-folders-...-T-tmp...-<16 hex>.session-lock` on macOS.
- Only four test modules set `HARNESS_TELEMETRY_DIR`: tests/test_isolation_telemetry.py, tests/test_session_metrics.py, tests/test_workflow_markers.py, and tests/test_telemetry.py.
- On 2026-11-14 the directory held 879 such files (oldest 2026-10-15), and one full suite run at harness 0.48.0 added files with the run's timestamp. No `.jsonl` file with a temporary-directory name was present, so event lines were not observed leaking.
- Re-check:
  1. Run `ls ~/.harness/telemetry | grep -c 'T-tmp'`.
  2. Run `python3 -m unittest discover -s tests`.
  3. Count again, and list `ls ~/.harness/telemetry | grep 'T-tmp' | grep -v session-lock`.

## Next Step
- Find the shared helpers that spawn hooks or the installer in a temporary repo, and give their child processes a temporary `HARNESS_TELEMETRY_DIR`, or set it once for the whole run.
- Then re-run the count above.
- Deleting the existing files is a separate choice for the user.

## Related
- harness/lib/session_metrics.py, harness/lib/telemetry.py, tests/test_telemetry.py, tests/test_workflow_markers.py
