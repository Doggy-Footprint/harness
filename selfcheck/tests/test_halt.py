"""VO1: batch halting in run.run / run.resume and the cmd_run exit codes (decision table D1-D9).

Expected values are the spec's rules applied by hand: halt on `interrupted`, or on a rate_limit status
that is neither `allowed` nor None; entries never started stay `pending`.
"""
import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from selfcheck import __main__ as cli
from selfcheck import run as run_mod
from selfcheck.tests import agent_fakes as F

IDS = list(F.pool_rows())[:4]
PLANTED_DIFF, _ = F.planted()


def limit(status):
    return {"status": status, "resets_at": 1791843000, "rate_limit_type": "five_hour"}


INTERRUPTED = dict(
    status="interrupted", reason="rate_limit_event", session_id="sess-A", phrases_sent=2,
    tool_calls_since_phrase=1, elapsed_s=33.5, rate_limit=limit("rejected"),
)


def returning(**over):
    return F.returning(F.driver_state_dict(**over))


class HaltReasonTests(unittest.TestCase):
    def test_vo1_d1_to_d5_halt_reason_table(self):
        cases = (
            ("D5 no state", None, None),
            ("D5 empty state", {}, None),
            ("D5 rate_limit None", {"status": "completed", "rate_limit": None}, None),
            ("D4 allowed", {"status": "completed", "rate_limit": limit("allowed")}, None),
            ("D1 interrupted", {"status": "interrupted"}, "interrupted"),
            ("D1 interrupted wins over allowed", {"status": "interrupted", "rate_limit": limit("allowed")}, "interrupted"),
            ("D1 interrupted wins over rejected", {"status": "interrupted", "rate_limit": limit("rejected")}, "interrupted"),
            ("D2 rejected with completed", {"status": "completed", "rate_limit": limit("rejected")}, "rate_limit:rejected"),
            ("D3 allowed_warning", {"status": "completed", "rate_limit": limit("allowed_warning")}, "rate_limit:allowed_warning"),
            ("D2 rejected with capped", {"status": "capped", "rate_limit": limit("rejected")}, "rate_limit:rejected"),
            ("D2 rejected with stalled", {"status": "stalled", "rate_limit": limit("rejected")}, "rate_limit:rejected"),
            ("D2 rejected with error", {"status": "error", "rate_limit": limit("rejected")}, "rate_limit:rejected"),
            ("D5 status None", {"status": "completed", "rate_limit": {"status": None}}, None),
            ("D5 no status key", {"status": "completed", "rate_limit": {"resets_at": 1}}, None),
            ("D5 rate_limit not a dict", {"status": "completed", "rate_limit": "rejected"}, None),
            ("D5 error without rate_limit", {"status": "error"}, None),
        )
        for label, state, expected in cases:
            with self.subTest(label):
                self.assertEqual(run_mod.halt_reason(state), expected)


class HaltRunTests(F.RunCase):
    def setUp(self):
        super().setUp()
        self.docker.configure(diff_text=PLANTED_DIFF)

    def batch(self, count=3, **kw):
        return self.go(ids=tuple(IDS[:count]), arms=("baseline",), **kw)

    def listing(self, run_dir):
        return self.load(run_dir / "run.json")

    def statuses(self, run_dir):
        return [e["status"] for e in self.listing(run_dir)["entries"]]

    def started_names(self):
        return [e[1] for e in self.docker.started()]

    def assert_halted(self, run_dir, reason, position):
        self.assertEqual(self.listing(run_dir)["halted"],
                         {"reason": reason, "instance_id": IDS[position - 1], "arm": "baseline"})

    def test_vo1_d3_c1_allowed_warning_on_the_second_entry_stops_before_the_third(self):
        self.docker.configure(n=2, driver=returning(rate_limit=limit("allowed_warning")))
        run_dir = self.batch()
        self.assertEqual(self.started_names(), [self.name(run_dir, 1), self.name(run_dir, 2)])
        self.assertEqual(self.statuses(run_dir), ["completed", "completed", "pending"])
        self.assert_halted(run_dir, "rate_limit:allowed_warning", 2)
        self.assertEqual(set(self.listing(run_dir)["halted"]), {"reason", "instance_id", "arm"})
        self.assertFalse((self.entry(run_dir, IDS[2], "baseline") / "state.json").exists())
        predictions = (run_dir / "predictions.baseline.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual([json.loads(l)["instance_id"] for l in predictions], IDS[:2])

    def test_vo1_d2_rejected_rate_limit_with_a_completed_status_halts(self):
        self.docker.configure(n=2, driver=returning(rate_limit=limit("rejected")))
        run_dir = self.batch()
        self.assertEqual(len(self.docker.started()), 2)
        self.assertEqual(self.statuses(run_dir), ["completed", "completed", "pending"])
        self.assert_halted(run_dir, "rate_limit:rejected", 2)

    def test_vo1_d1_c2_interrupted_second_entry_halts_and_keeps_its_container(self):
        self.docker.configure(n=2, driver=returning(**INTERRUPTED))
        run_dir = self.batch()
        self.assertEqual(self.started_names(), [self.name(run_dir, 1), self.name(run_dir, 2)])
        self.assertEqual(self.statuses(run_dir), ["completed", "interrupted", "pending"])
        self.assert_halted(run_dir, "interrupted", 2)
        self.assertIn(self.name(run_dir, 2), self.docker.containers)

    def test_vo1_d1_interrupted_first_entry_leaves_the_other_two_pending(self):
        self.docker.configure(n=1, driver=returning(**INTERRUPTED))
        run_dir = self.batch()
        self.assertEqual(len(self.docker.started()), 1)
        self.assertEqual(self.statuses(run_dir), ["interrupted", "pending", "pending"])
        self.assert_halted(run_dir, "interrupted", 1)

    def test_vo1_d4_allowed_on_every_entry_runs_the_whole_batch(self):
        self.docker.configure(driver=returning(rate_limit=limit("allowed")))
        run_dir = self.batch()
        self.assertEqual(len(self.docker.started()), 3)
        self.assertEqual(self.statuses(run_dir), ["completed"] * 3)
        listing = self.listing(run_dir)
        self.assertIn("halted", listing)
        self.assertIsNone(listing["halted"])

    def test_vo1_d5_no_rate_limit_runs_the_whole_batch(self):
        run_dir = self.batch()
        self.assertEqual(len(self.docker.started()), 3)
        self.assertEqual(self.statuses(run_dir), ["completed"] * 3)
        self.assertIn("halted", self.listing(run_dir))
        self.assertIsNone(self.listing(run_dir)["halted"])

    def test_vo1_d6_c5_halt_at_the_last_entry_is_recorded(self):
        self.docker.configure(n=3, driver=returning(rate_limit=limit("allowed_warning")))
        run_dir = self.batch()
        self.assertEqual(len(self.docker.started()), 3)
        self.assertEqual(self.statuses(run_dir), ["completed"] * 3)
        self.assert_halted(run_dir, "rate_limit:allowed_warning", 3)

    def test_vo1_d7_c3_resume_of_a_rate_limit_halt_runs_the_pending_entry_and_clears_halted(self):
        self.docker.configure(n=2, driver=returning(rate_limit=limit("allowed_warning")))
        run_dir = self.batch()
        done = {str(p): p.read_bytes() for p in self.entry(run_dir, IDS[1], "baseline").rglob("*") if p.is_file()}
        mark = len(self.docker.log)
        self.assertEqual(self.resume(run_dir.name), run_dir)
        touched = {e[1] for e in self.docker.log[mark:] if e[0] in ("start_container", "exec", "start", "stop")}
        self.assertEqual(touched, {self.name(run_dir, 3)})
        self.assertEqual(self.statuses(run_dir), ["completed"] * 3)
        self.assertIsNone(self.listing(run_dir)["halted"])
        again = {str(p): p.read_bytes() for p in self.entry(run_dir, IDS[1], "baseline").rglob("*") if p.is_file()}
        self.assertEqual(again, done)

    def test_vo1_d7_resume_of_an_interrupted_halt_continues_the_entry_then_the_pending_ones(self):
        self.docker.configure(n=2, driver=returning(**INTERRUPTED))
        run_dir = self.batch()
        self.docker.history[self.name(run_dir, 2)].script.driver = returning()
        self.resume(run_dir.name)
        self.assertEqual(self.statuses(run_dir), ["completed"] * 3)
        self.assertIsNone(self.listing(run_dir)["halted"])
        self.assertEqual(self.docker.history[self.name(run_dir, 2)].driver_inputs[1]["resume"],
                         {"session_id": "sess-A", "phrases_sent": 2, "elapsed_s": 33.5})
        self.assertEqual(len(self.docker.history[self.name(run_dir, 3)].driver_inputs), 1)

    def test_vo1_d8_resume_halts_again_without_starting_later_entries(self):
        snapshots = []
        runs = self.runs_dir

        def interrupted_and_peek(container, inp):
            listing = json.loads((next(runs.iterdir()) / "run.json").read_text(encoding="utf-8"))
            snapshots.append(listing["halted"])
            return F.DriverResult(0, F.driver_files(F.driver_state_dict(**INTERRUPTED)), False)

        self.docker.configure(n=2, driver=returning(rate_limit=limit("allowed_warning")))
        self.docker.configure(n=3, driver=interrupted_and_peek)
        run_dir = self.batch(count=4)
        self.assertEqual(self.statuses(run_dir), ["completed", "completed", "pending", "pending"])
        self.assert_halted(run_dir, "rate_limit:allowed_warning", 2)
        self.resume(run_dir.name)
        self.assertEqual(snapshots, [None], "resume must clear halted before its first entry")
        self.assertEqual(self.started_names(), [self.name(run_dir, n) for n in (1, 2, 3)])
        self.assertEqual(self.statuses(run_dir), ["completed", "completed", "interrupted", "pending"])
        self.assert_halted(run_dir, "interrupted", 3)


class RepeatHaltTests(F.RunCase):
    def setUp(self):
        super().setUp()
        self.docker.configure(diff_text=PLANTED_DIFF)

    def repeated(self, **kw):
        return self.go(ids=tuple(IDS[:2]), arms=("baseline",), repeats=2, **kw)

    def listing(self, run_dir):
        return self.load(run_dir / "run.json")

    def entries(self, run_dir):
        return [(e["instance_id"], e["repeat"], e["status"]) for e in self.listing(run_dir)["entries"]]

    def files(self, run_dir, iid, k):
        return {str(p): p.read_bytes() for p in (run_dir / iid / ("baseline-r%d" % k)).rglob("*") if p.is_file()}

    def test_o6_c22_interrupted_repeat_entry_records_the_repeat_in_halted(self):
        self.docker.configure(n=2, driver=returning(**INTERRUPTED))
        run_dir = self.repeated()
        self.assertEqual(self.entries(run_dir), [(IDS[0], 1, "completed"), (IDS[0], 2, "interrupted"),
                                                 (IDS[1], 1, "pending"), (IDS[1], 2, "pending")])
        self.assertEqual(self.listing(run_dir)["halted"],
                         {"reason": "interrupted", "instance_id": IDS[0], "arm": "baseline", "repeat": 2})
        self.assertEqual(len(self.docker.started()), 2)

    def test_o6_c22_rate_limit_halt_records_the_repeat(self):
        self.docker.configure(n=1, driver=returning(rate_limit=limit("allowed_warning")))
        run_dir = self.repeated()
        self.assertEqual(self.listing(run_dir)["halted"], {
            "reason": "rate_limit:allowed_warning", "instance_id": IDS[0], "arm": "baseline", "repeat": 1})
        self.assertEqual([s for _, _, s in self.entries(run_dir)], ["completed", "pending", "pending", "pending"])

    def test_o6_c22_halt_without_repeats_has_no_repeat_key(self):
        self.docker.configure(n=1, driver=returning(rate_limit=limit("allowed_warning")))
        run_dir = self.go(ids=tuple(IDS[:2]), arms=("baseline",))
        self.assertEqual(set(self.listing(run_dir)["halted"]), {"reason", "instance_id", "arm"})

    def test_o6_c22_resume_of_the_last_interrupted_repeat_touches_only_that_entry(self):
        self.docker.configure(n=4, driver=returning(**INTERRUPTED))
        run_dir = self.repeated()
        self.assertEqual(self.listing(run_dir)["halted"]["repeat"], 2)
        before = {(i, k): self.files(run_dir, i, k) for i, k in ((IDS[0], 1), (IDS[0], 2), (IDS[1], 1))}
        self.docker.history[self.name(run_dir, 4)].script.driver = returning()
        mark = len(self.docker.log)
        self.assertEqual(self.resume(run_dir.name), run_dir)
        touched = {e[1] for e in self.docker.log[mark:] if e[0] in ("start_container", "exec", "start", "stop")}
        self.assertEqual(touched, {self.name(run_dir, 4)})
        self.assertEqual({(i, k): self.files(run_dir, i, k) for i, k in before}, before)
        self.assertEqual(self.entries(run_dir), [(IDS[0], 1, "completed"), (IDS[0], 2, "completed"),
                                                 (IDS[1], 1, "completed"), (IDS[1], 2, "completed")])
        self.assertIsNone(self.listing(run_dir)["halted"])
        self.assertTrue((run_dir / IDS[1] / "baseline-r2" / "prediction.json").is_file())
        self.assertFalse((run_dir / IDS[1] / "baseline").exists())
        self.assertEqual(self.docker.history[self.name(run_dir, 4)].driver_inputs[1]["resume"],
                         {"session_id": "sess-A", "phrases_sent": 2, "elapsed_s": 33.5})

    def test_o6_c22_resume_continues_the_interrupted_repeat_then_pending_repeats_in_their_dirs(self):
        self.docker.configure(n=2, driver=returning(**INTERRUPTED))
        run_dir = self.repeated()
        first = self.files(run_dir, IDS[0], 1)
        self.docker.history[self.name(run_dir, 2)].script.driver = returning()
        self.resume(run_dir.name)
        self.assertEqual(self.entries(run_dir), [(IDS[0], 1, "completed"), (IDS[0], 2, "completed"),
                                                 (IDS[1], 1, "completed"), (IDS[1], 2, "completed")])
        self.assertEqual(self.files(run_dir, IDS[0], 1), first)
        for iid in IDS[:2]:
            for k in (1, 2):
                self.assertTrue((run_dir / iid / ("baseline-r%d" % k) / "prediction.json").is_file(), (iid, k))
        self.assertEqual(len(self.docker.history[self.name(run_dir, 3)].driver_inputs), 1)
        self.assertIsNone(self.listing(run_dir)["halted"])
        lines = (run_dir / "predictions.baseline.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(sorted((json.loads(l)["instance_id"], json.loads(l)["repeat"]) for l in lines),
                         sorted([(IDS[0], 1), (IDS[0], 2), (IDS[1], 1), (IDS[1], 2)]))

    def test_o6_c22_resume_halting_again_records_the_new_repeat(self):
        self.docker.configure(n=1, driver=returning(rate_limit=limit("allowed_warning")))
        self.docker.configure(n=2, driver=returning(**INTERRUPTED))
        run_dir = self.repeated()
        self.assertEqual(self.listing(run_dir)["halted"]["repeat"], 1)
        self.resume(run_dir.name)
        self.assertEqual(self.listing(run_dir)["halted"],
                         {"reason": "interrupted", "instance_id": IDS[0], "arm": "baseline", "repeat": 2})


class HaltExitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="halt-cli-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def run_dir(self, statuses, halted):
        directory = Path(self.tmp) / ("run%d" % len(list(Path(self.tmp).iterdir())))
        directory.mkdir()
        entries = [{"instance_id": "i%d" % n, "arm": "baseline", "status": s} for n, s in enumerate(statuses)]
        (directory / "run.json").write_text(json.dumps({
            "run_id": directory.name, "entries": entries, "created_at": 0, "halted": halted,
        }), encoding="utf-8")
        return directory

    def invoke(self, argv, attr, directory):
        out, err = io.StringIO(), io.StringIO()
        fake = mock.Mock(return_value=directory)
        with mock.patch.object(run_mod, attr, fake), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = cli.main(argv)
            except SystemExit as exit_:
                code = exit_.code
        return code, out.getvalue(), err.getvalue()

    def halted(self, reason="rate_limit:allowed_warning", iid="i1"):
        return {"reason": reason, "instance_id": iid, "arm": "baseline"}

    def test_vo1_d9_exit_code_table_for_run_and_resume(self):
        cases = (
            ("halted only", ["completed", "completed", "pending"], self.halted(), 3),
            ("D9 halted and error", ["error", "completed", "pending"], self.halted(), 3),
            ("error only", ["completed", "error"], None, 1),
            ("clean", ["completed", "completed"], None, 0),
            ("interrupted without halted record", ["completed", "interrupted"], None, 0),
        )
        for label, statuses, halted, expected in cases:
            for argv, attr in ((["run"], "run"), (["run", "--resume", "abc"], "resume")):
                with self.subTest(label=label, command=attr):
                    directory = self.run_dir(statuses, halted)
                    code, _, _ = self.invoke(argv, attr, directory)
                    self.assertEqual(code, expected)

    def test_vo1_c1_halt_message_goes_to_stderr_with_the_resume_command(self):
        directory = self.run_dir(["completed", "completed", "pending"], self.halted("rate_limit:allowed_warning", "i1"))
        code, out, err = self.invoke(["run"], "run", directory)
        self.assertEqual(code, 3)
        expected = ("halted: rate_limit:allowed_warning at i1/baseline; resume with: "
                    "python3 -m selfcheck run --resume %s" % directory.name)
        self.assertIn(expected, err.splitlines())
        self.assertIn(str(directory), (out + err).splitlines())

    def test_vo1_c2_interrupted_halt_message(self):
        directory = self.run_dir(["interrupted", "pending"], self.halted("interrupted", "i0"))
        code, _, err = self.invoke(["run", "--resume", directory.name], "resume", directory)
        self.assertEqual(code, 3)
        self.assertIn("halted: interrupted at i0/baseline; resume with: python3 -m selfcheck run --resume %s"
                      % directory.name, err.splitlines())

    def test_vo1_d4_no_halt_message_when_halted_is_null(self):
        directory = self.run_dir(["completed"], None)
        code, _, err = self.invoke(["run"], "run", directory)
        self.assertEqual(code, 0)
        self.assertNotIn("halted:", err)


if __name__ == "__main__":
    unittest.main()
