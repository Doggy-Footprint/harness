"""VO2 (equivalence partitioning) and VO3 (boundary value analysis) for selfcheck.process.evaluate_entry.

Expected verdicts are the spec's PC1-PC11 rules applied by hand to each synthetic entry; `None` in an
expectation map means "the spec does not pin this verdict for this entry" (see the report's challenges).
"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from selfcheck import process
from selfcheck.tests import m3_fakes as m
from selfcheck.tests.m3_fakes import E, L, tb

LEDGER = "raw/ledger.jsonl"
TELEMETRY = "raw/telemetry/a.jsonl"
GOOD = m.score("x")


def ledger_with(insert_at=None, rows=(), base=None):
    items = list(base if base is not None else m.compliant_ledger_items())
    if insert_at is None:
        return items + list(rows)
    return items[:insert_at] + list(rows) + items[insert_at:]


def events_with(mutate):
    return m.reseq(mutate(m.compliant_events()))


def seq_events(actions, end="complete"):
    events = [
        E("workflow_start"), E("workflow_phase", phase="implement_test"), E("workflow_phase", phase="verify"),
        E("verifier_result", result="pass"), E("verification_result", mutants=10, killed=9),
    ]
    events += [E("seed", action=a) for a in actions]
    events.append(E("workflow_end", status=end))
    return m.reseq(events)


def verifier_events(results, end="complete"):
    events = [E("workflow_start"), E("workflow_phase", phase="implement_test")]
    for n, result in enumerate(results):
        if n:
            events.append(E("workflow_phase", phase="amend"))
        events += [E("workflow_phase", phase="verify"), E("verifier_result", result=result)]
    events += [E("verification_result", mutants=10, killed=9), E("seed", action="backup"),
               E("seed", action="restore"), E("workflow_end", status=end)]
    return m.reseq(events)


class ProcessCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="proc-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.counter = 0

    def evaluate(self, score=GOOD, **over):
        self.counter += 1
        over.setdefault("iid", "inst-%d" % self.counter)
        iid = over.pop("iid")
        arm = over.pop("arm", "harness")
        entry = m.write_entry(self.tmp, iid, arm, **over)
        return process.evaluate_entry(entry, score=score)

    @staticmethod
    def verdicts(res):
        return {cid: res["checks"][cid]["verdict"] for cid in res["checks"]}

    def expect(self, res, overrides=None, dont_care=()):
        self.assertEqual(set(res["checks"]), set(m.CHECK_IDS))
        want = dict.fromkeys(m.CHECK_IDS, "pass")
        want.update(overrides or {})
        got = self.verdicts(res)
        for cid in m.CHECK_IDS:
            if cid in dont_care:
                continue
            self.assertEqual(got[cid], want[cid], "%s: %s" % (cid, res["checks"][cid]))

    @staticmethod
    def evidence(res, cid):
        return {(e["file"], e["line"]) for e in res["checks"][cid]["evidence"]}


# ----------------------------------------------------------------------------------------------
# VO2: one compliant class (C6), shape
# ----------------------------------------------------------------------------------------------

class CompliantEntryTests(ProcessCase):
    def test_vo2_c6_compliant_entry_passes_every_check(self):
        res = self.evaluate()
        self.expect(res)
        self.assertEqual(res["workflow_run_id"], m.WF)
        self.assertEqual(res["end_status"], "complete")
        self.assertEqual(res["skipped_lines"], 0)
        self.assertEqual(res["arm"], "harness")

    def test_vo2_c6_result_shape_and_json_serialisable(self):
        res = self.evaluate()
        self.assertEqual(set(res), {"instance_id", "arm", "workflow_run_id", "end_status", "checks", "metrics",
                                    "skipped_lines"})
        for cid, check in res["checks"].items():
            self.assertEqual(set(check), {"verdict", "detail", "evidence"}, cid)
            self.assertIn(check["verdict"], ("pass", "fail", "n/a"))
            self.assertIsInstance(check["detail"], str)
            for item in check["evidence"]:
                self.assertEqual(set(item), {"file", "line"})
                self.assertIsInstance(item["line"], int)
        json.dumps(res)

    def test_vo2_c6_identity_comes_from_manifest_else_directory_names(self):
        res = self.evaluate(iid="dir-name-x", manifest={"instance_id": "from-manifest", "arm": "harness"})
        self.assertEqual(res["instance_id"], "from-manifest")
        res = self.evaluate(iid="dir-name-y", manifest=None)
        self.assertEqual((res["instance_id"], res["arm"]), ("dir-name-y", "harness"))

    def test_vo2_c6_metrics_of_the_compliant_entry(self):
        res = self.evaluate()
        self.assertEqual(res["metrics"], {
            "verifier_results": 1, "verifier_dispatches": 1, "seed_pairs": 1,
            "subagent_dispatches": {"test-implementer": 1, "implementer": 1, "test-verifier": 1},
            "main_implementation_edits": 0, "implementer_test_runs": 0, "unknown_bash_accesses": 0,
            "self_reported_kill": {"mutants": 10, "killed": 9, "rate": 0.9},
            "measured_kill": 0.5,
        })

    def test_vo2_c6_measured_kill_is_none_without_a_score(self):
        res = self.evaluate(score=None)
        self.assertIsNone(res["metrics"]["measured_kill"])

    def test_vo2_c6_self_reported_kill_uses_the_last_run_verification_result_only(self):
        def mutate(events):
            return events[:5] + [E("verification_result", mutants=20, killed=5)] + events[5:] + [
                E("verification_result", run="OTHER-RUN", mutants=99, killed=99)]
        res = self.evaluate(events=events_with(mutate))
        self.assertEqual(res["metrics"]["self_reported_kill"], {"mutants": 20, "killed": 5, "rate": 0.25})

    def test_vo2_c6_self_reported_kill_is_none_without_an_event_and_rate_none_for_zero_mutants(self):
        res = self.evaluate(events=events_with(lambda e: [x for x in e if x["event"] != "verification_result"]))
        self.assertIsNone(res["metrics"]["self_reported_kill"])
        res = self.evaluate(events=events_with(
            lambda e: [x if x["event"] != "verification_result" else E("verification_result", mutants=0, killed=0)
                       for x in e]))
        self.assertEqual(res["metrics"]["self_reported_kill"], {"mutants": 0, "killed": 0, "rate": None})

    def test_vo2_c6_main_implementation_edits_count_main_rows_after_the_spec_write_only(self):
        edit = L(None, "Edit", file_path=tb(m.IMPL_FILE), old_string="a", new_string="b")
        items = [edit] + m.compliant_ledger_items()
        items = items[:2] + [edit] + items[2:]
        res = self.evaluate(ledger=items)
        self.assertEqual(res["metrics"]["main_implementation_edits"], 1)

    def test_vo2_c6_dispatch_counts_include_task_tool_and_ignore_subagent_rows(self):
        extra = [
            L(None, "Task", subagent_type="test-verifier", prompt="v"),
            L("implementer", "Agent", subagent_type="test-verifier", prompt="v"),
            L(None, "Agent", subagent_type="implementer", prompt="i"),
        ]
        res = self.evaluate(ledger=ledger_with(5, extra))
        self.assertEqual(res["metrics"]["verifier_dispatches"], 2)
        self.assertEqual(res["metrics"]["subagent_dispatches"],
                         {"test-implementer": 1, "implementer": 2, "test-verifier": 2})


# ----------------------------------------------------------------------------------------------
# VO2: one failing class per C7 row (16)
# ----------------------------------------------------------------------------------------------

class SingleViolationTests(ProcessCase):
    def test_vo2_c7_01_no_workflow_start(self):
        res = self.evaluate(events=m.reseq([E("verification_result", mutants=10, killed=9)]))
        self.expect(res, {"PC1": "fail", "PC2": "fail", "PC3": "n/a", "PC4": "n/a", "PC5": "n/a", "PC7": "n/a",
                          "PC8": "n/a", "PC9": "n/a", "PC10": "n/a", "PC11": "n/a", "PC12": "n/a"})
        self.assertEqual(res["checks"]["PC1"]["evidence"], [])
        self.assertIsNone(res["workflow_run_id"])

    def test_vo2_c7_02_telemetry_compliance_reason(self):
        def mutate(events):
            return events[:2] + [E("workflow_phase", phase="implement_test")] + events[2:]
        res = self.evaluate(events=events_with(mutate))
        self.expect(res, {"PC2": "fail"})
        self.assertIn("duplicate_implement_test", res["checks"]["PC2"]["detail"])
        self.assertNotIn("no_workflow_end", res["checks"]["PC2"]["detail"])

    def test_vo2_c7_03_three_verifier_results(self):
        res = self.evaluate(events=verifier_events(["fail", "fail", "pass"]))
        self.expect(res, {"PC3": "fail"})

    def test_vo2_c7_04_three_verifier_dispatches(self):
        dispatch = L(None, "Agent", subagent_type="test-verifier", prompt="v")
        res = self.evaluate(ledger=ledger_with(5, [dispatch, dispatch]))
        self.expect(res, {"PC3": "fail"})

    def test_vo2_c7_05_complete_without_verification_result(self):
        res = self.evaluate(events=events_with(lambda e: [x for x in e if x["event"] != "verification_result"]))
        self.expect(res, {"PC4": "fail"})

    def test_vo2_c7_06_unpaired_backup(self):
        res = self.evaluate(events=seq_events(["backup", "restore", "backup"]))
        self.expect(res, {"PC5": "fail"})
        self.assertEqual(self.evidence(res, "PC5"), {(TELEMETRY, 8)})

    def test_vo2_c7_07_seed_pending_at_end(self):
        pending = "seed: unrestored files in /testbed/.harness/seed\n  AGENTS.md\n"
        res = self.evaluate(prediction_=m.prediction(seed_before=pending))
        self.expect(res, {"PC6": "fail"})
        self.assertEqual(res["checks"]["PC6"]["evidence"], [{"file": "prediction.json", "line": 1}])

    def test_vo2_c7_08_archive_status_does_not_match_end(self):
        res = self.evaluate(diff=m.archived_diff(status="limit"))
        self.expect(res, {"PC7": "fail"})

    def test_vo2_c7_09_handoff_spec_not_active(self):
        events = m.reseq([E("workflow_start"), E("seed", action="backup"), E("seed", action="restore"),
                          E("workflow_end", status="handoff")])
        res = self.evaluate(events=events, diff=m.archived_diff(status="complete", where=m.SPECS))
        self.expect(res, {"PC4": "n/a", "PC7": "fail", "PC10": "n/a", "PC11": "n/a"})

    def test_vo2_c7_10_main_test_edit_after_spec_write(self):
        edit = L(None, "Edit", file_path=tb(m.TEST_FILE), old_string="a", new_string="b")
        res = self.evaluate(ledger=ledger_with(5, [edit]))
        self.expect(res, {"PC8": "fail"})
        self.assertEqual(self.evidence(res, "PC8"), {(LEDGER, 6)})

    def test_vo2_c7_11_implementer_reads_a_tests_file(self):
        res = self.evaluate(ledger=ledger_with(5, [L("implementer", "Read", file_path=tb(m.TEST_FILE))]))
        self.expect(res, {"PC9": "fail"})
        self.assertEqual(self.evidence(res, "PC9"), {(LEDGER, 6)})

    def test_vo2_c7_12_test_implementer_reads_an_implementation_file(self):
        res = self.evaluate(ledger=ledger_with(3, [L("test-implementer", "Read", file_path=tb(m.IMPL_FILE))]))
        self.expect(res, {"PC9": "fail"})
        self.assertEqual(self.evidence(res, "PC9"), {(LEDGER, 4)})

    def test_vo2_c7_13_test_verifier_bash_cat_of_an_implementation_file(self):
        res = self.evaluate(ledger=ledger_with(None, [L("test-verifier", "Bash", command="cat " + m.IMPL_FILE)]))
        self.expect(res, {"PC9": "fail"})
        self.assertEqual(self.evidence(res, "PC9"), {(LEDGER, 9)})

    def test_vo2_c7_14_edit_after_final_pass(self):
        res = self.evaluate(ledger=ledger_with(None, [L("implementer", "Edit", file_path=tb(m.IMPL_FILE))]))
        self.expect(res, {"PC10": "fail"})
        self.assertEqual(self.evidence(res, "PC10"), {(LEDGER, 9)})

    def test_vo2_c7_15_complete_but_unresolved(self):
        res = self.evaluate(score=m.score("x", resolved=False))
        self.expect(res, {"PC11": "fail"})
        self.assertEqual(res["checks"]["PC11"]["evidence"], [{"file": "prediction.json", "line": 1}])

    def test_vo2_c7_16_complete_but_swt_failure(self):
        res = self.evaluate(score=m.score("x", swt=False))
        self.expect(res, {"PC11": "fail"})
        self.assertEqual(res["checks"]["PC11"]["evidence"], [{"file": "prediction.json", "line": 1}])


# ----------------------------------------------------------------------------------------------
# VO2: edge classes C8
# ----------------------------------------------------------------------------------------------

class EdgeTests(ProcessCase):
    def test_vo2_c8_main_test_edit_before_the_first_spec_write_passes_pc8(self):
        early = L(None, "Edit", file_path=tb(m.TEST_FILE), old_string="a", new_string="b")
        res = self.evaluate(ledger=ledger_with(0, [early]))
        self.expect(res, {"PC12": "fail"})

    def test_vo2_c8_bash_naming_a_directory_entry_does_not_match_pc9(self):
        diff = m.archived_diff(tests=[m.TEST_FILE, "tests/unit"], impl=[m.IMPL_FILE, "src/pkg"])
        rows = [L("implementer", "Bash", command="python -m pytest tests/unit -q"),
                L("test-implementer", "Bash", command="ls src/pkg"),
                L("test-verifier", "Bash", command="python -m pytest tests/unit -q")]
        res = self.evaluate(diff=diff, ledger=ledger_with(5, rows))
        self.expect(res)

    def test_vo2_c8_absolute_path_outside_testbed_never_matches(self):
        outside = "/home/user/" + m.TEST_FILE
        rows_main = [L(None, "Edit", file_path=outside, old_string="a", new_string="b")]
        res = self.evaluate(ledger=ledger_with(5, rows_main))
        self.expect(res)
        rows = [L("implementer", "Read", file_path=outside), L("implementer", "Grep", path="/home/user/tests")]
        res = self.evaluate(ledger=ledger_with(5, rows))
        self.expect(res)


# ----------------------------------------------------------------------------------------------
# VO2: missing-input classes C9
# ----------------------------------------------------------------------------------------------

class MissingInputTests(ProcessCase):
    def test_vo2_c9_missing_telemetry_dir(self):
        res = self.evaluate(events=None)
        self.expect(res, {"PC1": "fail", "PC2": "fail", "PC3": "n/a", "PC4": "n/a", "PC5": "n/a", "PC7": "n/a",
                          "PC8": "n/a", "PC9": "n/a", "PC10": "n/a", "PC11": "n/a", "PC12": "n/a"})
        self.assertEqual(res["checks"]["PC1"]["evidence"], [])
        self.assertEqual(res["skipped_lines"], 0)
        self.assertIsNone(res["workflow_run_id"])
        self.assertIsNone(res["end_status"])

    def test_vo2_c9_missing_ledger(self):
        res = self.evaluate(ledger=None)
        self.expect(res, {"PC8": "n/a", "PC10": "n/a", "PC12": "n/a"})
        self.assertEqual(res["metrics"]["verifier_dispatches"], 0)
        self.assertEqual(res["metrics"]["subagent_dispatches"], {})

    def test_vo2_c9_missing_full_diff(self):
        res = self.evaluate(diff=None)
        self.expect(res, {"PC7": "fail", "PC8": "n/a", "PC9": "n/a", "PC10": "n/a", "PC12": "n/a"})
        self.assertEqual(res["checks"]["PC7"]["evidence"], [])

    def test_vo2_c9_missing_prediction(self):
        res = self.evaluate(prediction_=None)
        self.expect(res, {"PC6": "n/a"})

    def test_vo2_c9_garbage_lines_are_skipped_and_counted_without_changing_verdicts(self):
        events = {"a.jsonl": m.compliant_events() + ["not json", "[1, 2]"]}
        ledger = m.compliant_ledger_items() + ["{broken", '"a string"', "7"]
        res = self.evaluate(events=events, ledger=ledger)
        self.expect(res)
        self.assertEqual(res["skipped_lines"], 5)

    def test_vo2_c9_blank_lines_are_ignored_and_not_counted(self):
        events = {"a.jsonl": [""] + m.compliant_events() + ["", "junk"]}
        ledger = ["", ""] + m.compliant_ledger_items() + [""]
        res = self.evaluate(events=events, ledger=ledger)
        self.expect(res)
        self.assertEqual(res["skipped_lines"], 1)

    def test_vo2_c9_evidence_uses_physical_line_numbers_after_garbage_and_blank_lines(self):
        edit = L(None, "Edit", file_path=tb(m.TEST_FILE), old_string="a", new_string="b")
        items = ledger_with(5, [edit])
        res = self.evaluate(ledger=["garbage", ""] + items)
        self.expect(res, {"PC8": "fail"})
        self.assertEqual(self.evidence(res, "PC8"), {(LEDGER, 8)})
        events = m.reseq(m.compliant_events()[:5] + [E("seed", action="backup"), E("seed", action="restore"),
                                                    E("seed", action="backup"), E("workflow_end", status="complete")])
        res = self.evaluate(events={"a.jsonl": ["junk", ""] + events})
        self.assertEqual(self.evidence(res, "PC5"), {(TELEMETRY, 10)})

    def test_vo2_c7_pc10_evidence_lists_every_offending_ledger_line(self):
        rows = [L("implementer", "Edit", file_path=tb(m.IMPL_FILE)), L("test-implementer", "Write", file_path=tb(m.TEST_FILE)),
                L(None, "Edit", file_path=tb("README.md"))]
        res = self.evaluate(ledger=ledger_with(None, rows))
        self.assertEqual(res["checks"]["PC10"]["verdict"], "fail")
        self.assertEqual(self.evidence(res, "PC10"), {(LEDGER, 9), (LEDGER, 10)})

    def test_vo2_c9_a_json_object_line_is_not_garbage(self):
        res = self.evaluate(ledger=m.compliant_ledger_items() + [{"unrelated": True}])
        self.assertEqual(res["skipped_lines"], 0)


# ----------------------------------------------------------------------------------------------
# VO2: baseline arm C10
# ----------------------------------------------------------------------------------------------

class BaselineArmTests(ProcessCase):
    def test_vo2_c10_every_check_is_na_with_the_baseline_detail(self):
        res = self.evaluate(arm="baseline", manifest={"instance_id": "b1", "arm": "baseline"})
        self.assertEqual(res["arm"], "baseline")
        self.assertEqual(set(res["checks"]), set(m.CHECK_IDS))
        for cid, check in res["checks"].items():
            self.assertEqual(check["verdict"], "n/a", cid)
            self.assertEqual(check["detail"], "baseline arm", cid)

    def test_vo2_c10_arm_falls_back_to_the_directory_name(self):
        res = self.evaluate(arm="baseline", manifest=None)
        self.assertEqual(res["arm"], "baseline")
        self.assertEqual({c["verdict"] for c in res["checks"].values()}, {"n/a"})


# ----------------------------------------------------------------------------------------------
# VO2: identity, ordering, spec parsing, per-check partitions
# ----------------------------------------------------------------------------------------------

class IdentityAndOrderingTests(ProcessCase):
    def test_vo2_c6_workflow_identity_is_the_first_workflow_start_and_run_events_filter_by_it(self):
        events = m.compliant_events() + [
            E("workflow_start", run="OTHER", spec="other"),
            E("verifier_result", run="OTHER", spec="other", result="pass"),
            E("verifier_result", run="OTHER", spec="other", result="pass"),
            E("verifier_result", run="OTHER", spec="other", result="pass"),
        ]
        res = self.evaluate(events=m.reseq(events))
        self.assertEqual(res["workflow_run_id"], m.WF)
        self.assertEqual(res["checks"]["PC3"]["verdict"], "pass")
        self.assertEqual(res["metrics"]["verifier_results"], 1)

    def test_vo2_c6_events_across_files_are_ordered_by_ts_not_by_file_name(self):
        events = m.compliant_events()
        split = {"b.jsonl": events[:6], "a.jsonl": events[6:]}
        res = self.evaluate(events=split)
        self.expect(res)

    def test_vo2_c6_equal_timestamps_keep_file_order(self):
        events = m.compliant_events()
        for e in events:
            e["ts"] = m.ts(0)
        res = self.evaluate(events=events)
        self.expect(res)

    def test_vo2_c7_no_workflow_end_adds_no_workflow_end_to_the_compliance_detail(self):
        res = self.evaluate(events=events_with(lambda e: e[:-1]))
        self.expect(res, {"PC2": "fail", "PC4": "n/a", "PC7": "n/a", "PC11": "n/a"})
        self.assertIn("no_workflow_end", res["checks"]["PC2"]["detail"])
        self.assertIsNone(res["end_status"])


class SpecTextTests(ProcessCase):
    def test_vo2_c6_spec_lists_strip_whitespace_and_backticks(self):
        diff = m.archived_diff(impl=["`%s`" % m.IMPL_FILE, " src/other.py "], tests=["  `tests/a.py` ", "tests/b.py"])
        rows = [L("implementer", "Read", file_path=tb("tests/a.py"))]
        res = self.evaluate(diff=diff, ledger=ledger_with(5, rows))
        self.assertEqual(res["checks"]["PC9"]["verdict"], "fail")
        rows = [L("test-implementer", "Read", file_path=tb("src/other.py"))]
        res = self.evaluate(diff=diff, ledger=ledger_with(3, rows))
        self.assertEqual(res["checks"]["PC9"]["verdict"], "fail")

    def test_vo2_c6_only_the_first_implementation_and_tests_lines_count(self):
        diff = m.archived_diff(tail=["Implementation: src/late.py", "Tests: tests/late.py"])
        rows = [L("implementer", "Read", file_path=tb("tests/late.py")),
                L("test-implementer", "Read", file_path=tb("src/late.py"))]
        res = self.evaluate(diff=diff, ledger=ledger_with(5, rows))
        self.expect(res)

    def test_vo2_c6_decoy_sections_of_other_files_are_not_parsed(self):
        rows = [L("implementer", "Read", file_path=tb("tests/decoy.py")),
                L("test-implementer", "Read", file_path=tb("decoy_impl.py"))]
        res = self.evaluate(ledger=ledger_with(5, rows))
        self.expect(res)

    def test_vo2_c6_spec_of_another_workflow_run_is_ignored(self):
        diff = m.decoy_section() + m.new_file_section(
            "%s/%s-feat.md" % (m.SPEC_LOGS, "otherrun"), m.spec_lines("aborted", tests=["tests/foreign.py"])
        ) + m.new_file_section(m.ARCHIVE_REL, m.spec_lines("complete"))
        rows = [L("implementer", "Read", file_path=tb("tests/foreign.py"))]
        res = self.evaluate(diff=diff, ledger=ledger_with(5, rows))
        self.expect(res)

    def test_vo2_c6_spec_logs_section_wins_over_the_specs_section(self):
        diff = m.new_file_section(m.SPEC_REL, m.spec_lines("active")) + m.new_file_section(
            m.ARCHIVE_REL, m.spec_lines("complete"))
        self.expect(self.evaluate(diff=diff))

    def test_vo2_c6_specs_section_is_used_when_no_archive_exists(self):
        diff = m.new_file_section(m.SPEC_REL, m.spec_lines("complete"))
        res = self.evaluate(diff=diff)
        self.expect(res, {"PC7": "fail"})

    def test_vo2_c7_no_spec_in_the_diff_fails_pc7_and_makes_spec_dependent_checks_na(self):
        res = self.evaluate(diff=m.decoy_section())
        self.expect(res, {"PC7": "fail", "PC8": "n/a", "PC9": "n/a", "PC10": "n/a", "PC12": "n/a"})


class Pc7Tests(ProcessCase):
    def test_vo2_pc7_handoff_with_an_active_spec_in_specs_passes(self):
        events = m.reseq([E("workflow_start"), E("seed", action="backup"), E("seed", action="restore"),
                          E("workflow_end", status="handoff")])
        res = self.evaluate(events=events, diff=m.archived_diff(status="active", where=m.SPECS))
        self.expect(res, {"PC4": "n/a", "PC10": "n/a", "PC11": "n/a"})

    def test_vo2_pc7_handoff_with_an_active_spec_in_spec_logs_fails(self):
        events = m.reseq([E("workflow_start"), E("seed", action="backup"), E("seed", action="restore"),
                          E("workflow_end", status="handoff")])
        res = self.evaluate(events=events, diff=m.archived_diff(status="active"))
        self.assertEqual(res["checks"]["PC7"]["verdict"], "fail")

    def test_vo2_pc7_aborted_and_limit_need_the_archive_with_the_same_status(self):
        aborted = m.reseq([E("workflow_start"), E("seed", action="backup"), E("seed", action="restore"),
                           E("workflow_end", status="aborted")])
        res = self.evaluate(events=aborted, diff=m.archived_diff(status="aborted"))
        self.assertEqual(res["checks"]["PC7"]["verdict"], "pass")
        res = self.evaluate(events=aborted, diff=m.archived_diff(status="complete"))
        self.assertEqual(res["checks"]["PC7"]["verdict"], "fail")
        limit = m.reseq([E("workflow_start"), E("workflow_phase", phase="implement_test"),
                         E("workflow_phase", phase="verify"), E("verifier_result", result="limit"),
                         E("seed", action="backup"), E("seed", action="restore"),
                         E("workflow_end", status="limit")])
        res = self.evaluate(events=limit, diff=m.archived_diff(status="limit"))
        self.assertEqual(res["checks"]["PC7"]["verdict"], "pass")
        self.assertEqual(res["checks"]["PC11"]["verdict"], "n/a")
        res = self.evaluate(events=limit, diff=m.archived_diff(status="active", where=m.SPECS))
        self.assertEqual(res["checks"]["PC7"]["verdict"], "fail")


class Pc8Tests(ProcessCase):
    def test_vo2_pc8_is_na_without_a_ledger_row_editing_a_spec(self):
        items = m.compliant_ledger_items()[1:] + [L(None, "Edit", file_path=tb(m.TEST_FILE))]
        res = self.evaluate(ledger=items)
        self.assertEqual(res["checks"]["PC8"]["verdict"], "n/a")

    def test_vo2_pc8_read_of_a_spec_does_not_start_the_window(self):
        items = [L(None, "Read", file_path=tb(m.SPEC_REL))] + m.compliant_ledger_items()[1:] + [
            L(None, "Edit", file_path=tb(m.TEST_FILE))]
        self.assertEqual(self.evaluate(ledger=items)["checks"]["PC8"]["verdict"], "n/a")

    def test_vo2_pc8_every_edit_tool_counts_and_only_main_rows_count(self):
        for tool, key in (("Edit", "file_path"), ("Write", "file_path"), ("MultiEdit", "file_path"),
                          ("NotebookEdit", "notebook_path")):
            with self.subTest(tool=tool):
                res = self.evaluate(ledger=ledger_with(5, [L(None, tool, **{key: tb(m.TEST_FILE)})]))
                self.assertEqual(res["checks"]["PC8"]["verdict"], "fail")
        res = self.evaluate(ledger=ledger_with(5, [L("test-implementer", "Edit", file_path=tb(m.TEST_FILE))]))
        self.assertEqual(res["checks"]["PC8"]["verdict"], "pass")
        res = self.evaluate(ledger=ledger_with(5, [L(None, "Read", file_path=tb(m.TEST_FILE))]))
        self.assertEqual(res["checks"]["PC8"]["verdict"], "pass")

    def test_vo2_pc8_edit_of_a_non_tests_path_passes(self):
        res = self.evaluate(ledger=ledger_with(5, [L(None, "Edit", file_path=tb("README.md"))]))
        self.assertEqual(res["checks"]["PC8"]["verdict"], "pass")

    def test_vo2_pc8_evidence_lists_every_offending_ledger_line(self):
        edit = L(None, "Edit", file_path=tb(m.TEST_FILE))
        res = self.evaluate(ledger=ledger_with(5, [edit, edit]))
        self.assertEqual(self.evidence(res, "PC8"), {(LEDGER, 6), (LEDGER, 7)})


PC9_CASES = [
    # label, agent_type, tool, input, tests, impl, expected
    ("implementer-read-abs-exact", "implementer", "Read", {"file_path": tb("tests/test_x.py")}, ["tests/test_x.py"], ["src/a.py"], "fail"),
    ("implementer-read-relative", "implementer", "Read", {"file_path": "tests/test_x.py"}, ["tests/test_x.py"], ["src/a.py"], "fail"),
    ("implementer-read-under-directory-entry", "implementer", "Read", {"file_path": tb("tests/unit/test_a.py")}, ["tests/unit"], ["src/a.py"], "fail"),
    ("implementer-read-sibling-prefix-not-matched", "implementer", "Read", {"file_path": tb("tests/unit2/test_a.py")}, ["tests/unit"], ["src/a.py"], "pass"),
    ("implementer-read-glob-entry", "implementer", "Read", {"file_path": tb("tests/test_y.py")}, ["tests/test_*.py"], ["src/a.py"], "fail"),
    ("implementer-grep-path-equal-to-entry", "implementer", "Grep", {"path": tb("tests/unit"), "pattern": "x"}, ["tests/unit"], ["src/a.py"], "fail"),
    ("implementer-glob-path", "implementer", "Glob", {"path": tb("tests/unit"), "pattern": "*"}, ["tests/unit"], ["src/a.py"], "fail"),
    ("implementer-notebook-edit", "implementer", "NotebookEdit", {"notebook_path": tb("tests/nb.ipynb")}, ["tests/nb.ipynb"], ["src/a.py"], "fail"),
    ("implementer-multiedit", "implementer", "MultiEdit", {"file_path": tb("tests/test_x.py")}, ["tests/test_x.py"], ["src/a.py"], "fail"),
    ("implementer-outside-testbed", "implementer", "Edit", {"file_path": "/home/x/tests/test_x.py"}, ["tests/test_x.py"], ["src/a.py"], "pass"),
    ("implementer-bash-file-entry", "implementer", "Bash", {"command": "cat tests/test_x.py"}, ["tests/test_x.py"], ["src/a.py"], "fail"),
    ("implementer-bash-directory-entry", "implementer", "Bash", {"command": "pytest tests/unit"}, ["tests/unit"], ["src/a.py"], "pass"),
    ("implementer-reads-implementation", "implementer", "Read", {"file_path": tb("src/a.py")}, ["tests/test_x.py"], ["src/a.py"], "pass"),
    ("test-implementer-reads-implementation", "test-implementer", "Read", {"file_path": tb("src/a.py")}, ["tests/test_x.py"], ["src/a.py"], "fail"),
    ("test-implementer-reads-tests", "test-implementer", "Read", {"file_path": tb("tests/test_x.py")}, ["tests/test_x.py"], ["src/a.py"], "pass"),
    ("test-implementer-bash-file-entry", "test-implementer", "Bash", {"command": "cat src/a.py"}, ["tests/test_x.py"], ["src/a.py"], "fail"),
    ("test-verifier-reads-under-implementation-directory", "test-verifier", "Read", {"file_path": tb("src/pkg/sub/a.py")}, ["tests/test_x.py"], ["src/pkg"], "fail"),
    ("test-verifier-bash-implementation-file", "test-verifier", "Bash", {"command": "cat src/a.py"}, ["tests/test_x.py"], ["src/a.py"], "fail"),
    ("test-verifier-bash-dotted-directory-entry-with-slash", "test-verifier", "Bash", {"command": "cat src.v2/pkg/a.py"}, ["tests/test_x.py"], ["src.v2/pkg/"], "fail"),
    ("test-verifier-bash-dotted-directory-entry", "test-verifier", "Bash", {"command": "cat src.v2/pkg/a.py"}, ["tests/test_x.py"], ["src.v2/pkg"], "fail"),
    ("main-reads-tests", None, "Read", {"file_path": tb("tests/test_x.py")}, ["tests/test_x.py"], ["src/a.py"], "pass"),
]


class Pc9Tests(ProcessCase):
    def test_vo2_pc9_path_and_role_partitions(self):
        for label, agent_type, tool, tool_input, tests, impl, expected in PC9_CASES:
            with self.subTest(label):
                spec_row = L(None, "Write", file_path=tb(m.SPEC_REL))
                ledger = [spec_row, (agent_type, tool, tool_input)]
                res = self.evaluate(diff=m.archived_diff(tests=tests, impl=impl), ledger=ledger)
                self.assertEqual(res["checks"]["PC9"]["verdict"], expected)
                if expected == "fail":
                    self.assertEqual(self.evidence(res, "PC9"), {(LEDGER, 2)})


class Pc10Tests(ProcessCase):
    def test_vo2_pc10_later_edit_of_either_list_fails_and_unlisted_or_read_passes(self):
        cases = (
            ("impl edit", L("implementer", "Edit", file_path=tb(m.IMPL_FILE)), "fail"),
            ("tests edit by test-implementer", L("test-implementer", "Edit", file_path=tb(m.TEST_FILE)), "fail"),
            ("unlisted edit", L(None, "Edit", file_path=tb("README.md")), "pass"),
            ("read of implementation", L(None, "Read", file_path=tb(m.IMPL_FILE)), "pass"),
        )
        for label, row, expected in cases:
            with self.subTest(label):
                res = self.evaluate(ledger=ledger_with(None, [row]))
                self.assertEqual(res["checks"]["PC10"]["verdict"], expected)

    def test_vo2_pc10_is_na_unless_the_last_verifier_result_is_pass(self):
        limit = verifier_events(["limit"], end="limit")
        row = L("implementer", "Edit", file_path=tb(m.IMPL_FILE))
        res = self.evaluate(events=limit, diff=m.archived_diff(status="limit"), ledger=ledger_with(None, [row]))
        self.assertEqual(res["checks"]["PC10"]["verdict"], "n/a")
        mixed = verifier_events(["pass", "fail"], end="limit")
        res = self.evaluate(events=mixed, diff=m.archived_diff(status="limit"), ledger=ledger_with(None, [row]))
        self.assertEqual(res["checks"]["PC10"]["verdict"], "n/a")

    def test_vo2_pc10_is_na_without_any_anchor(self):
        res = self.evaluate(ledger=m.compliant_ledger_items()[:5] + [L("implementer", "Edit", file_path=tb(m.IMPL_FILE))])
        self.assertEqual(res["checks"]["PC10"]["verdict"], "n/a")

    def test_vo2_pc10_main_dispatch_is_the_anchor_when_no_subagent_row_exists(self):
        items = m.compliant_ledger_items()[:6]
        res = self.evaluate(ledger=items)
        self.assertEqual(res["checks"]["PC10"]["verdict"], "pass")
        res = self.evaluate(ledger=items + [L("implementer", "Edit", file_path=tb(m.IMPL_FILE))])
        self.assertEqual(res["checks"]["PC10"]["verdict"], "fail")

    def test_vo2_pc10_anchor_is_the_last_test_verifier_row(self):
        items = m.compliant_ledger_items()
        items = items[:7] + [L("implementer", "Edit", file_path=tb(m.IMPL_FILE))] + items[7:]
        res = self.evaluate(ledger=items)
        self.assertEqual(res["checks"]["PC10"]["verdict"], "pass")

    def test_vo2_pc10_is_na_without_spec_text(self):
        row = L("implementer", "Edit", file_path=tb(m.IMPL_FILE))
        res = self.evaluate(diff=None, ledger=ledger_with(None, [row]))
        self.assertEqual(res["checks"]["PC10"]["verdict"], "n/a")


def run_scoped(base, extra):
    return m.reseq(base + extra)


class RunScopingTests(ProcessCase):
    def test_vo2_f4_pc4_verification_result_of_another_run_does_not_count(self):
        events = [dict(e, workflow_run_id="OTHER") if e["event"] == "verification_result" else e
                  for e in m.compliant_events()]
        res = self.evaluate(events=events)
        self.assertEqual(res["checks"]["PC4"]["verdict"], "fail")

    def test_vo2_f4_pc4_verification_result_after_workflow_end_fails(self):
        events = m.compliant_events()
        vr = events.pop(4)
        res = self.evaluate(events=m.reseq(events + [vr]))
        self.assertEqual(res["checks"]["PC4"]["verdict"], "fail")

    def test_vo2_f4_pc5_other_runs_seed_events_are_ignored(self):
        events = m.compliant_events()
        noise = lambda a: E("seed", run="OTHER", spec="other", action=a)
        mixed = events[:5] + [events[5], noise("backup"), noise("backup"), events[6], noise("restore")] + events[7:]
        res = self.evaluate(events=m.reseq(mixed))
        self.assertEqual(res["checks"]["PC5"]["verdict"], "pass")
        self.assertEqual(res["metrics"]["seed_pairs"], 1)

    def test_vo2_f4_pc5_final_restore_after_workflow_end_fails(self):
        events = m.compliant_events()
        restore = events.pop(6)
        res = self.evaluate(events=m.reseq(events + [restore]))
        self.assertEqual(res["checks"]["PC5"]["verdict"], "fail")

    def test_vo2_f4_pc10_other_runs_later_pass_does_not_apply_when_own_last_is_retry(self):
        events = verifier_events(["retry"], end="limit")
        events = m.reseq(events + [E("verifier_result", run="OTHER", spec="other", result="pass")])
        row = L("implementer", "Edit", file_path=tb(m.IMPL_FILE))
        res = self.evaluate(events=events, diff=m.archived_diff(status="limit"), ledger=ledger_with(None, [row]))
        self.assertEqual(res["checks"]["PC10"]["verdict"], "n/a")

    def test_vo2_f4_pc10_other_runs_later_retry_does_not_hide_own_last_pass(self):
        events = m.reseq(m.compliant_events() + [E("verifier_result", run="OTHER", spec="other", result="retry")])
        row = L("implementer", "Edit", file_path=tb(m.IMPL_FILE))
        res = self.evaluate(events=events, ledger=ledger_with(None, [row]))
        self.assertEqual(res["checks"]["PC10"]["verdict"], "fail")


class PinnedBehaviourTests(ProcessCase):
    def test_vo2_g8_no_full_diff_with_a_main_edit_after_a_spec_write_counts_no_implementation_edits(self):
        items = [L(None, "Write", file_path=tb(m.SPEC_REL)), L(None, "Edit", file_path=tb(m.IMPL_FILE))]
        res = self.evaluate(diff=None, ledger=items)
        self.assertEqual(res["metrics"]["main_implementation_edits"], 0)
        self.assertEqual(res["checks"]["PC8"]["verdict"], "n/a")

    def test_vo2_v5_spec_text_without_frontmatter_fails_pc7(self):
        lines = ["status: complete", "Implementation: " + m.IMPL_FILE, "Tests: " + m.TEST_FILE]
        res = self.evaluate(diff=m.new_file_section(m.ARCHIVE_REL, lines))
        self.assertEqual(res["checks"]["PC7"]["verdict"], "fail")

    def test_vo2_v5_non_string_empty_or_null_ledger_paths_are_ignored_without_exception(self):
        rows = [
            L("implementer", "Read", file_path=5), L("implementer", "Read", file_path=""),
            L("implementer", "Read", file_path=None), L("implementer", "Grep", path=5),
            L("implementer", "NotebookEdit", notebook_path=None), L("test-implementer", "Glob", path=""),
            L(None, "Edit", file_path=5), L(None, "Edit", file_path=""), L(None, "Write", file_path=None),
            L("implementer", "Read"),
        ]
        res = self.evaluate(ledger=ledger_with(5, rows))
        self.expect(res)

    def test_vo2_v5_pc5_evidence_includes_a_restore_that_follows_workflow_end(self):
        events = m.compliant_events()
        restore = events.pop(6)
        res = self.evaluate(events=m.reseq(events + [restore]))
        self.assertEqual(res["checks"]["PC5"]["verdict"], "fail")
        self.assertIn((TELEMETRY, 8), self.evidence(res, "PC5"))


class Pc10EditToolTests(ProcessCase):
    def test_vo2_eg2_main_agent_edits_after_the_final_pass_fail_pc10_with_that_line(self):
        cases = (
            ("main Edit of an implementation path", L(None, "Edit", file_path=tb(m.IMPL_FILE))),
            ("main MultiEdit of a tests path", L(None, "MultiEdit", file_path=tb(m.TEST_FILE))),
            ("main NotebookEdit of a tests path", L(None, "NotebookEdit", notebook_path=tb(m.TEST_FILE))),
        )
        for label, row in cases:
            with self.subTest(label):
                res = self.evaluate(ledger=ledger_with(None, [row]))
                self.assertEqual(res["checks"]["PC10"]["verdict"], "fail")
                self.assertEqual(self.evidence(res, "PC10"), {(LEDGER, 9)})

    def test_vo2_eg_seed_before_text_only_needs_to_contain_seed_none(self):
        res = self.evaluate(prediction_=m.prediction(seed_before="x\nseed: none\n"))
        self.assertEqual(res["checks"]["PC6"]["verdict"], "pass")

    def test_vo2_eg_pc5_evidence_names_the_telemetry_file_holding_the_unpaired_event(self):
        events = seq_events(["backup", "restore", "backup"])
        res = self.evaluate(events={"a.jsonl": events[:7], "b.jsonl": events[7:]})
        self.assertEqual(res["checks"]["PC5"]["verdict"], "fail")
        self.assertEqual(self.evidence(res, "PC5"), {("raw/telemetry/b.jsonl", 1)})


class Pc11Tests(ProcessCase):
    def test_vo2_pc11_na_without_a_score_and_for_a_non_complete_end(self):
        self.assertEqual(self.evaluate(score=None)["checks"]["PC11"]["verdict"], "n/a")
        limit = verifier_events(["limit"], end="limit")
        res = self.evaluate(events=limit, diff=m.archived_diff(status="limit"), score=m.score("x", resolved=False))
        self.assertEqual(res["checks"]["PC11"]["verdict"], "n/a")

    def test_vo2_pc11_each_condition_alone_fails_and_both_true_passes(self):
        for kw, expected in (({}, "pass"), ({"resolved": False}, "fail"), ({"swt": False}, "fail"),
                             ({"resolved": False, "swt": False}, "fail")):
            with self.subTest(kw=kw):
                self.assertEqual(self.evaluate(score=m.score("x", **kw))["checks"]["PC11"]["verdict"], expected)


# ----------------------------------------------------------------------------------------------
# VO3: PC3 counts and PC5 sequences (boundary value analysis, 2-value)
# ----------------------------------------------------------------------------------------------

class BoundaryTests(ProcessCase):
    def test_vo3_pc3_verifier_results_at_two_pass_and_three_fail(self):
        self.assertEqual(self.evaluate(events=verifier_events(["fail", "pass"]))["checks"]["PC3"]["verdict"], "pass")
        self.assertEqual(self.evaluate(events=verifier_events(["fail", "fail", "pass"]))["checks"]["PC3"]["verdict"], "fail")

    def test_vo3_pc3_verifier_dispatches_at_two_pass_and_three_fail(self):
        dispatch = L(None, "Agent", subagent_type="test-verifier", prompt="v")
        two = self.evaluate(ledger=ledger_with(5, [dispatch]))
        three = self.evaluate(ledger=ledger_with(5, [dispatch, dispatch]))
        self.assertEqual(two["checks"]["PC3"]["verdict"], "pass")
        self.assertEqual(three["checks"]["PC3"]["verdict"], "fail")

    def test_vo3_pc3_a_task_tool_dispatch_counts_toward_the_limit(self):
        agent = L(None, "Agent", subagent_type="test-verifier", prompt="v")
        task = L(None, "Task", subagent_type="test-verifier", prompt="v")
        res = self.evaluate(ledger=ledger_with(5, [agent, task]))
        self.assertEqual(res["checks"]["PC3"]["verdict"], "fail")

    def test_vo3_pc5_seed_sequences(self):
        cases = (
            ("empty", [], "fail"),
            ("backup restore", ["backup", "restore"], "pass"),
            ("backup backup restore", ["backup", "backup", "restore"], "fail"),
            ("backup restore backup", ["backup", "restore", "backup"], "fail"),
            ("restore only", ["restore"], "fail"),
            ("two pairs", ["backup", "restore", "backup", "restore"], "pass"),
            ("restore first", ["restore", "backup"], "fail"),
            ("other actions ignored", ["backup", "status", "restore"], "pass"),
        )
        for label, actions, expected in cases:
            with self.subTest(label):
                res = self.evaluate(events=seq_events(actions))
                self.assertEqual(res["checks"]["PC5"]["verdict"], expected)
                if expected == "fail" and actions:
                    seeds = {(TELEMETRY, 6 + i) for i, a in enumerate(actions) if a in ("backup", "restore")}
                    self.assertTrue(self.evidence(res, "PC5"))
                    self.assertLessEqual(self.evidence(res, "PC5"), seeds)

    def test_vo3_pc5_seed_pairs_metric_counts_completed_pairs(self):
        for actions, pairs in ((["backup", "restore"], 1), (["backup", "restore", "backup", "restore"], 2),
                               (["backup", "restore", "backup"], 1), ([], 0)):
            with self.subTest(actions=actions):
                self.assertEqual(self.evaluate(events=seq_events(actions))["metrics"]["seed_pairs"], pairs)

    def test_vo3_pc5_is_na_without_a_workflow_start(self):
        res = self.evaluate(events=m.reseq([E("seed", action="backup")]))
        self.assertEqual(res["checks"]["PC5"]["verdict"], "n/a")


# ----------------------------------------------------------------------------------------------
# O3: F8 decision table, spec spec 2974883932c47b32 v1 (Bash rows write paths)
# ----------------------------------------------------------------------------------------------

SPEC_HEREDOC = "cat > %s <<'EOF'\n---\nstatus: active\nEOF" % m.SPEC_REL
TEST_SED = "sed -i 's/a/b/' %s" % m.TEST_FILE
TEST_HEREDOC = "cat >> %s <<'EOF'\ndef test_n(): pass\nEOF" % m.TEST_FILE
IMPL_SED = "sed -i 's/a/b/' %s" % m.IMPL_FILE


def spec_row(kind):
    if kind == "Edit":
        return L(None, "Edit", file_path=tb(m.SPEC_REL), old_string="a", new_string="b")
    return L(None, "Bash", command=SPEC_HEREDOC)


def test_write_row(kind):
    if kind == "Edit":
        return L(None, "Edit", file_path=tb(m.TEST_FILE), old_string="a", new_string="b")
    return L(None, "Bash", command=TEST_SED)


def with_spec_row(kind, rows=(), at=1):
    base = m.compliant_ledger_items()
    base[0] = spec_row(kind)
    return base[:at] + list(rows) + base[at:]


class Pc8BashDecisionTableTests(ProcessCase):
    def test_o3_r1_spec_by_edit_and_main_test_write_by_edit_fails(self):
        res = self.evaluate(ledger=with_spec_row("Edit", [test_write_row("Edit")], at=5))
        self.assertEqual(res["checks"]["PC8"]["verdict"], "fail")
        self.assertEqual(self.evidence(res, "PC8"), {(LEDGER, 6)})

    def test_o3_r2_spec_by_edit_and_main_test_write_by_bash_sed_fails_with_that_row(self):
        res = self.evaluate(ledger=with_spec_row("Edit", [test_write_row("Bash")], at=5))
        self.assertEqual(res["checks"]["PC8"]["verdict"], "fail")
        self.assertEqual(self.evidence(res, "PC8"), {(LEDGER, 6)})

    def test_o3_r3_spec_by_edit_and_no_later_main_test_write_passes(self):
        res = self.evaluate(ledger=with_spec_row("Edit"))
        self.assertEqual(res["checks"]["PC8"]["verdict"], "pass")

    def test_o3_r4_spec_by_bash_and_main_test_write_by_edit_fails(self):
        res = self.evaluate(ledger=with_spec_row("Bash", [test_write_row("Edit")], at=5))
        self.assertEqual(res["checks"]["PC8"]["verdict"], "fail")
        self.assertEqual(self.evidence(res, "PC8"), {(LEDGER, 6)})

    def test_o3_c12_spec_by_bash_and_main_test_write_by_bash_fails_with_the_sed_row(self):
        res = self.evaluate(ledger=with_spec_row("Bash", [test_write_row("Bash")], at=5))
        self.assertEqual(res["checks"]["PC8"]["verdict"], "fail")
        self.assertEqual(self.evidence(res, "PC8"), {(LEDGER, 6)})

    def test_o3_r6_spec_by_bash_and_no_later_main_test_write_is_pass_not_na(self):
        res = self.evaluate(ledger=with_spec_row("Bash"))
        self.assertEqual(res["checks"]["PC8"]["verdict"], "pass")

    def test_o3_bash_heredoc_test_write_by_main_fails(self):
        res = self.evaluate(ledger=with_spec_row("Bash", [L(None, "Bash", command=TEST_HEREDOC)], at=5))
        self.assertEqual(res["checks"]["PC8"]["verdict"], "fail")
        self.assertEqual(self.evidence(res, "PC8"), {(LEDGER, 6)})

    def test_o3_bash_rows_that_do_not_write_tests_pass(self):
        cases = (
            ("subagent bash write", L("test-implementer", "Bash", command=TEST_SED)),
            ("main bash read", L(None, "Bash", command="cat " + m.TEST_FILE)),
            ("main bash test run", L(None, "Bash", command="python -m pytest %s -q" % m.TEST_FILE)),
            ("main bash write elsewhere", L(None, "Bash", command="echo x > README.md")),
            ("main bash non-string command", L(None, "Bash", command=5)),
            ("main bash missing command", L(None, "Bash")),
        )
        for label, row in cases:
            with self.subTest(label):
                res = self.evaluate(ledger=with_spec_row("Bash", [row], at=5))
                self.assertEqual(res["checks"]["PC8"]["verdict"], "pass")

    def test_o3_bash_test_write_before_the_first_spec_write_passes(self):
        res = self.evaluate(ledger=[test_write_row("Bash")] + with_spec_row("Edit"))
        self.assertEqual(res["checks"]["PC8"]["verdict"], "pass")

    def test_o3_spec_write_with_unresolved_variable_matches_by_directory_prefix(self):
        cmd = "F=agent-docs/specs/$RID-x.md; cat > $F <<'EOF'\nx\nEOF"
        items = m.compliant_ledger_items()
        items[0] = L(None, "Bash", command=cmd)
        res = self.evaluate(ledger=items[:5] + [test_write_row("Edit")] + items[5:])
        self.assertEqual(res["checks"]["PC8"]["verdict"], "fail")
        self.assertEqual(self.evidence(res, "PC8"), {(LEDGER, 6)})

    def test_o3_unresolved_variable_in_a_test_path_matches_only_by_directory_prefix(self):
        diff = m.archived_diff(tests=["tests/unit"])
        for label, cmd, expected in (
            ("inside tests directory entry", "cat > tests/unit/$N.py <<'EOF'\nx\nEOF", "fail"),
            ("other directory", "cat > other/$N.py <<'EOF'\nx\nEOF", "pass"),
        ):
            with self.subTest(label):
                row = L(None, "Bash", command=cmd)
                res = self.evaluate(diff=diff, ledger=with_spec_row("Edit", [row], at=5))
                self.assertEqual(res["checks"]["PC8"]["verdict"], expected)


class Pc10AndMetricBashTests(ProcessCase):
    def test_o3_pc10_bash_edit_after_the_final_pass_fails_for_each_role(self):
        cases = (
            ("implementer sed impl", L("implementer", "Bash", command=IMPL_SED)),
            ("test-implementer heredoc tests", L("test-implementer", "Bash", command=TEST_HEREDOC)),
            ("main sed tests", L(None, "Bash", command=TEST_SED)),
        )
        for label, row in cases:
            with self.subTest(label):
                res = self.evaluate(ledger=ledger_with(None, [row]))
                self.assertEqual(res["checks"]["PC10"]["verdict"], "fail")
                self.assertEqual(self.evidence(res, "PC10"), {(LEDGER, 9)})

    def test_o3_pc10_bash_rows_that_do_not_edit_listed_paths_pass(self):
        cases = (
            ("read impl", L("implementer", "Bash", command="cat " + m.IMPL_FILE)),
            ("test run", L("implementer", "Bash", command="python -m pytest -q")),
            ("write unlisted", L(None, "Bash", command="echo x > README.md")),
        )
        for label, row in cases:
            with self.subTest(label):
                res = self.evaluate(ledger=ledger_with(None, [row]))
                self.assertEqual(res["checks"]["PC10"]["verdict"], "pass")

    def test_o3_pc10_bash_edit_before_the_final_verifier_row_passes(self):
        items = m.compliant_ledger_items()
        items = items[:7] + [L("implementer", "Bash", command=IMPL_SED)] + items[7:]
        res = self.evaluate(ledger=items)
        self.assertEqual(res["checks"]["PC10"]["verdict"], "pass")

    def test_o3_main_implementation_edits_counts_main_bash_writes_after_the_spec_write(self):
        bash_impl = L(None, "Bash", command=IMPL_SED)
        edit_impl = L(None, "Edit", file_path=tb(m.IMPL_FILE), old_string="a", new_string="b")
        cases = (
            ("one bash", [bash_impl], 1),
            ("two bash and one edit", [bash_impl, bash_impl, edit_impl], 3),
            ("bash write of a tests path", [L(None, "Bash", command=TEST_SED)], 0),
            ("subagent bash write", [L("implementer", "Bash", command=IMPL_SED)], 0),
            ("bash read", [L(None, "Bash", command="cat " + m.IMPL_FILE)], 0),
        )
        for label, rows, expected in cases:
            with self.subTest(label):
                res = self.evaluate(ledger=ledger_with(1, rows))
                self.assertEqual(res["metrics"]["main_implementation_edits"], expected)

    def test_o3_main_implementation_edits_ignores_bash_writes_before_the_spec_write(self):
        items = [L(None, "Bash", command=IMPL_SED)] + m.compliant_ledger_items()
        res = self.evaluate(ledger=items)
        self.assertEqual(res["metrics"]["main_implementation_edits"], 0)

    def test_o3_main_implementation_edits_counts_after_a_bash_spec_write(self):
        res = self.evaluate(ledger=with_spec_row("Bash", [L(None, "Bash", command=IMPL_SED)], at=1))
        self.assertEqual(res["metrics"]["main_implementation_edits"], 1)


# ----------------------------------------------------------------------------------------------
# O4: PC12 decision table R1-R7 (F9, C13-C16)
# ----------------------------------------------------------------------------------------------

class Pc12Tests(ProcessCase):
    IMPL_WRITE_BASH = L(None, "Bash", command="cat >> %s <<'EOF'\nx = 1\nEOF" % m.IMPL_FILE)

    def pc12(self, res):
        return res["checks"]["PC12"]

    def test_o4_r1_no_spec_text_is_na(self):
        for label, diff in (("no diff", None), ("decoy only", m.decoy_section())):
            with self.subTest(label):
                res = self.evaluate(diff=diff)
                self.assertEqual(self.pc12(res)["verdict"], "n/a")

    def test_o4_r2_spec_text_and_no_writes_passes(self):
        ledger = [L(None, "Write", file_path=tb(m.SPEC_REL), content="spec"),
                  L(None, "Agent", subagent_type="implementer", prompt="i"),
                  L("implementer", "Read", file_path=tb(m.IMPL_FILE)),
                  L(None, "Bash", command="echo x > README.md")]
        self.assertEqual(self.pc12(self.evaluate(ledger=ledger))["verdict"], "pass")
        self.assertEqual(self.pc12(self.evaluate(ledger=[L(None, "Agent", subagent_type="implementer", prompt="i")]))["verdict"],
                         "pass")

    def test_o4_r3_c15_writes_without_any_spec_write_fails_with_the_first_write_row(self):
        ledger = [L(None, "Agent", subagent_type="implementer", prompt="i"),
                  L("implementer", "Edit", file_path=tb(m.IMPL_FILE), old_string="a", new_string="b"),
                  L("implementer", "Edit", file_path=tb(m.IMPL_FILE), old_string="b", new_string="c")]
        res = self.evaluate(ledger=ledger)
        self.assertEqual(self.pc12(res)["verdict"], "fail")
        self.assertEqual(self.evidence(res, "PC12"), {(LEDGER, 2)})

    def test_o4_r4_c13_main_bash_writes_impl_and_tests_before_the_spec_fails_with_that_row(self):
        both = L(None, "Bash", command="sed -i 's/a/b/' %s\ncat >> %s <<'EOF'\nx\nEOF" % (m.IMPL_FILE, m.TEST_FILE))
        ledger = [L(None, "Agent", subagent_type="implementer", prompt="i"),
                  L(None, "Read", file_path=tb(m.IMPL_FILE)),
                  both,
                  L(None, "Agent", subagent_type="test-verifier", prompt="v"),
                  L("implementer", "Edit", file_path=tb(m.IMPL_FILE), old_string="b", new_string="c"),
                  L(None, "Bash", command=SPEC_HEREDOC)]
        res = self.evaluate(ledger=ledger)
        self.assertEqual(self.pc12(res)["verdict"], "fail")
        self.assertEqual(self.evidence(res, "PC12"), {(LEDGER, 3)})

    def test_o4_r4_each_writer_tool_and_role_before_the_spec_fails(self):
        cases = (
            ("main Edit impl", L(None, "Edit", file_path=tb(m.IMPL_FILE), old_string="a", new_string="b")),
            ("main Write tests", L(None, "Write", file_path=tb(m.TEST_FILE), content="x")),
            ("main Bash impl", self.IMPL_WRITE_BASH),
            ("implementer Edit impl", L("implementer", "Edit", file_path=tb(m.IMPL_FILE), old_string="a", new_string="b")),
            ("implementer Bash tests", L("implementer", "Bash", command=TEST_SED)),
        )
        for label, row in cases:
            with self.subTest(label):
                ledger = [L(None, "Agent", subagent_type="implementer", prompt="i"), row,
                          L(None, "Write", file_path=tb(m.SPEC_REL), content="spec")]
                res = self.evaluate(ledger=ledger)
                self.assertEqual(self.pc12(res)["verdict"], "fail")
                self.assertEqual(self.evidence(res, "PC12"), {(LEDGER, 2)})

    def test_o4_r4_evidence_is_only_the_first_offending_row(self):
        edit = L(None, "Edit", file_path=tb(m.IMPL_FILE), old_string="a", new_string="b")
        ledger = [edit, edit, L(None, "Write", file_path=tb(m.SPEC_REL), content="spec"), edit]
        res = self.evaluate(ledger=ledger)
        self.assertEqual(self.evidence(res, "PC12"), {(LEDGER, 1)})

    def test_o4_r5_c14_spec_first_then_implementer_write_passes(self):
        ledger = [L(None, "Write", file_path=tb(m.SPEC_REL), content="spec"),
                  L(None, "Agent", subagent_type="implementer", prompt="i"),
                  L("implementer", "Edit", file_path=tb(m.IMPL_FILE), old_string="a", new_string="b")]
        self.assertEqual(self.pc12(self.evaluate(ledger=ledger))["verdict"], "pass")

    def test_o4_r5_bash_spec_write_first_then_main_writes_passes(self):
        ledger = [L(None, "Bash", command=SPEC_HEREDOC), self.IMPL_WRITE_BASH, L(None, "Bash", command=TEST_SED)]
        self.assertEqual(self.pc12(self.evaluate(ledger=ledger))["verdict"], "pass")

    def test_o4_r5_writes_to_unlisted_paths_before_the_spec_do_not_count(self):
        ledger = [L(None, "Edit", file_path=tb("README.md"), old_string="a", new_string="b"),
                  L(None, "Bash", command="echo x > notes.txt"),
                  L(None, "Write", file_path=tb(m.SPEC_REL), content="spec")]
        self.assertEqual(self.pc12(self.evaluate(ledger=ledger))["verdict"], "pass")

    def test_o4_r5_reads_and_test_runs_before_the_spec_do_not_count(self):
        ledger = [L(None, "Read", file_path=tb(m.IMPL_FILE)),
                  L(None, "Bash", command="cat %s; python -m pytest %s -q" % (m.IMPL_FILE, m.TEST_FILE)),
                  L(None, "Write", file_path=tb(m.SPEC_REL), content="spec")]
        self.assertEqual(self.pc12(self.evaluate(ledger=ledger))["verdict"], "pass")

    def test_o4_r6_only_test_implementer_writes_before_the_spec_passes(self):
        ledger = [L("test-implementer", "Write", file_path=tb(m.TEST_FILE), content="x"),
                  L("test-implementer", "Bash", command=TEST_HEREDOC),
                  L(None, "Write", file_path=tb(m.SPEC_REL), content="spec"),
                  L("implementer", "Edit", file_path=tb(m.IMPL_FILE), old_string="a", new_string="b")]
        self.assertEqual(self.pc12(self.evaluate(ledger=ledger))["verdict"], "pass")

    def test_o4_r7_baseline_arm_is_na(self):
        res = self.evaluate(arm="baseline", manifest={"instance_id": "b1", "arm": "baseline"})
        self.assertEqual(self.pc12(res)["verdict"], "n/a")

    def test_o4_compliant_entry_passes_pc12_and_check_ids_end_at_pc12(self):
        res = self.evaluate()
        self.assertEqual(self.pc12(res)["verdict"], "pass")
        self.assertEqual(tuple(process.CHECK_IDS), tuple("PC%d" % n for n in range(1, 13)))
        self.assertEqual(set(res["checks"]), set(process.CHECK_IDS))


# ----------------------------------------------------------------------------------------------
# O5: PC9 over Bash classification and the two new metrics (F10, C17-C19)
# ----------------------------------------------------------------------------------------------

class Pc9BashTests(ProcessCase):
    TESTS = ["tests/t.py"]
    IMPL = ["src/impl.py"]

    def run_rows(self, *rows):
        ledger = [L(None, "Write", file_path=tb(m.SPEC_REL), content="spec")] + list(rows)
        return self.evaluate(diff=m.archived_diff(tests=self.TESTS, impl=self.IMPL), ledger=ledger)

    def test_o5_c17_implementer_test_run_is_not_cross_role_access_and_is_counted(self):
        res = self.run_rows(L("implementer", "Bash", command="python -m pytest tests/t.py"))
        self.assertEqual(res["checks"]["PC9"]["verdict"], "pass")
        self.assertEqual(res["metrics"]["implementer_test_runs"], 1)
        self.assertEqual(res["metrics"]["unknown_bash_accesses"], 0)

    def test_o5_implementer_test_runs_are_summed_over_rows_and_commands(self):
        res = self.run_rows(L("implementer", "Bash", command="pytest tests/t.py -q"),
                            L("implementer", "Bash", command="python -m unittest; pytest tests/t.py"),
                            L("implementer", "Bash", command="cat src/impl.py"))
        self.assertEqual(res["checks"]["PC9"]["verdict"], "pass")
        self.assertEqual(res["metrics"]["implementer_test_runs"], 3)

    def test_o5_test_runs_by_other_roles_are_not_counted(self):
        res = self.run_rows(L("test-implementer", "Bash", command="pytest tests/t.py"),
                            L("test-verifier", "Bash", command="python -m pytest tests/t.py"),
                            L(None, "Bash", command="pytest tests/t.py"))
        self.assertEqual(res["checks"]["PC9"]["verdict"], "pass")
        self.assertEqual(res["metrics"]["implementer_test_runs"], 0)

    def test_o5_non_bash_implementer_rows_add_no_test_runs(self):
        res = self.run_rows(L("implementer", "Read", file_path=tb("src/impl.py")))
        self.assertEqual(res["metrics"]["implementer_test_runs"], 0)

    def test_o5_c18_implementer_bash_access_to_tests_fails_with_the_row(self):
        cases = (
            ("cat", "cat tests/t.py"),
            ("grep", "grep -n foo tests/t.py"),
            ("sed -i", "sed -i 's/a/b/' tests/t.py"),
            ("redirect", "echo x > tests/t.py"),
            ("tee", "echo x | tee tests/t.py"),
            ("abs testbed path", "cat /testbed/tests/t.py"),
            ("after cd", "cd tests; cat t.py"),
            ("python write", "python3 - <<'EOF'\nopen('tests/t.py','w').write('x')\nEOF"),
            ("python read", "python3 - <<'EOF'\nprint(open('tests/t.py').read())\nEOF"),
        )
        for label, cmd in cases:
            with self.subTest(label):
                res = self.run_rows(L("implementer", "Bash", command=cmd))
                self.assertEqual(res["checks"]["PC9"]["verdict"], "fail")
                self.assertEqual(self.evidence(res, "PC9"), {(LEDGER, 2)})

    def test_o5_c18_test_roles_bash_access_to_implementation_fails_with_the_row(self):
        cases = (
            ("test-implementer sed -n", "test-implementer", "sed -n 1,5p src/impl.py"),
            ("test-implementer write", "test-implementer", "cp x.py src/impl.py"),
            ("test-verifier cat", "test-verifier", "cat src/impl.py"),
            ("test-verifier redirect", "test-verifier", "echo x >> src/impl.py"),
        )
        for label, role, cmd in cases:
            with self.subTest(label):
                res = self.run_rows(L(role, "Bash", command=cmd))
                self.assertEqual(res["checks"]["PC9"]["verdict"], "fail")
                self.assertEqual(self.evidence(res, "PC9"), {(LEDGER, 2)})

    def test_o5_test_roles_running_tests_and_touching_their_own_side_pass(self):
        res = self.run_rows(L("test-implementer", "Bash", command="python -m pytest tests/t.py"),
                            L("test-implementer", "Bash", command="cat tests/t.py"),
                            L("test-verifier", "Bash", command="pytest tests/t.py"),
                            L("implementer", "Bash", command="cat src/impl.py"),
                            L("implementer", "Bash", command="sed -i 's/a/b/' src/impl.py"))
        self.assertEqual(res["checks"]["PC9"]["verdict"], "pass")

    def test_o5_main_agent_bash_access_to_either_side_is_not_pc9(self):
        res = self.run_rows(L(None, "Bash", command="cat tests/t.py src/impl.py"))
        self.assertEqual(res["checks"]["PC9"]["verdict"], "pass")

    def test_o5_c19_mention_only_entry_passes_and_counts_one_unknown(self):
        res = self.run_rows(L("implementer", "Bash", command="./custom_tool tests/t.py"))
        self.assertEqual(res["checks"]["PC9"]["verdict"], "pass")
        self.assertEqual(res["metrics"]["unknown_bash_accesses"], 1)
        self.assertEqual(res["metrics"]["implementer_test_runs"], 0)

    def test_o5_unknown_bash_accesses_counts_rows_of_all_three_roles(self):
        res = self.run_rows(L("implementer", "Bash", command="./tool tests/t.py"),
                            L("test-implementer", "Bash", command="ls src/impl.py"),
                            L("test-verifier", "Bash", command="./tool src/impl.py"),
                            L("implementer", "Bash", command="./tool tests/t.py"))
        self.assertEqual(res["checks"]["PC9"]["verdict"], "pass")
        self.assertEqual(res["metrics"]["unknown_bash_accesses"], 4)

    def test_o5_mentions_of_own_side_or_unlisted_paths_are_not_unknown_accesses(self):
        res = self.run_rows(L("implementer", "Bash", command="ls src/impl.py"),
                            L("implementer", "Bash", command="./tool README.md"),
                            L("test-implementer", "Bash", command="ls tests/t.py"),
                            L(None, "Bash", command="./tool tests/t.py"))
        self.assertEqual(res["metrics"]["unknown_bash_accesses"], 0)

    def test_o5_non_bash_rows_keep_the_path_rule(self):
        res = self.run_rows(L("implementer", "Read", file_path=tb("tests/t.py")))
        self.assertEqual(res["checks"]["PC9"]["verdict"], "fail")
        self.assertEqual(self.evidence(res, "PC9"), {(LEDGER, 2)})
        res = self.run_rows(L("test-verifier", "Grep", path=tb("src/impl.py"), pattern="x"))
        self.assertEqual(res["checks"]["PC9"]["verdict"], "fail")
        self.assertEqual(res["metrics"]["unknown_bash_accesses"], 0)

    def test_o5_malformed_bash_command_does_not_fail_or_raise(self):
        res = self.run_rows(L("implementer", "Bash", command="cat 'tests/t.py"),
                            L("implementer", "Bash", command=5), L("implementer", "Bash"))
        self.assertEqual(res["checks"]["PC9"]["verdict"], "pass")
        self.assertEqual(res["metrics"]["implementer_test_runs"], 0)

    def test_o5_evidence_lists_every_offending_row(self):
        res = self.run_rows(L("implementer", "Bash", command="cat tests/t.py"),
                            L("implementer", "Bash", command="pytest tests/t.py"),
                            L("test-verifier", "Bash", command="cat src/impl.py"))
        self.assertEqual(self.evidence(res, "PC9"), {(LEDGER, 2), (LEDGER, 4)})


class Pc12MissingInputTests(ProcessCase):
    def test_sc1_pc12_is_na_for_missing_telemetry_missing_ledger_and_empty_ledger(self):
        for label, over in (("missing telemetry dir", dict(events=None)), ("missing ledger file", dict(ledger=None)),
                            ("empty ledger", dict(ledger=[]))):
            with self.subTest(label):
                res = self.evaluate(**over)
                self.assertEqual(res["checks"]["PC12"]["verdict"], "n/a")

    def test_sc1_pc12_is_na_without_a_full_diff(self):
        self.assertEqual(self.evaluate(diff=None)["checks"]["PC12"]["verdict"], "n/a")

    def test_a4_only_a_test_verifier_write_before_the_spec_passes(self):
        ledger = [L("test-verifier", "Write", file_path=tb(m.TEST_FILE), content="x"),
                  L("test-verifier", "Bash", command=TEST_HEREDOC),
                  L(None, "Write", file_path=tb(m.SPEC_REL), content="spec")]
        self.assertEqual(self.evaluate(ledger=ledger)["checks"]["PC12"]["verdict"], "pass")


class DollarPathMatchingTests(ProcessCase):
    def verdict(self, cid, tests, command, *, before_spec=False):
        diff = m.archived_diff(tests=tests)
        row = L(None, "Bash", command=command)
        spec = L(None, "Write", file_path=tb(m.SPEC_REL), content="spec")
        ledger = [row, spec] if before_spec else [spec, row]
        return self.evaluate(diff=diff, ledger=ledger)["checks"][cid]["verdict"]

    def test_sc2_dollar_path_does_not_match_a_file_entry(self):
        cmd = "cat > tests/$N.py <<'EOF'\nx\nEOF"
        self.assertEqual(self.verdict("PC8", ["tests/test_a.py"], cmd), "pass")
        self.assertEqual(self.verdict("PC12", ["tests/test_a.py"], cmd, before_spec=True), "pass")

    def test_sc2_dollar_path_matches_a_directory_entry_by_its_prefix(self):
        cmd = "cat > tests/$N.py <<'EOF'\nx\nEOF"
        self.assertEqual(self.verdict("PC8", ["tests/"], cmd), "fail")
        self.assertEqual(self.verdict("PC12", ["tests/"], cmd, before_spec=True), "fail")

    def test_sc2_empty_prefix_matches_no_entry(self):
        cmd = "cat > $F <<'EOF'\nx\nEOF"
        for tests in (["tests/"], ["tests/test_a.py"], ["tests/unit"]):
            with self.subTest(tests=tests):
                self.assertEqual(self.verdict("PC8", tests, cmd), "pass")
                self.assertEqual(self.verdict("PC12", tests, cmd, before_spec=True), "pass")


class NonBashRowTests(ProcessCase):
    def test_f8_a_non_bash_non_edit_row_with_a_command_is_not_a_write(self):
        fake = L(None, "Foo", command="cat > %s" % m.SPEC_REL)
        ledger = [fake, L(None, "Agent", subagent_type="implementer", prompt="i"),
                  L("implementer", "Edit", file_path=tb(m.IMPL_FILE), old_string="a", new_string="b")]
        res = self.evaluate(ledger=ledger)
        self.assertEqual(res["checks"]["PC8"]["verdict"], "n/a")
        self.assertEqual(res["checks"]["PC12"]["verdict"], "fail")
        self.assertEqual(self.evidence(res, "PC12"), {(LEDGER, 3)})


if __name__ == "__main__":
    unittest.main()
