# Test quality gaps found in past workflow-approach runs

## Goal
"이걸 바탕으로 harness 쪽에 개선 사항 handoff 작성해줘. 어떻게 할지는 적지말고, 발견한 문제를 구체적으로 나열해줘"

Context: a read-only audit (2026-10-13) of tests produced by workflow-approach runs that passed test-verifier and mutation testing.
- **Pass 1** covered 10 runs from 09-22 to 10-11 at harness 0.7.0–0.20.0. Runs before 0.7.0 were excluded because mutation was only a verifier thought experiment then.
- **Pass 2** covered the 2 runs made after the 0.17.0 hardening (`6f44ce6`). It used a strict, harness-independent rubric that ignored verifier verdicts and the mutation ledger.

No tests or mutants were executed during the audit. Every "would survive" claim below comes from reading the code and has not been executed.

## State
- Branch: `master`
- Commit: `4d447a0`
- Changed files: none; this handoff is the only change.
- Relevant source files:
  - `harness/skills/workflow-approach/SKILL.md`
  - `harness/agents/test-implementer.md`
  - `harness/agents/test-verifier.md`
  - `harness/agents/mutant-triager.md`
  - `harness/bin/test_scan.py`
  - `tests/test_test_scan.py`
  - `tests/test_test_scan_rules.py`
  - `tests/test_installer.py`

Audited runs. Commits are in each target repo; "wt" means the session ran in a worktree.

| # | session | project / spec | harness | commit |
|---|---|---|---|---|
| 1 | 3a4e65b0 | harness / 7176826b00d34cc7-analytics-dashboard | 0.7.0 | 1450ab1 |
| 2 | 3b0fc95c | clip-manager (wt) / 547fb213daf79144-editor-effects-ui | 0.9.0 | 56867dd |
| 3 | ddef4e81 | gallery / f4e54a4cec9a832d-gallery-extension-first-cut | 0.11.0 | e665858 |
| 4 | 5755a596 | blog (wt) / 8f8bc346160affc6-notion-import | 0.10.0 | 03e9ef7 |
| 5 | f8b516f7 | network-analysis (wt) / 44ff0ed597e46cf3-report-readability-finish | 0.10.0 | 87d3a72 |
| 6 | 17081ad2 | blog / 4cdc41e0994e0af9-post-close-morph-visibility | 0.13.0 | 63f7087 |
| 7 | 1c2c113a | network-analysis (wt) / 485e71fc64c8a984-route-client-call-edges | 0.13.0 | 6333ad9 |
| 8 | 3254b7d8 | harness / 43566c0a9bdc1f1f-dry-run-ignore-fail-and-needed-parents | 0.14.0 | d4fe995 |
| 9 | 32a7d6ea | network-analysis (wt) / d01cf9063bb1e4aa-identifier-ambiguity-metric | 0.13.0 | bf5f664 |
| 10 | ca7aac38 | harness / f0e1103f974f1301-test-audit-language-rules | 0.20.0 | 2a79dcc |
| 11 | 40f4ec2e | harness / 5aee51c6eb1cf672-test-audit-skill | 0.17.0 | f350bb6 |

Pass 1 audited runs 1–10. Pass 2 audited runs 10 and 11 under the strict rubric; run 10 was re-audited from scratch without the pass 1 results.

## Failed Attempts
| attempt | failure evidence | cause |
|---|---|---|
| Treat "verifier PASS + all recorded mutants killed" as test quality | In all 10 runs, the auditor found 2–3 or more plausible unrecorded mutants that no test detects, many of them on must requirements | verified: recorded mutants were concentrated on already-tested code (see P1) |
| Rely on 0.17.0 (8–10 hand mutants, fuzzing, mutation tool) to raise quality | Run 10 at 0.20.0 scored 강 in pass 1 but 중 overall in pass 2 (input discrimination 약). Run 11 at 0.17.0 scored 중 and "conditional reject" | verified for these 2 runs; based on only 2 samples, both on a pure-Python CLI repo |
| Compare quality across harness versions | Later versions scored better, but those runs (#8, #10, #11) are all in the harness repo, which is easy to test | hypothesis: the version effect is confounded with the target repo |

## Next Step
Decide which of the problems below the harness should address, and open a workflow-approach spec for that scope.

### P1. Mutants target code that is already tested
- In 10 of 10 runs, the mutants were chosen after the fact to confirm verifier findings. The largest or riskiest new code was never mutated:
  - #7: `http_calls.py`, 249 lines, the largest new file.
  - #9: `_regions`, the lexer core.
  - #1: importer re-import branch, `importer.py:44-46`.
  - #6: the B fix, the BlogShell refactor, and the overlay clipPath.
  - #3: the sort comparator. Verifier 1 recommended a mutant there; it was never run.
- #10 ran at 0.20.0 but used no mutation tool. #11 is the only run with mutation-tool use at 0.17+. No mutant-triager output exists in the sample.
- #10 and #11: no mutant targeted the ~150 per-language regex rules, which are the user-facing core.

### P2. Test inputs already have the expected shape, so tests pass vacuously
Single-variant or "already correct" inputs appear in 9 of 10 pass-1 runs and in both pass-2 runs:

| run | input problem | consequence |
|---|---|---|
| #3 | sort test input is already in order (`CbzScannerTest.kt:34`) | removing `sortedBy` still passes |
| #3 | directory-entry test uses `"a.png/"`, which already fails the extension check | removing `!entry.isDirectory` still passes |
| #2 | all speed segments divide evenly | truncation mode is untested |
| #2 | speed range always starts at keep start | `EditorLogic.kt:77` never executes |
| #2 | adds are always ascending | `sortedBy` in `speedsOverlap` is untested |
| #4 | exactly one local image per test | reversing the replacement order still passes |
| #4 | no absolute-path image test | removing the `isAbsolute` check still passes |
| #5 | target always at anchor (0,0) | `neighborCenter` mutant survives |
| #5 | `query_nodes` always empty | query-node weight is never observed |
| #7 | no spread syntax and no non-object `fetch` init | `http_calls.py:148/158/163` branches are untested |
| #8 | every `.gitignore` seed ends with a newline | `harness.py:575` newline prefix is untested |
| #8 | no existing exception lines | dedupe at `:547` is untested |
| #9 | only `"""`, only unterminated `/*`, no `\` in strings | `identifier_occurrence.py:32/42/48` survive |
| #1 | rewrite test writes bytes identical to the original | re-import branch never runs |
| #10/#11 | only bare `class`, bare `time(nullptr)`, single-quoted JS titles, `@unittest.skip`/`MagicMock` only, no async or docstring test | modifier, qualifier, and syntax-variant regex alternatives are untested |

### P3. Assertions check a single flag or a subset
- #10:
  - `test_vo4_direct_flag_rows` (~200 subtests) checks only the target flag with `assertIn`. It never checks whether a snippet also triggers another flag or language.
  - 13 rule rows have no non-trigger: kotlin/csharp sleep, swift xfail/sleep, php skip/focused/incomplete/sleep, ruby xfail/focused/sleep, cpp xfail/sleep.
- #11:
  - go, rust, and java tests assert no flags at all. JS checks only skip and focused, so FR3 (must) is effectively unverified outside Python.
  - The output schema is not asserted: `summary.tests`, `summary.flags`, `language`, `runner_candidates[].evidence`.
- #1: compliance negative tests use `assertTrue(reasons)`, the malformed test checks only `runs == 1`, and the startup-failure test checks only a nonzero exit code and non-empty stderr.
- #4: success-path body and source-marking checks are partial `toContain`.
- #6: O4 checks only "first clip is not full-screen". O5 checks only `toHaveCount(1)`.
- #7: `assertGreaterEqual(fan_out, 1)`. QR1 is verified by absence checks only, never by comparing output bytes to the base commit.
- #8: the migration announcement body is unasserted (only the header is checked).

### P4. Some oracles reimplement production code or cannot fail
- Reimplementing production:
  - #2: V1 expected values use `preset.width/height` (`EditorLogicTest.kt:193-199`).
  - #2: V7 expected values call `clampSelection(...)` (`EditorEffectsViewModelTest.kt:154,173`).
  - #9: V4 selects nodes with the production last-segment rule (`test:164`).
- Cannot fail:
  - #10: `self.assertTrue(nd)` at `tests/test_test_scan_rules.py:1194` asserts a constant.
  - #10: `test_vo9_version_file_and_install_manifest_are_0210` asserts the VERSION constant.
  - #1: the Q5 codex end-to-end check reads a transcript that is never scanned, so it is always true.
  - #10: the FR11 SKILL.md language check is a whole-document substring search (`tests/test_installer.py:465-477`): `"go"` matches nearly anything, `"java"` matches `"javascript"`, and `"skip"`, `"empty"`, `"sleep"` always match.

### P5. The verifier accepts narrowed scope and dropped advisories
- #7: verifier 2 wrote "Advisory: none remain", but A1 (QR1 base equality) and A3 (non-literal axios URL) were never addressed.
- #9: F3 (must) clauses were cut from V2 coverage. The verifier filed the gap as advisory A1, "outside declared coverage items", and the main agent told the user it was out of scope.
- #5: the verifier accepted C-6 as covered, but no test has present nodes together with asserted new-neighbor coordinates.
- #4: the continuation run's verifier wrote "F7: remains rejected (no new evidence)" without re-examining it.
- #1: the verifier called the rewrite path "Sound" in rounds 1–3, but that path never executes.
- #6: verifier 2 accepted excluding M3, which leaves intent I2 (the B fix) without an oracle.
- #3: the verifier accepted V1 as verifying sorted order and accepted V5's directory-entry partition. Both pass vacuously (P2).
- #2: the verifier missed the V1 oracle reimplementation and the evenly-divisible V2 inputs.

### P6. Mutant dispositions and kill attribution are wrong
- #9: M1 (full label instead of `node_identifier(label)`, `bottlenecks/core.py:103`) survived and was recorded as "equivalent". It is a real defect: any dotted label yields 0. Verifier 2 agreed with the "equivalent" call.
- #4: M4 (`markUploaded(page.strippedBody)`) was killed by an unrelated oracle, a frontmatter key assert at test:272. That kill was then used to reject finding F7 (body byte preservation), which remains unverified.
- #5: the archived Audit state lists "mutations M1–M3 detected" on every VO row, including VO-1, VO-3, VO-6 and VO-8, which no mutant exercised.
- #4: the `[...prepared]` substitution recorded alongside M2 is a no-op mutant.
- #3: only 3 mutants were run, all in areas that were already strong.

### P7. Glue code and entry points have no automated tests
- #5: `graph.js` `updateAlwaysLabels`. FR2 (must) is verified only by an "overlap 0, console errors 0" review criterion.
- #4: the CLI `scripts/import-notion.mjs` (exit code, problems output, local date) has no tests, and the spec has no obligation for it.
- #6: the `BlogShell.tsx` memo/ref refactor has no unit test. `related` deps and `back(current.base)` are unverified.
- #2: core preview logic has no unit tests and relies on R1 manual checks: `flipAt`, `sourceTimeForOutput`, `EditPlanner.kt:184,215`. The spec's Test path excluded core.
- #7: TS call-site collection (`_module_instances`, `_join`, the `export_clause` branch at `http_calls.py:107-117`) was outside the mutation sample.

### P8. Process violations
- #8: the main agent tightened `assert_dry_ignored_row` after the verifier passed (`tests/test_installer.py:2225-2229`). The verifier was not rerun, and the ledger still records A1 as "left open by choice".
- #1: the main agent wrote the G7/G8 tests itself after reading `importer.py:56-64`, which breaks role separation. G5 (`ANALYTICS_HOST`) was deferred without a user decision, even though Q6 requires "0 ignored overrides", and the run was marked complete.
- #11: `tests/test_installer.py:2443` `assertNotEqual(..., "0.17.0")` was not updated when the latest version became 0.18.0. A refused update that wrongly completes would still pass.

### P9. Test maintainability in the harness repo (#10, #11)
- Version literals are hardcoded in about 27–30 places, and `"y\n" * N` prompt counts are hardcoded across installer, telemetry, and workflow_markers tests. Every release edits them in bulk.
- Test names are stale: `test_c18_harness_version_is_0_9_0` asserts 0.18.0.
- `tests/test_test_scan_rules.py` has a custom rendering DSL of about 250 lines (T/CFG/render_*/S·P·C) with hidden special cases: except/with/rescue and brace auto-closing.
- `tests = [t for t in tests]` at `:598` is a no-op.
- `test_vo6_other_languages_mock_only_and_snapshot_only_rows` largely duplicates the VO4 mock/snapshot rows.
- Nearly every test spawns a subprocess and git; the suite makes hundreds of process launches.
- Migration tests are coupled to prose substrings, for example "no existing project files change" at `tests/test_installer.py:547`.

### P10. Production defects hidden by these test gaps (unverified)
- Inferred by reading the code; not executed.
- `harness/bin/test_scan.py:377 @2a79dcc`: the cpp `time` rule has the lookbehind `(?<![\w.:>])`, so it misses `std::time(nullptr)`. The `rand` alternative on the same line allows `std::`.
- `harness/bin/test_scan.py:164`, `:196`, `:264` (java/kotlin/swift group skip): no fixture has a modifier before `class` or `struct`, so the modifier-prefixed path is untested.
- `harness/bin/test_scan.py:753-760`: the composer.json parse guard is never exercised with malformed JSON, or with `scripts` as a list.
- #4 `notion-import.mjs:131` `frontmatterScalar` writes `JSON.stringify(String(value))`. Arrays become `"a,b"` and objects become `"[object Object]"`, which violates R8 key merging.
- #7 `http_calls.py:158`: a non-object `fetch` init returns method `None`. Whether that is correct is untested.

### Additional unrecorded mutants judged to survive (from the audit reports)
- #10:
  - `test_scan.py:55`: remove the python trivial_assert negative lookahead.
  - `:332-333`: unanchor ruby `pending`/`fit`.
  - `:312`: weaken the php lookbehind to `(?<![\w])`.
  - `:86`: remove the JS `|\w+` catch-param alternative.
  - `:582`: drop the ruby `end` indentation comparison.
- #11 (`test_scan.py @f350bb6`):
  - `:363`: `summary.tests` → `len(files)`.
  - `:364`: summary flags → `{}`.
  - `:352`: language → `"python"`.
  - `:192`: `== ""` → `!= ""`.
  - `:63`: go assert → None.
  - `:111`: drop the `rel.parts[:-1]` guard.
  - `:164`: drop the docstring branch.
  - `:159`: drop `AsyncFunctionDef`.
  - `:43`: quote class `['"`]` → `[']`.
  - `:309`: drop the gradle `break`.
  - `:125`: apply exclusions only at top level.
- #8 `installer/harness.py`:
  - `:547`: drop dedupe.
  - `:575`: always use an empty prefix.
  - `:361-364`: migration returns `[]`.

## Open Questions
- Should the P10 suspected production defects be confirmed by running them before any harness change?
- Should the confounding in the version comparison be resolved by auditing 0.18+ runs in non-harness repos once they exist? No such runs existed at audit time.
- Which of P1–P9 belong in harness instructions and agents, and which are per-project test debt (#2–#7, #9) to leave to each repo?

## Spec
none (audit task, not a workflow-approach run)

## Execution Ledger
- Audit agents: 12, all read-only (10 in pass 1, 2 in pass 2). No tests, builds, or mutants were executed.
- Pass 1 grades:
  - Coverage: 강 3, 중 7.
  - Oracle: 강 4, 중 6.
  - Mutation effectiveness: 중 5, 중-약 2, 약 3.
  - Verifier judgment: 강 2, 중 6, 약 2.
- Pass 2 (strict):
  - #11: tests 강 35 / 약 6 / 공허 0. Overall 중; would get conditional reject in strict review.
  - #10: tests 강 70 / 약 4 / 공허 1. Overall 중; would get conditional reject in strict review.
- Correction counters: n/a. Verifier counters: n/a.
