import contextlib
import copy
import io
import re
from pathlib import Path
import unittest

from evaluation.pr_test_quality import gce
from evaluation.pr_test_quality.tests.fakes import TOKEN, FakeRun, TmpCase, set_token_file, sha256, spec_cfg

RESOURCES = ("network", "subnet", "router", "nat", "firewall", "service_account", "secret", "disk", "vm")


def kind_of(argv):
    text = " ".join(argv)
    if "versions" in argv:
        return "secret_version"
    for key, word in (("nat", "nats"), ("subnet", "subnets"), ("router", "routers"),
                      ("firewall", "firewall-rules"), ("service_account", "service-accounts"),
                      ("secret", "secrets"), ("disk", "disks"), ("vm", "instances"), ("network", "networks")):
        if word in argv:
            return key
    return None


class Gcloud:
    """Answers describe/list/access probes from a set of existing resources and records the rest."""

    def __init__(self, present=(), remote_secret=None, fail_on=None):
        self.present = set(present)
        self.remote_secret = remote_secret
        self.fail_on = fail_on
        self.run = FakeRun(self.handle)

    def handle(self, argv, stdin):
        kind = kind_of(argv)
        if self.fail_on and self.fail_on(argv):
            return 1, "", "ERROR: denied: quota exceeded for resource\nlast line of stderr"
        if "access" in argv:
            if self.remote_secret is None:
                return 1, "", "NOT_FOUND"
            return 0, self.remote_secret, ""
        if "describe" in argv:
            return (0, "{}", "") if kind in self.present else (1, "", "NOT_FOUND")
        if "list" in argv:
            return (0, "name\n" if kind in self.present else "", "")
        if "get-iam-policy" in argv:
            return 0, "secretAccessor", ""
        return 0, "", ""

    def creates(self):
        return [a for a in self.run.argvs if any(v in a for v in ("create", "add"))
                and "describe" not in a and "add-iam-policy-binding" not in a]


class Base(TmpCase):
    def setUp(self):
        super().setUp()
        self.cfg_ = self.cfg()
        g = self.cfg_["gce"]
        g.setdefault("region", "us-central1")
        g.setdefault("zone", "us-central1-a")
        g.setdefault("secret", "harness-eval-oauth")
        g.setdefault("data_disk", "harness-eval-data")
        self.token_path = set_token_file(self.cfg_, self.tmp)

    def quiet(self, fn, *a, **kw):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = fn(*a, **kw)
        return rc, out.getvalue() + err.getvalue()


def has_flag(argv, flag, value=None):
    for i, a in enumerate(argv):
        if value is None:
            if a == flag or a.startswith(flag + "="):
                return True
        else:
            if a == "%s=%s" % (flag, value):
                return True
            if a == flag and i + 1 < len(argv) and argv[i + 1] == value:
                return True
    return False


class PlanUp(Base):
    def setUp(self):
        super().setUp()
        self.plan = gce.plan_up(self.cfg_)

    def first(self, kind, verb="create"):
        for i, a in enumerate(self.plan):
            if kind_of(a) == kind and verb in a:
                return i, a
        self.fail("no %s %s in plan" % (kind, verb))

    def test_O24_C39_plan_is_gcloud_argv_lists(self):
        self.assertTrue(self.plan)
        for argv in self.plan:
            self.assertIsInstance(argv, list)
            self.assertEqual(argv[0], "gcloud")
            self.assertTrue(all(isinstance(a, str) for a in argv))

    def test_O24_C39_resources_are_created_in_dependency_order(self):
        order = [self.first(k)[0] for k in ("network", "subnet", "router", "nat", "firewall", "service_account",
                                            "disk", "vm")]
        self.assertEqual(order, sorted(order))
        self.assertLess(self.first("secret")[0], self.first("vm")[0])
        self.assertLess(self.first("secret_version", "add")[0], self.first("vm")[0])
        self.assertLess(self.first("secret")[0], self.first("secret_version", "add")[0])

    def test_O24_QR4_vm_flags_exact(self):
        _, vm = self.first("vm")
        self.assertIn("--no-address", vm)
        self.assertTrue(has_flag(vm, "--machine-type", "n2-standard-16"))
        self.assertIn("debian-12", " ".join(vm))
        self.assertIn(self.cfg_["gce"]["data_disk"], " ".join(vm))

    def vm_for(self, cfg):
        plan = gce.plan_up(cfg)
        vms = [a for a in plan if kind_of(a) == "vm" and "create" in a]
        self.assertEqual(len(vms), 1)
        return vms[0], plan

    def assert_no_spot(self, plan):
        for argv in plan:
            for arg in argv:
                self.assertNotIn("SPOT", arg)
                self.assertNotIn("--instance-termination-action", arg)
                self.assertNotIn("--provisioning-model", arg.replace("--provisioning-model=STANDARD", ""))

    def test_O24_QR4_D31_shipped_config_is_on_demand_and_emits_no_spot_flags(self):
        self.assertFalse(spec_cfg()["gce"].get("spot", False))
        vm, plan = self.vm_for(spec_cfg())
        self.assert_no_spot(plan)

    def test_O24_QR4_D31_spot_false_emits_no_spot_flags(self):
        cfg = copy.deepcopy(self.cfg_)
        cfg["gce"]["spot"] = False
        self.assert_no_spot(self.vm_for(cfg)[1])

    def test_O24_QR4_D31_spot_key_absent_emits_no_spot_flags(self):
        cfg = copy.deepcopy(self.cfg_)
        cfg["gce"].pop("spot", None)
        self.assert_no_spot(self.vm_for(cfg)[1])

    def test_O24_QR4_D31_spot_true_emits_both_flags_on_the_vm_command(self):
        cfg = copy.deepcopy(self.cfg_)
        cfg["gce"]["spot"] = True
        vm, plan = self.vm_for(cfg)
        self.assertIn("--provisioning-model=SPOT", vm)
        self.assertIn("--instance-termination-action=STOP", vm)
        others = [a for a in plan if a is not vm]
        self.assertFalse(any("SPOT" in x for a in others for x in a))

    def test_O24_QR4_firewall_allows_only_iap_range_on_tcp_22(self):
        _, fw = self.first("firewall")
        text = " ".join(fw)
        self.assertIn("35.235.240.0/20", text)
        self.assertIn("tcp:22", text)
        self.assertNotIn("0.0.0.0/0", text)
        self.assertEqual(re.findall(r"tcp:\d+", text), ["tcp:22"])

    def test_O24_disk_is_300gb_pd_balanced(self):
        _, disk = self.first("disk")
        text = " ".join(disk)
        self.assertIn("pd-balanced", text)
        self.assertRegex(text, r"300\s?GB|300GB|=300\b|\s300\b")
        self.assertIn(self.cfg_["gce"]["data_disk"], text)

    def test_O24_project_zone_region_and_secret_name_come_from_cfg(self):
        g = self.cfg_["gce"]
        text = "\n".join(" ".join(a) for a in self.plan)
        self.assertIn(g["project"], text)
        self.assertEqual(g["project"], "harness-eval-d31ee3")
        self.assertIn(g["zone"], text)
        self.assertIn(g["region"], text)
        self.assertIn(g["secret"], text)
        for argv in self.plan:
            self.assertIn(g["project"], " ".join(argv))

    def test_O24_QR10_plan_never_contains_the_token(self):
        self.assertNotIn(TOKEN, "\n".join(" ".join(a) for a in self.plan))

    def test_O24_secret_version_reads_value_from_stdin(self):
        _, add = self.first("secret_version", "add")
        self.assertTrue(any(a in ("--data-file=-", "-") or a.endswith("=-") for a in add), add)


class Up(Base):
    def test_O24_C39_all_absent_creates_everything_with_secret_on_stdin(self):
        g = Gcloud()
        rc, out = self.quiet(gce.up, self.cfg_, run_fn=g.run)
        self.assertEqual(rc, 0)
        kinds = [kind_of(a) for a in g.creates()]
        for needed in ("network", "subnet", "router", "nat", "firewall", "service_account", "secret", "disk", "vm"):
            self.assertIn(needed, kinds)
        seq = [kinds.index(k) for k in ("network", "subnet", "router", "nat", "firewall", "disk", "vm")]
        self.assertEqual(seq, sorted(seq))
        secret_calls = [c for c in g.run.calls if c["input"] is not None and TOKEN in c["input"]]
        self.assertTrue(secret_calls)
        self.assertTrue(any(a == "--data-file=-" or a.endswith("=-") for a in secret_calls[0]["argv"]))
        self.assertNotIn(TOKEN, g.run.all_text())
        self.assertNotIn(TOKEN, out)

    def test_O24_C40_everything_present_and_same_secret_issues_no_create(self):
        g = Gcloud(present=RESOURCES, remote_secret=TOKEN)
        rc, out = self.quiet(gce.up, self.cfg_, run_fn=g.run)
        self.assertEqual(rc, 0)
        self.assertEqual(g.creates(), [])
        self.assertFalse([a for a in g.run.argvs if "create" in a])
        self.assertTrue(g.run.calls)
        self.assertNotIn(TOKEN, g.run.all_text() + out)

    def test_O24_changed_secret_adds_exactly_one_version(self):
        g = Gcloud(present=RESOURCES, remote_secret="an-older-token-value")
        rc, _ = self.quiet(gce.up, self.cfg_, run_fn=g.run)
        self.assertEqual(rc, 0)
        adds = [c for c in g.run.calls if "versions" in c["argv"] and "add" in c["argv"]]
        self.assertEqual(len(adds), 1)
        self.assertIn(TOKEN, adds[0]["input"])
        self.assertEqual([a for a in g.creates() if kind_of(a) != "secret_version"], [])
        self.assertNotIn(TOKEN, g.run.all_text())

    def test_O24_secret_missing_but_other_resources_present_creates_secret_and_version_only(self):
        g = Gcloud(present=[r for r in RESOURCES if r != "secret"], remote_secret=None)
        rc, _ = self.quiet(gce.up, self.cfg_, run_fn=g.run)
        self.assertEqual(rc, 0)
        self.assertEqual(sorted(kind_of(a) for a in g.creates()), ["secret", "secret_version"])

    def test_O24_only_missing_router_is_created(self):
        g = Gcloud(present=[r for r in RESOURCES if r != "router"], remote_secret=TOKEN)
        self.quiet(gce.up, self.cfg_, run_fn=g.run)
        self.assertEqual([kind_of(a) for a in g.creates()], ["router"])

    def test_O24_failure_stops_at_the_failing_step_prints_stderr_and_returns_one(self):
        g = Gcloud(fail_on=lambda a: "routers" in a and "create" in a)
        rc, out = self.quiet(gce.up, self.cfg_, run_fn=g.run)
        self.assertEqual(rc, 1)
        self.assertIn("quota exceeded", out)
        self.assertIn("last line of stderr", out)
        self.assertIn("routers", " ".join(g.run.argvs[-1]))
        kinds = [kind_of(a) for a in g.creates()]
        self.assertIn("network", kinds)
        for later in ("firewall", "disk", "vm", "secret"):
            self.assertNotIn(later, kinds)

    def test_O24_QR10_token_never_appears_in_output_even_on_failure(self):
        g = Gcloud(fail_on=lambda a: "instances" in a and "create" in a)
        _, out = self.quiet(gce.up, self.cfg_, run_fn=g.run)
        self.assertNotIn(TOKEN, out + g.run.all_text())


class Down(Base):
    def test_O24_down_deletes_vm_and_keeps_disk_and_secret(self):
        g = Gcloud(present=RESOURCES)
        rc, _ = self.quiet(gce.down, self.cfg_, run_fn=g.run)
        self.assertEqual(rc, 0)
        deletes = [a for a in g.run.argvs if "delete" in a]
        self.assertEqual([kind_of(a) for a in deletes], ["vm"])

    def test_O24_purge_also_deletes_disk_and_secret(self):
        g = Gcloud(present=RESOURCES)
        rc, _ = self.quiet(gce.down, self.cfg_, run_fn=g.run, purge=True, yes=True)
        self.assertEqual(rc, 0)
        kinds = {kind_of(a) for a in g.run.argvs if "delete" in a}
        self.assertEqual(kinds, {"vm", "disk", "secret"})

    def test_O24_F15_purge_without_yes_returns_two_and_runs_nothing(self):
        g = Gcloud(present=RESOURCES)
        rc, out = self.quiet(gce.down, self.cfg_, run_fn=g.run, purge=True)
        self.assertEqual(rc, 2)
        self.assertEqual(g.run.calls, [])
        self.assertIn("--yes", out)

    def test_O24_yes_without_purge_still_only_deletes_the_vm(self):
        g = Gcloud(present=RESOURCES)
        rc, _ = self.quiet(gce.down, self.cfg_, run_fn=g.run, yes=True)
        self.assertEqual(rc, 0)
        self.assertEqual([kind_of(a) for a in g.run.argvs if "delete" in a], ["vm"])

    def test_O24_down_failure_returns_one(self):
        g = Gcloud(present=RESOURCES, fail_on=lambda a: "instances" in a and "delete" in a)
        rc, out = self.quiet(gce.down, self.cfg_, run_fn=g.run)
        self.assertEqual(rc, 1)
        self.assertIn("quota exceeded", out)


class Remote(Base):
    def test_O24_F15_push_ships_a_tgz_of_exactly_the_tracked_files(self):
        import tarfile
        seen = {}

        def handler(argv, stdin):
            if argv[:1] == ["git"] and "ls-files" in argv:
                sep = "\0" if "-z" in argv else "\n"
                return 0, sep.join(["AGENTS.md", "installer/harness.py"]) + sep, ""
            if "scp" in argv:
                local = [a for a in argv if a.endswith(".tgz") and not a.startswith("harness") and ":" not in a]
                seen["local"] = local
                with tarfile.open(local[0], "r:gz") as tar:
                    seen["names"] = sorted((m.name[2:] if m.name.startswith("./") else m.name) for m in tar.getmembers())
            return 0, "", ""
        run = FakeRun(handler)
        rc, _ = self.quiet(gce.push, self.cfg_, run_fn=run)
        self.assertEqual(rc, 0)
        plain = [n for n in seen["names"] if n != ".git" and not n.startswith(".git/")]
        self.assertEqual(plain, ["AGENTS.md", "installer/harness.py"])
        self.assertIn(".git", seen["names"])
        scp = [a for a in run.argvs if "scp" in a][0]
        self.assertIn("--tunnel-through-iap", scp)
        self.assertIn(":/tmp/evaluation-push.tgz", " ".join(scp))
        ssh = " ".join([a for a in run.argvs if "ssh" in a][0])
        self.assertIn("/data/src", ssh)
        self.assertIn("/tmp/evaluation-push.tgz", ssh)
        self.assertNotIn(TOKEN, run.all_text())

    def test_O24_push_stops_when_scp_fails(self):
        def handler(argv, stdin):
            if argv[:1] == ["git"]:
                return 0, "AGENTS.md\n", ""
            return (255, "", "scp failed") if "scp" in argv else (0, "", "")
        run = FakeRun(handler)
        rc, _ = self.quiet(gce.push, self.cfg_, run_fn=run)
        self.assertEqual(rc, 1)
        self.assertFalse([a for a in run.argvs if "ssh" in a])

    def test_O24_push_failure_returns_one(self):
        def handler(argv, stdin):
            if argv[:1] == ["git"]:
                return 0, "a.py\n", ""
            return 255, "", "ssh: connect failed"
        rc, out = self.quiet(gce.push, self.cfg_, run_fn=FakeRun(handler))
        self.assertEqual(rc, 1)
        self.assertIn("connect failed", out)

    def test_O24_exec_remote_runs_command_over_iap(self):
        run = FakeRun()
        rc = gce.exec_remote(self.cfg_, ["python3", "-m", "evaluation.pr_test_quality", "doctor"], run_fn=run)
        self.assertEqual(rc, 0)
        self.assertEqual(len(run.calls), 1)
        argv = run.argvs[0]
        self.assertEqual(argv[0], "gcloud")
        self.assertIn("ssh", argv)
        self.assertIn("--tunnel-through-iap", argv)
        self.assertIn("python3 -m evaluation.pr_test_quality doctor", " ".join(argv))
        self.assertNotIn("nohup", " ".join(argv))
        self.assertIn(self.cfg_["gce"]["zone"], " ".join(argv))

    def test_O24_exec_remote_detach_uses_nohup_and_log_under_data_logs(self):
        run = FakeRun()
        rc = gce.exec_remote(self.cfg_, ["python3", "-m", "evaluation.pr_test_quality", "pilot"], run_fn=run, detach=True)
        self.assertEqual(rc, 0)
        text = " ".join(run.argvs[-1])
        self.assertIn("nohup", text)
        self.assertRegex(text, r"/data/logs/[^\s]+\.log")
        self.assertIn("python3 -m evaluation.pr_test_quality pilot", text)

    def test_O24_exec_remote_failure_is_nonzero(self):
        rc = gce.exec_remote(self.cfg_, ["false"], run_fn=FakeRun(lambda a, i: (5, "", "remote failed")))
        self.assertNotEqual(rc, 0)

    def test_O24_F15_pull_copies_results_into_results_dir_and_run_dir_into_data_runs(self):
        self.cfg_["results_dir"] = str(self.tmp / "results")
        run = FakeRun()
        rc, _ = self.quiet(gce.pull, self.cfg_, "20261001-abc", run_fn=run)
        self.assertEqual(rc, 0)
        scps = [a for a in run.argvs if "scp" in a]
        self.assertEqual(len(scps), 2)
        results, runs = scps
        self.assertIn("--tunnel-through-iap", results)
        self.assertTrue(any(a.endswith(":/data/results/20261001-abc.*") for a in results), results)
        self.assertEqual(results[-1], str(self.tmp / "results"))
        self.assertIn("--recurse", runs)
        self.assertTrue(any(a.endswith(":/data/evaluation/runs/20261001-abc") for a in runs), runs)
        self.assertEqual(runs[-1], str(Path(self.cfg_["data_dir"]) / "runs"))

    def test_O24_F15_exec_passes_vm_data_and_results_dirs(self):
        run = FakeRun()
        gce.exec_remote(self.cfg_, ["python3", "-m", "evaluation.pr_test_quality", "doctor"], run_fn=run)
        text = " ".join(run.argvs[0])
        self.assertIn("EVALUATION_DATA_DIR=/data/evaluation", text)
        self.assertIn("EVALUATION_RESULTS_DIR=/data/results", text)

    def test_O24_pull_failure_returns_one(self):
        rc, out = self.quiet(gce.pull, self.cfg_, "r1", run_fn=FakeRun(lambda a, i: (1, "", "no such file")))
        self.assertEqual(rc, 1)
        self.assertIn("no such file", out)


if __name__ == "__main__":
    unittest.main()
