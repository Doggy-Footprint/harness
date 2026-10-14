"""VO8 (claude_call with patched subprocess; CLI `review` through selfcheck.__main__.main) plus the CLI side of
FR10/VO7 (`report` loads review.json from the run dir). Spec e4d852bdd61ccf5b v2.

No docker, no network: review.claude_call is patched for the CLI tests and subprocess.run for claude_call.
Pool rows come from the committed selfcheck/fixtures/instances.jsonl (the same pool the CLI loads).
"""
import json
import shutil
import subprocess
import unittest
from unittest import mock

from selfcheck import __main__ as cli
from selfcheck import review
from selfcheck.tests import agent_fakes as F
from selfcheck.tests import m3_fakes as m
from selfcheck.tests import review_fakes as R
from selfcheck.tests import test_cli_m3 as m3

POOL = F.pool_rows()
IDS = list(POOL)[:3]
NOT_IN_POOL = "proj__nopool-9"
SPEC_CFG = {"model": "claude-opus-5-5", "effort": "low", "timeout_s": 900}


def argv_of(call):
    return list(call.args[0]) if call.args else list(call.kwargs["args"])


class ClaudeCallTests(unittest.TestCase):
    def call(self, **run_kw):
        run_kw.setdefault("return_value", subprocess.CompletedProcess(["claude"], 0, stdout="MODEL-OUT", stderr=""))
        with mock.patch.object(subprocess, "run", **run_kw) as run:
            try:
                out = review.claude_call("THE-PROMPT", model="m-x", effort="e-y", timeout_s=77)
            finally:
                self.run = run
        return out

    def test_vo8_argv_stdin_and_timeout(self):
        out = self.call()
        self.assertEqual(out, "MODEL-OUT")
        self.assertIsInstance(out, str)
        self.assertEqual(self.run.call_count, 1)
        call = self.run.call_args
        argv = argv_of(call)
        self.assertEqual(argv[0].rsplit("/", 1)[-1], "claude")
        self.assertIn("-p", argv)
        self.assertEqual(argv[argv.index("--model") + 1], "m-x")
        self.assertEqual(argv[argv.index("--effort") + 1], "e-y")
        self.assertEqual(argv[argv.index("--output-format") + 1], "text")
        self.assertEqual(argv[argv.index("--tools") + 1], "")
        self.assertNotIn("THE-PROMPT", argv)
        self.assertEqual(call.kwargs.get("input"), "THE-PROMPT")
        self.assertEqual(call.kwargs.get("timeout"), 77)
        self.assertIs(call.kwargs.get("text"), True)
        self.assertTrue(call.kwargs.get("capture_output") is True or call.kwargs.get("stdout") == subprocess.PIPE)

    def test_vo8_non_zero_exit_raises_runtime_error(self):
        with self.assertRaises(RuntimeError):
            self.call(return_value=subprocess.CompletedProcess(["claude"], 1, stdout="", stderr="auth failed"))

    def test_vo8_timeout_raises_runtime_error(self):
        with self.assertRaises(RuntimeError):
            self.call(side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=77))


class FakeClaude:
    """Stand-in for review.claude_call. `plan(problem_statement)` -> str | exception; default: valid review."""

    def __init__(self, plan=None):
        self.plan = plan
        self.calls = []

    def __call__(self, prompt, *, model, effort, timeout_s):
        self.calls.append({"prompt": prompt, "model": model, "effort": effort, "timeout_s": timeout_s})
        if self.plan is not None:
            for iid, row in POOL.items():
                if row["problem_statement"] in prompt:
                    out = self.plan(iid)
                    if isinstance(out, BaseException):
                        raise out
                    return out
        return R.model_text(R.D1_CATS)

    def reviewed(self):
        return [iid for iid, row in POOL.items() for c in self.calls if row["problem_statement"] in c["prompt"]]


class ReviewCliCase(m3.CliCase):
    RUN = "runreview000001"

    def setUp(self):
        super().setUp()
        self.fake = FakeClaude()

    def invoke_review(self, argv, fake=None):
        fake = fake or self.fake
        with mock.patch.object(review, "claude_call", fake):
            return self.invoke(argv, no_run=True)

    def review_run(self, ids=IDS, with_baseline=True):
        entries = []
        for iid in ids:
            entries.append({
                "instance_id": iid, "arm": "harness", "status": "completed",
                "manifest": m.manifest(iid, "harness", self.RUN), "state": m.state(),
                "prediction": m.prediction(iid, "harness", self.RUN),
                "extra": {"events": m.compliant_events(), "diff": m.archived_diff(),
                          "raw_files": {R.TRANSCRIPT_DIR + "/" + R.UUID_A + ".jsonl": m.jsonl_text(R.default_rows())}},
            })
        if with_baseline:
            entries.append({"instance_id": ids[0], "arm": "baseline", "status": "completed",
                            "manifest": m.manifest(ids[0], "baseline", self.RUN), "state": m.state(),
                            "prediction": m.prediction(ids[0], "baseline", self.RUN)})
        run_dir = m.write_run(self.runs, self.RUN, entries, params={"harness_ref": "HEAD", "harness_commit": "d" * 40})
        m.write_text(run_dir / "scores.harness.jsonl", "\n".join(json.dumps(m.score(i)) for i in ids) + "\n")
        m.write_text(run_dir / ids[0] / "harness" / "process.json", json.dumps({"marker": "process-before"}))
        return run_dir

    @staticmethod
    def review_of(run_dir, iid):
        path = run_dir / iid / "harness" / "review.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


class ReviewCommandTests(ReviewCliCase):
    def test_vo8_review_ok_reviews_every_entry_and_prints_status_lines(self):
        run_dir = self.review_run()
        before = m.tree(run_dir)
        code, out, err = self.invoke_review(["review", self.RUN])
        self.assertEqual(code, 0, err)
        self.assertEqual(out.splitlines(), ["%s ok" % i for i in IDS])
        self.assertEqual(len(self.fake.calls), 3)
        self.assertEqual(sorted(self.fake.reviewed()), sorted(IDS))
        for iid in IDS:
            got = self.review_of(run_dir, iid)
            self.assertEqual(got["status"], "ok")
            self.assertEqual(got["instance_id"], iid)
        after = m.tree(run_dir)
        self.assertEqual(set(after) - set(before), {"%s/harness/review.json" % i for i in IDS})
        for path, data in before.items():
            self.assertEqual(after[path], data, path)
        self.assertFalse((run_dir / IDS[0] / "baseline" / "review.json").exists())

    def test_vo8_review_passes_the_pool_instance_and_config_values_to_claude_call(self):
        self.review_run(IDS[:1])
        self.invoke_review(["review", self.RUN])
        call = self.fake.calls[0]
        row = POOL[IDS[0]]
        for needle in (row["problem_statement"], row["patch"], row["test_patch"], row["FAIL_TO_PASS"][0]):
            self.assertIn(needle, call["prompt"])
        self.assertIn("The issue is about Literal annotations.", call["prompt"])
        for needle in ("Implementation: src/pkg/mod.py", "status: complete", "Which opt?", "A-opt"):
            self.assertIn(needle, call["prompt"])
        self.assertEqual({k: call[k] for k in ("model", "effort", "timeout_s")}, SPEC_CFG)
        self.assertEqual(cli.CONFIG["review"], SPEC_CFG)

    def test_vo8_review_unknown_run_id_exits_2_and_writes_nothing(self):
        code, out, err = self.invoke_review(["review", "nosuchrun"])
        self.assertEqual(code, 2)
        self.assertEqual(err, "unknown run id: nosuchrun\n")
        self.assertEqual(out, "")
        self.assertEqual(self.fake.calls, [])
        self.assertEqual(m.tree(self.runs), {})

    def test_vo8_qr2_one_error_among_three_still_attempts_all_and_exits_1(self):
        run_dir = self.review_run()
        bad = IDS[1]

        def plan(iid):
            return RuntimeError("claude exited 1") if iid == bad else R.model_text(R.payload())

        code, out, err = self.invoke_review(["review", self.RUN], FakeClaude(plan))
        self.assertEqual(code, 1)
        self.assertEqual(out.splitlines(), ["%s ok" % IDS[0], "%s error" % bad, "%s ok" % IDS[2]])
        self.assertEqual(self.review_of(run_dir, bad)["status"], "error")
        self.assertEqual(self.review_of(run_dir, IDS[2])["status"], "ok")

    def test_vo8_review_first_entry_failing_does_not_stop_later_entries(self):
        run_dir = self.review_run()
        fake = FakeClaude(lambda iid: RuntimeError("down") if iid == IDS[0] else R.model_text(R.payload()))
        code, out, _ = self.invoke_review(["review", self.RUN], fake)
        self.assertEqual(code, 1)
        self.assertEqual(sorted(fake.reviewed()), sorted(IDS))
        self.assertEqual([self.review_of(run_dir, i)["status"] for i in IDS], ["error", "ok", "ok"])

    def test_vo8_instances_filter_reviews_only_the_listed_entries(self):
        run_dir = self.review_run()
        code, out, err = self.invoke_review(["review", self.RUN, "--instances", ",".join(IDS[1:])])
        self.assertEqual(code, 0, err)
        self.assertEqual(out.splitlines(), ["%s ok" % IDS[1], "%s ok" % IDS[2]])
        self.assertEqual(sorted(self.fake.reviewed()), sorted(IDS[1:]))
        self.assertIsNone(self.review_of(run_dir, IDS[0]))

    def test_vo8_entry_without_a_pool_row_is_skipped(self):
        ids = [IDS[0], NOT_IN_POOL]
        run_dir = self.review_run(ids)
        code, out, err = self.invoke_review(["review", self.RUN])
        self.assertEqual(code, 0, err)
        self.assertEqual(out.splitlines(), ["%s ok" % IDS[0]])
        self.assertEqual(len(self.fake.calls), 1)
        self.assertIsNone(self.review_of(run_dir, NOT_IN_POOL))

    def test_vo8_entry_listed_in_run_json_without_an_entry_dir_is_skipped(self):
        run_dir = self.review_run()
        shutil.rmtree(run_dir / IDS[1])
        code, out, err = self.invoke_review(["review", self.RUN])
        self.assertEqual(code, 0, err)
        self.assertEqual(out.splitlines(), ["%s ok" % IDS[0], "%s ok" % IDS[2]])
        self.assertEqual(len(self.fake.calls), 2)
        self.assertFalse((run_dir / IDS[1]).exists())

    def test_vo7_token_in_model_output_exits_1_writes_no_review_and_prints_no_token(self):
        run_dir = self.review_run(IDS[:1])
        leak = R.model_text(R.payload(understanding=R.category("diverged", R.finding("leak " + self.token))))
        code, out, err = self.invoke_review(["review", self.RUN], FakeClaude(lambda iid: leak))
        self.assertEqual(code, 1)
        self.assertEqual(out.splitlines(), ["%s error" % IDS[0]])
        self.assertIsNone(self.review_of(run_dir, IDS[0]))
        for text in (out, err):
            self.assertNotIn(self.token, text)
        for path, data in m.tree(run_dir).items():
            self.assertNotIn(self.token.encode(), data, path)


class CliTokenTests(ReviewCliCase):
    def test_vo7_token_in_garbage_or_exception_message_reaches_no_file_or_stream(self):
        for label, response in (("garbage", "oops " + self.token),
                                ("exception", RuntimeError("claude failed " + self.token))):
            with self.subTest(label):
                shutil.rmtree(self.runs / self.RUN, True)
                run_dir = self.review_run(IDS[:1])
                code, out, err = self.invoke_review(["review", self.RUN], FakeClaude(lambda iid: response))
                self.assertEqual(code, 1)
                for text in (out, err):
                    self.assertNotIn(self.token, text)
                for path, data in m.tree(run_dir).items():
                    self.assertNotIn(self.token.encode(), data, path)


class ReportReadsReviewsTests(ReviewCliCase):
    IDS2 = ("proj__a-1", "proj__b-2")

    def okfile(self, iid, cats):
        return json.dumps({"status": "ok", "instance_id": iid, "model": R.MODEL, "effort": R.EFFORT,
                           "categories": cats, "false_claims": [
                               {"category": "understanding", "summary": "WRONG-FACT", "citation": "[t:1]"}]})

    def test_fr10_report_emits_reviews_loaded_from_the_run_dir(self):
        run_dir = self.harness_run()
        cats = R.payload(understanding=R.category("diverged", R.finding("WRONG-FACT", "[t:1]", True)))
        m.write_text(run_dir / "proj__a-1" / "harness" / "review.json", self.okfile("proj__a-1", cats))
        m.write_text(run_dir / "proj__b-2" / "harness" / "review.json", "{ broken")
        code, out, err = self.invoke(["report", run_dir.name, "--no-baseline"], no_run=True)
        self.assertEqual(code, 0, err)
        rep = self.load(self.results / (run_dir.name + ".json"))
        first, second = rep["instances"]
        self.assertEqual(first["review"]["understanding"], "diverged")
        self.assertEqual(second["review"], "error: unreadable review.json")
        self.assertEqual(rep["false_claims"], [{"instance_id": "proj__a-1", "category": "understanding",
                                                "summary": "WRONG-FACT", "citation": "[t:1]"}])
        text = (self.results / (run_dir.name + ".md")).read_text(encoding="utf-8")
        self.assertIn("## false claims", text)
        self.assertIn("WRONG-FACT", text)

    def test_fr10_report_without_review_files_says_not_run_and_none(self):
        run_dir = self.harness_run()
        code, _, err = self.invoke(["report", run_dir.name, "--no-baseline"], no_run=True)
        self.assertEqual(code, 0, err)
        rep = self.load(self.results / (run_dir.name + ".json"))
        self.assertEqual([i["review"] for i in rep["instances"]], ["not run", "not run"])
        self.assertEqual(rep["false_claims"], [])

    def test_vo7_report_with_the_token_in_a_review_file_exits_1_and_writes_nothing(self):
        run_dir = self.harness_run()
        cats = R.payload(understanding=R.category("diverged", R.finding("WRONG-FACT", "[t] " + self.token, True)))
        m.write_text(run_dir / "proj__a-1" / "harness" / "review.json", json.dumps({
            "status": "ok", "instance_id": "proj__a-1", "model": R.MODEL, "effort": R.EFFORT, "categories": cats,
            "false_claims": [{"category": "understanding", "summary": "WRONG-FACT", "citation": "[t] " + self.token}]}))
        code, out, err = self.invoke(["report", run_dir.name, "--no-baseline"], no_run=True)
        self.assertEqual(code, 1)
        self.assertTrue(err.strip())
        self.assertFalse(self.results.exists() and self.files_under(self.results))
        for text in (out, err):
            self.assertNotIn(self.token, text)


class ReviewSurfaceTests(unittest.TestCase):
    def test_vo8_review_subcommand_is_registered(self):
        self.assertIn("review", cli.SUBCOMMANDS)


if __name__ == "__main__":
    unittest.main()
