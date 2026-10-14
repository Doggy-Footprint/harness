import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from selfcheck import docker_exec, run
from selfcheck.tests import agent_fakes as F
from selfcheck.tests.agent_fakes import ROW_A, ROW_B

PLANTED_DIFF, _ = F.planted()
DERIVED_RE = r"selfcheck-agent\.arm64\.%s:[0-9a-f]{12}"
IMAGE_MISSING_RE = r"^image missing: (%s); run python -m selfcheck images --agent$"
INTERRUPTED = dict(
    status="interrupted", reason="rate_limit_event", session_id="sess-A", phrases_sent=2,
    tool_calls_since_phrase=1, elapsed_s=33.5,
    rate_limit={"status": "rejected", "resets_at": 1791843000, "rate_limit_type": "five_hour"},
)
INSTALL_PLACEHOLDER = F.PLACEHOLDERS[0]


def git_out(*args):
    return subprocess.run(["git", *args], cwd=F.ROOT, capture_output=True, check=True).stdout


def files_containing(root, needle):
    hits = []
    for path in Path(root).rglob("*"):
        if path.is_file() and needle in path.read_bytes():
            hits.append(path)
    return hits


class _ReorderedScan:
    def __init__(self, entries):
        self._entries = iter(entries)

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._entries)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def close(self):
        pass


@contextlib.contextmanager
def listing_order(links_first):
    """Control the directory listing order (an external boundary): symlinks before or after regular entries."""
    real_walk, real_scandir, real_listdir = os.walk, os.scandir, os.listdir

    def rank(is_link):
        return (0 if is_link else 1) if links_first else (1 if is_link else 0)

    def walk(top, *args, **kwargs):
        for dirpath, dirs, files in real_walk(top, *args, **kwargs):
            dirs.sort(key=lambda n: rank(os.path.islink(os.path.join(dirpath, n))))
            files.sort(key=lambda n: rank(os.path.islink(os.path.join(dirpath, n))))
            yield dirpath, dirs, files

    def scandir(path="."):
        with real_scandir(path) as handle:
            entries = sorted(handle, key=lambda e: rank(e.is_symlink()))
        return _ReorderedScan(entries)

    def listdir(path="."):
        return sorted(real_listdir(path), key=lambda n: rank(os.path.islink(os.path.join(str(path), n))))

    with mock.patch.object(os, "walk", walk), mock.patch.object(os, "scandir", scandir), \
            mock.patch.object(os, "listdir", listdir):
        yield


class ComposePromptTests(unittest.TestCase):
    ROW = {
        "instance_id": "x__y-1", "repo": "x/y",
        "problem_statement": "  \n\tBody text\n\n  Indented line\n\n  ",
        "hints_text": "UNIQUE-HINT-TEXT", "patch": "UNIQUE-GOLD-PATCH", "test_patch": "UNIQUE-TEST-PATCH",
        "FAIL_TO_PASS": ["UNIQUE-F2P"], "PASS_TO_PASS": ["UNIQUE-P2P"], "base_commit": "UNIQUE-BASE",
        "version": "UNIQUE-VERSION", "difficulty": "UNIQUE-DIFFICULTY",
    }
    BODY = "Body text\n\n  Indented line"
    SUFFIX = "\n\nResolve the issue above in the repository at /testbed. Add or modify automated tests that verify the fix.\n"

    def test_vo5_p1_baseline_text_is_exact(self):
        self.assertEqual(run.compose_prompt(self.ROW, "baseline"), self.BODY + self.SUFFIX)

    def test_vo5_p2_harness_arm_prefixes_workflow_approach(self):
        self.assertEqual(run.compose_prompt(self.ROW, "harness"), "/workflow-approach " + self.BODY + self.SUFFIX)

    def test_vo5_p3_hints_and_other_fields_are_never_included(self):
        for arm in ("baseline", "harness"):
            text = run.compose_prompt(self.ROW, arm)
            for marker in ("UNIQUE-HINT-TEXT", "UNIQUE-GOLD-PATCH", "UNIQUE-TEST-PATCH", "UNIQUE-F2P", "UNIQUE-P2P",
                           "UNIQUE-BASE", "UNIQUE-VERSION", "UNIQUE-DIFFICULTY"):
                with self.subTest(arm=arm, marker=marker):
                    self.assertNotIn(marker, text)

    def test_vo5_p4_surrounding_whitespace_is_stripped_and_inner_whitespace_kept(self):
        for statement in ("\n\n  Plain  \n\n", "\tTabbed\r\n", "Plain"):
            with self.subTest(statement=statement):
                row = dict(self.ROW, problem_statement=statement)
                self.assertEqual(run.compose_prompt(row, "baseline"), statement.strip() + self.SUFFIX)
        self.assertEqual(run.compose_prompt(self.ROW, "baseline").split("\n\nResolve")[0], self.BODY)


class ScrubTests(unittest.TestCase):
    TOKEN = "tok-scrub-0123456789abcdef"

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="scrub-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = Path(self.tmp)

    def scrub(self):
        return run.scrub(str(self.root), self.TOKEN)

    def put(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def test_vo10_k1_text_file(self):
        path = self.put("a.txt", ("before %s after\n" % self.TOKEN).encode())
        self.assertEqual(self.scrub(), 1)
        self.assertEqual(path.read_bytes(), b"before [REDACTED] after\n")

    def test_vo10_k2_binary_file(self):
        original = b"\x00\xff\xfe" + self.TOKEN.encode() + b"\x80\x81\x00"
        path = self.put("blob.bin", original)
        self.assertEqual(self.scrub(), 1)
        self.assertEqual(path.read_bytes(), b"\x00\xff\xfe[REDACTED]\x80\x81\x00")

    def test_vo10_k3_nested_directories(self):
        deep = self.put("a/b/c/deep.jsonl", ('{"k":"%s"}\n' % self.TOKEN).encode())
        top = self.put("top.txt", self.TOKEN.encode())
        other = self.put("a/other.txt", b"clean\n")
        self.assertEqual(self.scrub(), 2)
        self.assertEqual(deep.read_bytes(), b'{"k":"[REDACTED]"}\n')
        self.assertEqual(top.read_bytes(), b"[REDACTED]")
        self.assertEqual(other.read_bytes(), b"clean\n")

    def test_vo10_k4_multiple_occurrences_in_one_file_are_all_replaced_and_counted(self):
        tok = self.TOKEN
        path = self.put("m.txt", ("%s,%s\n%s%s tail %s" % (tok, tok, tok, tok, tok)).encode())
        self.assertEqual(self.scrub(), 5)
        self.assertEqual(path.read_bytes(), b"[REDACTED],[REDACTED]\n[REDACTED][REDACTED] tail [REDACTED]")

    def test_vo10_k4_counts_add_up_across_files(self):
        self.put("one.txt", (self.TOKEN * 2).encode())
        self.put("d/two.txt", (" %s " % self.TOKEN).encode())
        self.assertEqual(self.scrub(), 3)

    def test_vo10_k5_absent_token_returns_zero_and_leaves_every_byte_alone(self):
        contents = {"a.txt": b"nothing here\n", "b/c.bin": b"\x00\x01\xff", "partial.txt": self.TOKEN[:-1].encode()}
        for name, data in contents.items():
            self.put(name, data)
        self.assertEqual(self.scrub(), 0)
        for name, data in contents.items():
            with self.subTest(name):
                self.assertEqual((self.root / name).read_bytes(), data)

    def test_vo10_k6_symlinks_are_skipped_without_stopping_the_walk(self):
        outside = Path(tempfile.mkdtemp(prefix="scrub-outside-"))
        self.addCleanup(shutil.rmtree, outside, True)
        target_text = ("outside holds %s\n" % self.TOKEN).encode()
        target = outside / "target.txt"
        target.write_bytes(target_text)
        (outside / "dir").mkdir()
        (outside / "dir" / "inner.txt").write_bytes(target_text)
        for order in ("symlinks first", "symlinks last"):
            with self.subTest(order):
                root = Path(self.tmp) / ("k6-" + order.replace(" ", "-"))
                (root / "d").mkdir(parents=True)
                links = {"d/0-file-link": target, "d/1-dangling": outside / "absent", "d/a-dir-link": outside / "dir",
                         "d/zz-file-link": target, "d/zz-dangling": outside / "absent"}
                for name, destination in links.items():
                    os.symlink(destination, root / name)
                regular = root / "d" / "m-file.txt"
                regular.write_bytes(("inside %s\n" % self.TOKEN).encode())
                later = root / "d" / "zz-regular.txt"
                later.write_bytes(("%s and %s" % (self.TOKEN, self.TOKEN)).encode())
                with listing_order(links_first=order == "symlinks first"):
                    count = run.scrub(str(root), self.TOKEN)
                self.assertEqual(count, 3)
                self.assertEqual(regular.read_bytes(), b"inside [REDACTED]\n")
                self.assertEqual(later.read_bytes(), b"[REDACTED] and [REDACTED]")
                self.assertEqual(target.read_bytes(), target_text)
                self.assertEqual((outside / "dir" / "inner.txt").read_bytes(), target_text)
                for name, destination in links.items():
                    self.assertTrue(os.path.islink(root / name), name)
                    self.assertEqual(os.readlink(root / name), str(destination), name)

    def test_vo10_k7_an_empty_token_returns_zero_and_changes_nothing(self):
        contents = {"a.txt": b"abc\n", "b/c.bin": b"\x00\x01\xff", "empty.txt": b""}
        for name, data in contents.items():
            self.put(name, data)
        for label, token in (("str", ""), ("bytes", b"")):
            with self.subTest(label):
                self.assertEqual(run.scrub(str(self.root), token), 0)
                for name, data in contents.items():
                    self.assertEqual((self.root / name).read_bytes(), data, name)


class ConfigLiteralTests(unittest.TestCase):
    def test_sig_config_agent_key_equals_the_spec_literal(self):
        config = json.loads((F.ROOT / "selfcheck" / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(config["agent"], F.SPEC_AGENT_CFG)


class RunStateTests(F.RunCase):
    def derived_names(self, instance_id):
        pattern = re.compile(DERIVED_RE % re.escape(instance_id.lower()))
        return [e[1] for e in self.docker.log if e[0] == "image_id" and pattern.fullmatch(e[1])]

    # -- R1 / C1 ------------------------------------------------------------------------------

    def test_vo9_r1_completed_baseline_entry_writes_files_and_removes_the_container(self):
        self.docker.configure(diff_text=PLANTED_DIFF)
        run_dir = self.go(model="claude-haiku-5-5", effort="low")
        run_id = run_dir.name
        self.assertRegex(run_id, r"^[0-9a-f]{16}$")
        self.assertEqual(run_dir, self.runs_dir / run_id)
        entry = self.entry(run_dir, ROW_A, "baseline")
        for name in ("manifest.json", "state.json", "prediction.json"):
            self.assertTrue((entry / name).is_file(), name)
        raw = entry / "raw"
        self.assertEqual((raw / "full.diff").read_bytes(), PLANTED_DIFF.encode("utf-8"))
        for name in ("messages.jsonl", "ledger.jsonl", "user.jsonl", "state.json"):
            self.assertTrue((raw / name).is_file(), name)
        self.assertTrue((raw / "claude").is_dir())
        self.assertTrue((raw / "telemetry").is_dir())

        name = self.name(run_dir, 1)
        state = self.entry_state(run_dir)
        self.assertEqual(state["status"], "completed")
        self.assertEqual(state["container"], name)
        self.assertIs(state["host_timeout"], False)
        self.assertEqual(state["scrubbed_occurrences"], 0)
        self.assertIn("error", state)
        for key, value in F.driver_state_dict().items():
            self.assertEqual(state[key], value, key)

        prediction = self.load(entry / "prediction.json")
        self.assertEqual(
            prediction, F.expected_prediction(PLANTED_DIFF, ROW_A, "baseline", run_id, F.BASE_HEAD)
        )
        lines = (run_dir / "predictions.baseline.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual([json.loads(l) for l in lines], [prediction])
        self.assertFalse((run_dir / "predictions.harness.jsonl").exists())

        listing = self.load(run_dir / "run.json")
        self.assertEqual(set(listing), {"run_id", "entries", "created_at", "halted"})
        self.assertIsNone(listing["halted"])
        self.assertEqual(listing["run_id"], run_id)
        self.assertEqual(listing["entries"], [{"instance_id": ROW_A, "arm": "baseline", "status": "completed"}])

        self.assertNotIn(name, self.docker.containers)
        self.assertIn(name, self.docker.removed)
        self.assertEqual(self.docker.container_labelled(run_id), [])

    def test_vo9_r1_driver_input_carries_the_effective_configuration(self):
        original = json.loads(json.dumps(self.cfg))
        run_dir = self.go(model="claude-haiku-5-5", effort="low", cap_min=7)
        name = self.name(run_dir, 1)
        inp = self.docker.history[name].driver_inputs[0]
        self.assertEqual(
            inp,
            {
                "run_id": run_dir.name, "arm": "baseline", "prompt": F.expected_prompt(self.rows[ROW_A], "baseline"),
                "model": "claude-haiku-5-5", "effort": "low", "aliases": F.SPEC_AGENT_CFG["aliases"],
                "disallowed_tools": F.SPEC_AGENT_CFG["disallowed_tools"], "wall_clock_s": 420, "max_user_turns": 8,
                "idle_grace_s": 120, "phrase": F.PHRASE, "out_dir": "/selfcheck/out",
                "token_path": "/run/secrets/oauth_token", "proxy_url": "http://selfcheck-proxy:3128", "resume": None,
            },
        )
        self.assertEqual(self.cfg, original, "overrides must apply to a copy")
        manifest = self.load(self.entry(run_dir, ROW_A, "baseline") / "manifest.json")
        self.assertEqual((manifest["model"], manifest["effort"]), ("claude-haiku-5-5", "low"))
        self.assertEqual(manifest["caps"], {"wall_clock_min": 7, "max_user_turns": 8, "idle_grace_s": 120})

    def test_vo9_r1_without_overrides_the_configured_values_are_used(self):
        run_dir = self.go(cap_min=None)
        inp = self.docker.history[self.name(run_dir, 1)].driver_inputs[0]
        self.assertEqual((inp["model"], inp["effort"], inp["wall_clock_s"]), ("claude-opus-5-5", "low", 180 * 60))
        timeout = [kw["timeout"] for argv, kw in self.docker.execs(self.name(run_dir, 1)) if argv == F.DRIVER_ARGV]
        self.assertEqual(timeout, [180 * 60 + 600])

    def test_vo9_r1_driver_exec_and_extraction_use_the_pinned_calls(self):
        self.docker.configure(diff_text=PLANTED_DIFF)
        run_dir = self.go()
        name = self.name(run_dir, 1)
        execs = self.docker.execs(name)
        driver_calls = [(argv, kw) for argv, kw in execs if argv == F.DRIVER_ARGV]
        self.assertEqual(len(driver_calls), 1)
        kw = driver_calls[0][1]
        self.assertEqual((kw["user"], kw["workdir"]), ("nonroot", "/testbed"))
        self.assertEqual(kw["timeout"], 300 + 600)
        files = self.docker.history[name].files
        self.assertIn("/opt/selfcheck/agent/driver.py", files)
        self.assertIn("/opt/selfcheck/agent/user_sim.py", files)
        self.assertTrue(any(p.endswith("/selfcheck/in/input.json") for p in files))
        self.assertIsNotNone(self.docker.exec_index_containing(name, "/selfcheck/out"))
        copy_out = [e for e in self.docker.log if e[0] == "copy_out" and e[1] == name]
        self.assertEqual([(e[2], e[3]) for e in copy_out], [("/selfcheck/out/.", str(self.entry(run_dir, ROW_A, "baseline") / "raw"))])
        driver_at = self.docker.exec_index(name, F.DRIVER_ARGV)
        self.assertGreater(self.docker.log.index(copy_out[0]), driver_at)

    def test_vo9_r1_manifest_is_filled_for_the_baseline_entry(self):
        run_dir = self.go()
        manifest = self.load(self.entry(run_dir, ROW_A, "baseline") / "manifest.json")
        self.assertEqual(set(manifest), F.MANIFEST_KEYS)
        self.assertEqual(manifest["run_id"], run_dir.name)
        self.assertEqual(manifest["instance_id"], ROW_A)
        self.assertEqual(manifest["arm"], "baseline")
        self.assertEqual(manifest["harness_ref"], "HEAD")
        self.assertIsNone(manifest["harness_commit"])
        self.assertIsNone(manifest["install"])
        self.assertEqual(manifest["start_commit"], F.BASE_HEAD)
        self.assertRegex(manifest["selfcheck_commit"], r"^[0-9a-f]{40}$")
        self.assertEqual(manifest["cli_version"], "2.1.294")
        self.assertEqual(manifest["env_keys"], sorted(F.SPEC_ENV_KEYS))
        self.assertEqual(manifest["sdk"], F.SPEC_AGENT_CFG["sdk"])
        self.assertEqual(manifest["container"]["cpus"], 4)
        self.assertEqual(manifest["container"]["memory"], "6g")
        derived = self.derived_names(ROW_A)[0]
        images = manifest["images"]
        self.assertEqual(images["derived_image"], derived)
        self.assertEqual(images["derived_image_id"], "sha256:" + hashlib.sha256(derived.encode()).hexdigest())
        instance_image = "sweb.eval.arm64.%s:latest" % ROW_A.lower()
        self.assertEqual(images["instance_image_id"], "sha256:" + hashlib.sha256(instance_image.encode()).hexdigest())
        tools = [e[1] for e in self.docker.log if e[0] == "image_id" and e[1].startswith("selfcheck-tools:")]
        self.assertTrue(tools)
        self.assertEqual(images["tools_image_id"], "sha256:" + hashlib.sha256(tools[0].encode()).hexdigest())
        self.assertEqual(images["testbed_tools_resolved"], ["mutmut==2.5.1", "hypothesis==6.0"])
        self.assertEqual(manifest["network"]["allow_hosts"], ["api.anthropic.com"])
        self.assertEqual(manifest["network"]["proxy_image"], F.SPEC_AGENT_CFG["proxy_image"])
        self.assertRegex(manifest["network"]["squid_conf_hash"], r"^[0-9a-f]{64}$")
        self.assertEqual(manifest["tools"], F.INIT_DATA["tools"])

    def test_vo9_r1_ensure_egress_runs_once_after_the_token_check_and_before_the_first_container(self):
        run_dir = self.go(ids=(ROW_A, ROW_B), arms=("baseline",))
        self.assertEqual(self.egress.calls, 1)
        kinds = [e[0] for e in self.docker.log]
        self.assertLess(kinds.index("ensure_egress"), kinds.index("start_container"))

    # -- C2: harness arm ------------------------------------------------------------------------

    def harness_run(self, **script):
        self.docker.configure(diff_text=PLANTED_DIFF, **script)
        return self.go(arms=("harness",))

    def test_vo9_c2_harness_install_precedes_the_driver_and_the_diff_is_against_the_install_commit(self):
        run_dir = self.harness_run(hooks_path=".githooks", precommit=True)
        name = self.name(run_dir, 1)
        log = self.docker.log
        installer = self.docker.exec_index_containing(name, F.INSTALLER_FRAGMENT)
        commit = self.docker.exec_index_containing(name, "core.hooksPath=/dev/null")
        driver = self.docker.exec_index(name, F.DRIVER_ARGV)
        rev_after = next(
            (i for i, e in enumerate(log) if i > commit and e[0] == "exec" and e[1] == name and e[2] == F.REV_PARSE_ARGV), None
        )
        self.assertIsNotNone(rev_after, "start_commit must be read after the install commit")
        started = next(i for i, e in enumerate(log) if e[0] == "start_container")
        self.assertTrue(started < installer < commit < rev_after < driver)
        install_cmd = log[installer][2]
        self.assertEqual(install_cmd[:2], ["sh", "-c"])
        self.assertIn(
            "printf 'y\\ny\\ny\\n' | /opt/selfcheck-py/venv/bin/python /opt/harness-src/installer/harness.py install /testbed --no-ci",
            install_cmd[2],
        )
        for index in (installer, commit):
            self.assertEqual((log[index][3]["user"], log[index][3]["workdir"]), ("nonroot", "/testbed"))
        commit_text = " ".join(log[commit][2])
        for fragment in ("user.name=selfcheck", "user.email=selfcheck@localhost", "commit -q -m", "selfcheck: install harness"):
            self.assertIn(fragment, commit_text)
        removal = self.docker.exec_index_containing(name, "/opt/harness-src", after=installer)
        self.assertIsNotNone(removal)
        self.assertIn("rm", " ".join(log[removal][2]))
        inp = self.docker.history[name].driver_inputs[0]
        self.assertTrue(inp["prompt"].startswith("/workflow-approach "))
        self.assertEqual(inp["prompt"], F.expected_prompt(self.rows[ROW_A], "harness"))
        diff_calls = [e for e in log if e[0] == "exec" and e[2][:4] == ["git", "-c", "core.quotePath=true", "diff"]]
        self.assertEqual(len(diff_calls), 1)
        self.assertEqual(diff_calls[0][2][-1], F.INSTALL_HEAD)
        prediction = self.load(self.entry(run_dir, ROW_A, "harness") / "prediction.json")
        self.assertEqual(prediction["start_commit"], F.INSTALL_HEAD)
        self.assertEqual(prediction["excluded_paths"], sorted(F.PLANTED_BUCKETS["excluded"]))

    def test_vo9_c2_install_manifest_and_harness_commit(self):
        for hooks, precommit in ((".githooks", True), (None, False)):
            with self.subTest(hooks=hooks, precommit=precommit):
                self.docker = F.FakeDocker()
                self.egress.docker = self.docker
                run_dir = self.harness_run(hooks_path=hooks, precommit=precommit)
                manifest = self.load(self.entry(run_dir, ROW_A, "harness") / "manifest.json")
                self.assertEqual(manifest["harness_commit"], git_out("rev-parse", "HEAD").decode().strip())
                self.assertEqual(manifest["harness_ref"], "HEAD")
                self.assertEqual(manifest["start_commit"], F.INSTALL_HEAD)
                self.assertEqual(manifest["arm"], "harness")
                install = manifest["install"]
                self.assertEqual(set(install), {"hooks_path", "pre_commit_config_present", "definition_replaced"})
                if hooks is None:
                    self.assertIsNone(install["hooks_path"])
                else:
                    self.assertEqual(install["hooks_path"], hooks)
                self.assertIs(install["pre_commit_config_present"], precommit)
                self.assertIs(install["definition_replaced"], True)

    def test_vo9_c2_harness_ref_selects_the_archived_commit(self):
        self.docker.configure(diff_text=PLANTED_DIFF)
        run_dir = self.go(arms=("harness",), harness_ref="HEAD~1")
        manifest = self.load(self.entry(run_dir, ROW_A, "harness") / "manifest.json")
        commit = git_out("rev-parse", "HEAD~1").decode().strip()
        self.assertEqual(manifest["harness_ref"], "HEAD~1")
        self.assertEqual(manifest["harness_commit"], commit)
        files = self.docker.history[self.name(run_dir, 1)].files
        installer = [data for path, data in files.items() if path.endswith("installer/harness.py")]
        self.assertTrue(installer, "harness source was not copied into the container")
        self.assertEqual(installer[0], git_out("show", "%s:installer/harness.py" % commit))
        self.assertTrue(any(path.endswith("harness/bin/seed.py") for path in files))

    def test_vo9_c2_project_definition_replaces_either_placeholder(self):
        definition = F.project_definition(self.rows[ROW_A]["repo"])
        for placeholder in F.PLACEHOLDERS:
            with self.subTest(placeholder=placeholder):
                self.docker = F.FakeDocker()
                self.egress.docker = self.docker
                original = "# Project\n\n%s\n\nrest of file\n" % placeholder
                run_dir = self.harness_run(agents_md=original)
                name = self.name(run_dir, 1)
                self.assertEqual(
                    self.docker.history[name].files["/testbed/AGENTS.md"].decode("utf-8"),
                    original.replace(placeholder, definition),
                )
                written = [i for i, e in enumerate(self.docker.log) if e[0] == "write_text" and e[1] == name and e[2] == "/testbed/AGENTS.md"]
                self.assertEqual(len(written), 1)
                self.assertLess(written[0], self.docker.exec_index_containing(name, "core.hooksPath=/dev/null"))

    def test_vo9_c2_baseline_never_installs_or_copies_the_harness(self):
        run_dir = self.go(arms=("baseline",))
        name = self.name(run_dir, 1)
        self.assertIsNone(self.docker.exec_index_containing(name, F.INSTALLER_FRAGMENT))
        self.assertIsNone(self.docker.exec_index_containing(name, "core.hooksPath=/dev/null"))
        files = self.docker.history[name].files
        self.assertFalse([p for p in files if p.endswith("installer/harness.py")])
        inp = self.docker.history[name].driver_inputs[0]
        self.assertFalse(inp["prompt"].startswith("/workflow-approach"))

    # -- R2 / R3 / R4: interruption and resume ------------------------------------------------------

    def interrupted_run(self, **kw):
        self.docker.configure(diff_text=PLANTED_DIFF, driver=F.returning(F.driver_state_dict(**INTERRUPTED)))
        return self.go(**kw)

    def test_vo9_r2_interrupted_entry_keeps_a_stopped_container_and_has_no_prediction(self):
        run_dir = self.interrupted_run()
        name = self.name(run_dir, 1)
        entry = self.entry(run_dir, ROW_A, "baseline")
        state = self.entry_state(run_dir)
        self.assertEqual(state["status"], "interrupted")
        self.assertEqual(state["session_id"], "sess-A")
        self.assertIn(name, self.docker.containers)
        self.assertIs(self.docker.containers[name].running, False)
        self.assertEqual([e[:2] for e in self.docker.log if e[0] in ("stop", "remove")], [("stop", name)])
        self.assertFalse((entry / "prediction.json").exists())
        predictions = run_dir / "predictions.baseline.jsonl"
        self.assertTrue(not predictions.exists() or predictions.read_text(encoding="utf-8").strip() == "")
        self.assertIsNone(self.docker.exec_index_containing(name, "git add"))
        self.assertNotIn(F.GIT_ADD_ARGV, [argv for argv, _ in self.docker.execs(name)])
        self.assertTrue((entry / "raw" / "state.json").is_file())
        self.assertTrue((entry / "manifest.json").is_file())
        self.assertEqual(self.load(run_dir / "run.json")["entries"][0]["status"], "interrupted")
        self.assertEqual(self.docker.container_labelled(run_dir.name), [name])

    def test_vo9_r3_resume_continues_only_interrupted_or_absent_entries_with_stored_counters(self):
        # FR1 (spec 94b886658b88a7ef): a batch stops after an interrupted entry, so the interrupted entry is
        # the last one (4) and the absent entry (3) precedes it; entries 1 and 2 must stay untouched.
        self.docker.configure(diff_text=PLANTED_DIFF)
        self.docker.configure(n=2, driver=F.returning(F.driver_state_dict(status="stalled")))
        self.docker.configure(n=4, driver=F.returning(F.driver_state_dict(**INTERRUPTED)))
        run_dir = self.go(ids=(ROW_A, ROW_B), arms=("baseline", "harness"))
        run_id = run_dir.name
        self.assertEqual([e["status"] for e in self.load(run_dir / "run.json")["entries"]],
                         ["completed", "stalled", "completed", "interrupted"])
        self.assertEqual(self.load(run_dir / "run.json")["halted"],
                         {"reason": "interrupted", "instance_id": ROW_B, "arm": "harness"})
        shutil.rmtree(self.entry(run_dir, ROW_B, "baseline"))
        before = {
            str(p): p.read_bytes()
            for n_arm in ((ROW_A, "baseline"), (ROW_A, "harness"))
            for p in self.entry(run_dir, *n_arm).rglob("*") if p.is_file()
        }
        interrupted = self.docker.history[self.name(run_dir, 4)]
        interrupted.script.driver = F.returning(F.driver_state_dict(phrases_sent=3, elapsed_s=80.0))
        mark = len(self.docker.log)

        self.assertEqual(self.resume(run_id), run_dir)

        after_log = self.docker.log[mark:]
        names_touched = {e[1] for e in after_log if e[0] in ("exec", "start", "start_container", "copy_in", "copy_out", "stop", "remove")}
        self.assertEqual(names_touched, {self.name(run_dir, 3), self.name(run_dir, 4)})
        after = {
            str(p): p.read_bytes()
            for n_arm in ((ROW_A, "baseline"), (ROW_A, "harness"))
            for p in self.entry(run_dir, *n_arm).rglob("*") if p.is_file()
        }
        self.assertEqual(after, before)

        resumed = interrupted.driver_inputs
        self.assertEqual(len(resumed), 2)
        self.assertEqual(resumed[1]["resume"], {"session_id": "sess-A", "phrases_sent": 2, "elapsed_s": 33.5})
        self.assertEqual(resumed[1]["run_id"], run_id)
        timeout = [kw["timeout"] for argv, kw in self.docker.execs(self.name(run_dir, 4)) if argv == F.DRIVER_ARGV][-1]
        self.assertEqual(timeout, 300 - 33.5 + 600)
        self.assertLess(
            [i for i, e in enumerate(self.docker.log) if e[0] == "stop" and e[1] == self.name(run_dir, 4)][0],
            [i for i, e in enumerate(self.docker.log) if e[0] == "start" and e[1] == self.name(run_dir, 4)][0],
        )
        fresh = self.docker.history[self.name(run_dir, 3)]
        self.assertIsNone(fresh.driver_inputs[0]["resume"])
        self.assertEqual(self.entry_state(run_dir, ROW_B, "harness")["status"], "completed")
        self.assertTrue((self.entry(run_dir, ROW_B, "harness") / "prediction.json").is_file())
        self.assertTrue((self.entry(run_dir, ROW_B, "baseline") / "prediction.json").is_file())
        self.assertEqual([e["status"] for e in self.load(run_dir / "run.json")["entries"]],
                         ["completed", "stalled", "completed", "completed"])
        self.assertIsNone(self.load(run_dir / "run.json")["halted"])
        self.assertEqual(self.docker.container_labelled(run_id), [])
        lines = (run_dir / "predictions.baseline.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(sorted(json.loads(l)["instance_id"] for l in lines), sorted([ROW_A, ROW_B]))

    def test_vo9_r3_resume_does_not_reinstall_the_harness(self):
        self.docker.configure(diff_text=PLANTED_DIFF, driver=F.returning(F.driver_state_dict(**INTERRUPTED)))
        run_dir = self.go(arms=("harness",))
        name = self.name(run_dir, 1)
        self.docker.history[name].script.driver = F.returning(F.driver_state_dict())
        self.resume(run_dir.name)
        installs = [1 for argv, _ in self.docker.execs(name) if len(argv) > 2 and F.INSTALLER_FRAGMENT in argv[2]]
        self.assertEqual(len(installs), 1)
        prediction = self.load(self.entry(run_dir, ROW_A, "harness") / "prediction.json")
        self.assertEqual(prediction["start_commit"], F.INSTALL_HEAD)

    def test_vo9_r4_missing_container_on_resume_ends_the_entry_in_error(self):
        run_dir = self.interrupted_run()
        name = self.name(run_dir, 1)
        self.docker.vanish(name)
        mark = len(self.docker.log)
        self.resume(run_dir.name)
        state = self.entry_state(run_dir)
        self.assertEqual(state["status"], "error")
        self.assertEqual(state["reason"], "container lost")
        self.assertEqual(self.load(run_dir / "run.json")["entries"][0]["status"], "error")
        self.assertNotIn(F.DRIVER_ARGV, [e[2] for e in self.docker.log[mark:] if e[0] == "exec"])

    def test_vo9_r4_resume_of_a_stopped_container_that_cannot_be_found_never_creates_a_new_one(self):
        run_dir = self.interrupted_run()
        self.docker.vanish(self.name(run_dir, 1))
        before = len(self.docker.started())
        self.resume(run_dir.name)
        self.assertEqual(len(self.docker.started()), before)

    # -- R5 .. R8: error paths ------------------------------------------------------------------

    def test_vo9_r5_missing_derived_image_errors_the_entry_and_the_next_entry_still_runs(self):
        marker = ROW_A.lower()
        self.docker = F.FakeDocker(image_missing=lambda n: n.startswith("selfcheck-agent.") and marker in n)
        self.egress.docker = self.docker
        run_dir = self.go(ids=(ROW_A, ROW_B), arms=("baseline",))
        state = self.entry_state(run_dir, ROW_A)
        self.assertEqual(state["status"], "error")
        self.assertRegex(state["reason"], IMAGE_MISSING_RE % (DERIVED_RE % re.escape(marker)))
        started = [e[1] for e in self.docker.started()]
        self.assertEqual(started, [self.name(run_dir, 2)])
        self.assertEqual(self.entry_state(run_dir, ROW_B)["status"], "completed")
        self.assertEqual([e["status"] for e in self.load(run_dir / "run.json")["entries"]], ["error", "completed"])

    def test_vo9_r5_absent_tools_or_instance_image_is_named_in_the_reason(self):
        instance_image = "sweb.eval.arm64.%s:latest" % ROW_A.lower()
        cases = (
            ("tools image absent", lambda n: n.startswith("selfcheck-tools:"), r"selfcheck-tools:[0-9a-f]{12}", [ROW_A, ROW_B]),
            ("instance image absent", lambda n: n == instance_image, re.escape(instance_image), [ROW_A]),
        )
        for name, missing, image_re, failing in cases:
            with self.subTest(name):
                self.docker = F.FakeDocker(image_missing=missing)
                self.egress.docker = self.docker
                run_dir = self.go(ids=(ROW_A, ROW_B), arms=("baseline",))
                for instance_id in failing:
                    state = self.entry_state(run_dir, instance_id)
                    self.assertEqual(state["status"], "error")
                    self.assertRegex(state["reason"], IMAGE_MISSING_RE % image_re)
                expected_started = [] if len(failing) == 2 else [self.name(run_dir, 2)]
                self.assertEqual([e[1] for e in self.docker.started()], expected_started)
                statuses = [e["status"] for e in self.load(run_dir / "run.json")["entries"]]
                self.assertEqual(statuses, ["error", "error"] if len(failing) == 2 else ["error", "completed"])

    def test_vo9_r6_install_commit_failure_keeps_install_log_and_removes_the_container(self):
        self.docker.configure(diff_text=PLANTED_DIFF, exec_fail={"core.hooksPath=/dev/null": (1, "commit boom output\n", False)})
        run_dir = self.go(arms=("harness",))
        name = self.name(run_dir, 1)
        state = self.entry_state(run_dir, arm="harness")
        self.assertEqual(state["status"], "error")
        self.assertTrue(state["reason"].startswith("install failed"), state["reason"])
        log = self.entry(run_dir, ROW_A, "harness") / "raw" / "install.log"
        self.assertTrue(log.is_file())
        self.assertIn("commit boom output", log.read_text(encoding="utf-8"))
        self.assertNotIn(name, self.docker.containers)
        self.assertIsNone(self.docker.exec_index(name, F.DRIVER_ARGV))
        self.assertEqual(self.load(run_dir / "run.json")["entries"][0]["status"], "error")

    def test_vo9_r6_installer_failure_keeps_install_log_and_removes_the_container(self):
        self.docker.configure(diff_text=PLANTED_DIFF, installer=(3, "INSTALLER-BROKEN output line\n"))
        run_dir = self.go(arms=("harness",))
        name = self.name(run_dir, 1)
        state = self.entry_state(run_dir, arm="harness")
        self.assertEqual(state["status"], "error")
        self.assertEqual(state["reason"], "install failed: exit 3")
        log = self.entry(run_dir, ROW_A, "harness") / "raw" / "install.log"
        self.assertIn("INSTALLER-BROKEN output line", log.read_text(encoding="utf-8"))
        self.assertNotIn(name, self.docker.containers)
        self.assertIsNone(self.docker.exec_index(name, F.DRIVER_ARGV))
        self.assertIsNone(self.docker.exec_index_containing(name, "core.hooksPath=/dev/null"))
        self.assertEqual(self.load(run_dir / "run.json")["entries"][0]["status"], "error")

    def test_vo9_r7_any_non_zero_driver_exit_is_an_error_with_the_exit_code(self):
        for code in (2, 3):
            with self.subTest(code=code):
                self.docker = F.FakeDocker()
                self.egress.docker = self.docker
                self.docker.configure(driver=F.returning(F.driver_state_dict(), exit_code=code))
                run_dir = self.go()
                state = self.entry_state(run_dir)
                self.assertEqual((state["status"], state["reason"]), ("error", "driver exit %d" % code))
                self.assertNotIn(self.name(run_dir, 1), self.docker.containers)

    def test_vo9_r7_exit_0_without_a_readable_state_is_driver_state_missing(self):
        cases = (("absent", dict(omit_state=True)), ("invalid json", dict(raw_state=b"{not json")))
        for name, kw in cases:
            with self.subTest(name):
                self.docker = F.FakeDocker()
                self.egress.docker = self.docker
                self.docker.configure(driver=F.returning(**kw))
                run_dir = self.go()
                state = self.entry_state(run_dir)
                self.assertEqual((state["status"], state["reason"]), ("error", "driver state missing"))

    def test_vo9_r8_host_timeout_marks_the_entry_capped_and_extraction_proceeds(self):
        self.docker.configure(
            diff_text=PLANTED_DIFF,
            driver=F.returning(F.driver_state_dict(status="running", reason=None), timed_out=True),
        )
        run_dir = self.go()
        name = self.name(run_dir, 1)
        state = self.entry_state(run_dir)
        self.assertEqual(state["status"], "capped")
        self.assertEqual(state["reason"], "wall_clock")
        self.assertIs(state["host_timeout"], True)
        timeout = [kw["timeout"] for argv, kw in self.docker.execs(name) if argv == F.DRIVER_ARGV]
        self.assertEqual(timeout, [300 + 600])
        self.assertLess(self.docker.exec_index(name, F.DRIVER_ARGV), self.docker.exec_index(name, F.KILL_ARGV))
        self.assertTrue((self.entry(run_dir, ROW_A, "baseline") / "prediction.json").is_file())
        self.assertEqual(self.load(run_dir / "run.json")["entries"][0]["status"], "capped")
        self.assertNotIn(name, self.docker.containers)

    # -- R9: token file -------------------------------------------------------------------------

    def test_vo9_r9_missing_or_irregular_token_file_stops_before_any_docker_call(self):
        missing = str(Path(self.tmp) / "absent-token")
        directory = Path(self.tmp) / "a-directory"
        directory.mkdir()
        for name, path in (("absent", missing), ("directory", str(directory))):
            with self.subTest(name):
                self.cfg["token_file"] = path
                with self.assertRaises(run.TokenFileMissing) as caught:
                    self.go()
                self.assertIsInstance(caught.exception, RuntimeError)
                self.assertEqual(str(caught.exception), "token file missing: " + path)
                self.assertEqual(self.docker.log, [])
                self.assertEqual(self.egress.calls, 0)

    def test_vo9_r9_token_path_is_expanded_in_the_message(self):
        with mock.patch.dict(os.environ, {"HOME": self.tmp}):
            self.cfg["token_file"] = "~/no-such-token"
            with self.assertRaises(run.TokenFileMissing) as caught:
                self.go()
        self.assertEqual(str(caught.exception), "token file missing: %s/no-such-token" % self.tmp)

    def test_vo9_r9_resume_checks_token_and_run_before_any_docker_call(self):
        run_dir = self.go()
        self.docker.log.clear()
        Path(self.token_path).unlink()
        with self.assertRaises(run.TokenFileMissing):
            self.resume(run_dir.name)
        self.assertEqual(self.docker.log, [])
        Path(self.token_path).write_text(self.token + "\n", encoding="utf-8")
        with self.assertRaises(run.UnknownRunError) as caught:
            self.resume("0" * 16)
        self.assertIsInstance(caught.exception, LookupError)
        self.assertEqual(self.docker.log, [])
        self.assertFalse((self.runs_dir / ("0" * 16)).exists())

    # -- R10: scrubbing --------------------------------------------------------------------------

    def test_vo9_r10_token_in_collected_output_is_redacted_and_counted(self):
        token = self.token
        messages = '{"a": "%s"} {"b": "%s"}\n' % (token, token)
        transcript = "prefix %s suffix\n" % token
        self.docker.configure(
            diff_text=PLANTED_DIFF,
            driver=F.returning(extra={"messages.jsonl": messages, "claude/projects/-testbed/s.jsonl": transcript}),
        )
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            run_dir = self.go()
        raw = self.entry(run_dir, ROW_A, "baseline") / "raw"
        self.assertEqual((raw / "messages.jsonl").read_text(encoding="utf-8"), messages.replace(token, "[REDACTED]"))
        self.assertEqual(
            (raw / "claude/projects/-testbed/s.jsonl").read_text(encoding="utf-8"), transcript.replace(token, "[REDACTED]")
        )
        state = self.entry_state(run_dir)
        self.assertEqual(state["scrubbed_occurrences"], 3)
        self.assertEqual(state["status"], "completed")
        self.assertEqual(files_containing(run_dir, token.encode()), [])
        self.assertEqual(out.getvalue().count(token) + err.getvalue().count(token), 0)

    def test_vo9_r10_token_inside_the_driver_state_is_scrubbed_from_every_entry_file(self):
        token = self.token
        state = F.driver_state_dict(reason="leaked %s in reason" % token)
        self.docker.configure(driver=F.returning(state))
        run_dir = self.go()
        entry = self.entry(run_dir, ROW_A, "baseline")
        self.assertEqual(files_containing(entry, token.encode()), [])
        self.assertEqual(files_containing(run_dir, token.encode()), [])
        host_state = self.load(entry / "state.json")
        self.assertGreaterEqual(host_state["scrubbed_occurrences"], 1)
        self.assertNotEqual(host_state["status"], "error")

    def test_vo9_r10_token_in_the_diff_is_absent_from_every_prediction_artifact(self):
        token = self.token
        diff, _ = F.real_git_diff({"pkg/a.py": "x = 1\n"}, {"pkg/a.py": "x = 1\nTOKEN = '%s'\n" % token})
        self.docker.configure(diff_text=diff)
        run_dir = self.go()
        self.assertEqual(files_containing(run_dir, token.encode()), [])
        prediction = self.load(self.entry(run_dir, ROW_A, "baseline") / "prediction.json")
        self.assertIn("[REDACTED]", prediction["src_diff"])
        lines = (run_dir / "predictions.baseline.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual([json.loads(l) for l in lines], [prediction])

    def test_vo9_r10_token_remaining_after_scrub_ends_the_entry_in_error_and_keeps_the_files(self):
        token = self.token
        self.docker.configure(driver=F.returning(extra={"messages.jsonl": "leak %s\n" % token}))
        calls = []

        def ineffective_scrub(*args, **kwargs):
            calls.append(args)
            return 0 if len(calls) == 1 else 1

        with mock.patch.object(run, "scrub", side_effect=ineffective_scrub):
            run_dir = self.go()
        state_text = (self.entry(run_dir, ROW_A, "baseline") / "state.json").read_text(encoding="utf-8")
        state = json.loads(state_text)
        self.assertEqual(state["status"], "error")
        self.assertEqual(state["reason"], "token remained after scrub")
        self.assertIsInstance(state["scrubbed_occurrences"], int)
        self.assertNotIn(token, state_text)
        self.assertIn(token, (self.entry(run_dir, ROW_A, "baseline") / "raw" / "messages.jsonl").read_text(encoding="utf-8"))
        self.assertNotIn(self.name(run_dir, 1), self.docker.containers)
        self.assertEqual(self.load(run_dir / "run.json")["entries"][0]["status"], "error")

    # -- R11 / R12 / R13 ---------------------------------------------------------------------------

    def test_vo9_r11_run_directory_and_created_parents_are_mode_0700(self):
        self.cfg["runs_dir"] = str(Path(self.tmp) / "a" / "b" / "runs")
        run_dir = self.go()
        for path in (Path(self.tmp) / "a", Path(self.tmp) / "a" / "b", Path(self.tmp) / "a" / "b" / "runs", run_dir):
            with self.subTest(path=str(path)):
                self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o700)

    def test_vo9_r12_start_container_arguments_are_exact(self):
        home = Path(self.tmp) / "home"
        home.mkdir()
        token_path, _ = F.write_token_file(home)
        self.cfg["runs_dir"] = "~/runs"
        self.cfg["token_file"] = "~/oauth_token"
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            run_dir = self.go()
        self.assertEqual(run_dir, home / "runs" / run_dir.name)
        started = self.docker.started()
        self.assertEqual(len(started), 1)
        _, name, kwargs = started[0]
        self.assertEqual(name, "selfcheck-agent-%s-1" % run_dir.name)
        self.assertRegex(kwargs["image"], r"^%s$" % (DERIVED_RE % re.escape(ROW_A.lower())))
        self.assertEqual(
            {k: v for k, v in kwargs.items() if k != "image"},
            {
                "network": "selfcheck-int", "labels": {"selfcheck.agent": run_dir.name}, "cpus": 4, "memory": "6g",
                "mounts": ["type=bind,src=%s,dst=/run/secrets/oauth_token,readonly" % token_path],
            },
        )

    def test_vo9_r13_entries_run_instance_major_in_arm_order_and_run_json_tracks_statuses(self):
        snapshots = []
        run_root = self.runs_dir

        def peek_then_stall(container, inp):
            try:
                path = next(run_root.iterdir()) / "run.json"
                snapshots.append(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                snapshots.append(None)
            return F.DriverResult(0, F.driver_files(F.driver_state_dict(status="stalled")), False)

        self.docker.configure(diff_text=PLANTED_DIFF)
        self.docker.configure(n=2, driver=peek_then_stall)
        self.docker.configure(n=3, driver=F.returning(F.driver_state_dict(status="capped", reason="wall_clock")))
        self.docker.configure(n=4, driver=F.returning(F.driver_state_dict(**INTERRUPTED)))
        run_dir = self.go(ids=(ROW_A, ROW_B), arms=("harness", "baseline"))
        listing = self.load(run_dir / "run.json")
        self.assertEqual(
            listing["entries"],
            [
                {"instance_id": ROW_A, "arm": "harness", "status": "completed"},
                {"instance_id": ROW_A, "arm": "baseline", "status": "stalled"},
                {"instance_id": ROW_B, "arm": "harness", "status": "capped"},
                {"instance_id": ROW_B, "arm": "baseline", "status": "interrupted"},
            ],
        )
        self.assertEqual(listing["halted"], {"reason": "interrupted", "instance_id": ROW_B, "arm": "baseline"})
        self.assertEqual([e[1] for e in self.docker.started()], [self.name(run_dir, n) for n in (1, 2, 3, 4)])
        self.assertIsNotNone(snapshots[0], "run.json must exist while the second entry runs")
        self.assertEqual(snapshots[0]["entries"][0]["status"], "completed")
        harness_lines = [json.loads(l) for l in (run_dir / "predictions.harness.jsonl").read_text(encoding="utf-8").splitlines()]
        baseline_lines = [json.loads(l) for l in (run_dir / "predictions.baseline.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([p["instance_id"] for p in harness_lines], [ROW_A, ROW_B])
        self.assertEqual([p["instance_id"] for p in baseline_lines], [ROW_A])
        for line in harness_lines:
            self.assertEqual(line, self.load(self.entry(run_dir, line["instance_id"], "harness") / "prediction.json"))
        self.assertFalse((self.entry(run_dir, ROW_B, "baseline") / "prediction.json").exists())

    def test_vo9_r13_arm_order_follows_the_requested_order(self):
        run_dir = self.go(ids=(ROW_A, ROW_B), arms=("baseline", "harness"))
        entries = self.load(run_dir / "run.json")["entries"]
        self.assertEqual(
            [(e["instance_id"], e["arm"]) for e in entries],
            [(ROW_A, "baseline"), (ROW_A, "harness"), (ROW_B, "baseline"), (ROW_B, "harness")],
        )

    # -- Batch 3: R2, R3, R8, R14, R15, R16, R18, R19 ---------------------------------------------------

    def after_driver(self, name):
        start = self.docker.exec_index(name, F.DRIVER_ARGV)
        self.assertIsNotNone(start, "driver was never executed")
        return self.docker.log[start + 1:]

    def test_vo9_r2_an_interrupted_entry_runs_no_freeze_seed_or_git_exec_after_the_driver(self):
        for arm in ("baseline", "harness"):
            with self.subTest(arm=arm):
                self.docker = F.FakeDocker()
                self.egress.docker = self.docker
                run_dir = self.interrupted_run(arms=(arm,))
                name = self.name(run_dir, 1)
                tail = self.after_driver(name)
                self.assertEqual([e for e in tail if e[0] == "processes"], [])
                execs = [e[2] for e in tail if e[0] == "exec"]
                for forbidden in (F.KILL_ARGV, F.SEED_STATUS_ARGV, F.SEED_RESTORE_ARGV, F.GIT_ADD_ARGV):
                    self.assertNotIn(forbidden, execs)
                self.assertEqual([argv for argv in execs if argv[:4] == ["git", "-c", "core.quotePath=true", "diff"]], [])
                self.assertEqual([argv for argv in execs if argv[:2] == ["git", "add"]], [])
                self.assertEqual([e[:2] for e in tail if e[0] in ("stop", "remove")], [("stop", name)])

    def test_vo9_r3_resume_reuses_the_original_model_effort_cap_and_harness_commit(self):
        self.docker.configure(diff_text=PLANTED_DIFF, driver=F.returning(F.driver_state_dict(**INTERRUPTED)))
        run_dir = self.go(arms=("harness",), model="claude-haiku-5-5", effort="low", cap_min=7, harness_ref="HEAD~1")
        name = self.name(run_dir, 1)
        entry = self.entry(run_dir, ROW_A, "harness")
        original = self.load(entry / "manifest.json")
        expected_commit = git_out("rev-parse", "HEAD~1").decode().strip()
        self.assertEqual(original["harness_commit"], expected_commit)

        self.cfg.update(model="claude-sonnet-5-5", effort="high", wall_clock_min=99)
        self.docker.history[name].script.driver = F.returning(F.driver_state_dict(phrases_sent=3, elapsed_s=80.0))
        self.resume(run_dir.name)

        inputs = self.docker.history[name].driver_inputs
        self.assertEqual(len(inputs), 2)
        self.assertEqual((inputs[1]["model"], inputs[1]["effort"], inputs[1]["wall_clock_s"]), ("claude-haiku-5-5", "low", 420))
        timeout = [kw["timeout"] for argv, kw in self.docker.execs(name) if argv == F.DRIVER_ARGV][-1]
        self.assertEqual(timeout, 420 - 33.5 + 600)
        resumed = self.load(entry / "manifest.json")
        self.assertEqual(resumed["harness_commit"], expected_commit)
        for key in ("model", "effort", "harness_ref", "harness_commit", "selfcheck_commit", "start_commit"):
            self.assertEqual(resumed[key], original[key], key)
        self.assertEqual(resumed["caps"]["wall_clock_min"], 7)
        self.assertEqual(self.entry_state(run_dir, arm="harness")["status"], "completed")

    def test_vo9_r3_resume_takes_start_commit_install_and_selfcheck_commit_from_storage(self):
        stored_install = {"hooks_path": ".githooks", "pre_commit_config_present": True, "definition_replaced": True}
        self.docker.configure(
            diff_text=PLANTED_DIFF, hooks_path=".githooks", precommit=True,
            driver=F.returning(F.driver_state_dict(**INTERRUPTED)),
        )
        run_dir = self.go(arms=("harness",))
        name = self.name(run_dir, 1)
        entry = self.entry(run_dir, ROW_A, "harness")
        first = self.load(entry / "manifest.json")
        self.assertEqual(first["install"], stored_install)
        self.assertEqual(first["start_commit"], F.INSTALL_HEAD)

        sentinel = "5" * 40
        params = self.load(run_dir / "params.json")
        self.assertIn("selfcheck_commit", params)
        self.assertNotEqual(params["selfcheck_commit"], sentinel)
        params["selfcheck_commit"] = sentinel
        (run_dir / "params.json").write_text(json.dumps(params), encoding="utf-8")

        moved_head = "d" * 40
        state = self.docker.history[name]
        state.head = moved_head
        state.script.driver = F.returning(F.driver_state_dict(phrases_sent=3, elapsed_s=80.0))
        mark = len(self.docker.log)
        self.resume(run_dir.name)

        resumed = self.load(entry / "manifest.json")
        self.assertEqual(resumed["start_commit"], F.INSTALL_HEAD)
        self.assertNotEqual(resumed["start_commit"], moved_head)
        self.assertEqual(resumed["install"], stored_install)
        self.assertEqual(resumed["selfcheck_commit"], sentinel)
        prediction = self.load(entry / "prediction.json")
        self.assertEqual(prediction["start_commit"], F.INSTALL_HEAD)
        diffs = [e for e in self.docker.log[mark:] if e[0] == "exec" and e[1] == name and e[2][:4] == ["git", "-c", "core.quotePath=true", "diff"]]
        self.assertEqual(len(diffs), 1)
        self.assertEqual(diffs[0][2][-1], F.INSTALL_HEAD)
        self.assertEqual(self.entry_state(run_dir, arm="harness")["status"], "completed")

    def test_vo9_r3_an_interrupted_entry_without_a_manifest_takes_the_start_commit_from_the_container(self):
        run_dir = self.interrupted_run()
        name = self.name(run_dir, 1)
        entry = self.entry(run_dir, ROW_A, "baseline")
        (entry / "manifest.json").unlink()
        fresh_head = "c" * 40
        self.docker.history[name].head = fresh_head
        self.docker.history[name].script.driver = F.returning(F.driver_state_dict())
        mark = len(self.docker.log)
        self.resume(run_dir.name)
        revs = [e for e in self.docker.log[mark:] if e[0] == "exec" and e[1] == name and e[2] == F.REV_PARSE_ARGV]
        self.assertEqual(len(revs), 1)
        self.assertEqual((revs[0][3]["user"], revs[0][3]["workdir"]), ("nonroot", "/testbed"))
        self.assertEqual(self.load(entry / "manifest.json")["start_commit"], fresh_head)
        self.assertEqual(self.load(entry / "prediction.json")["start_commit"], fresh_head)

    def test_vo9_r8_freeze_precedes_the_host_read_of_the_driver_state_on_a_host_timeout(self):
        self.docker.configure(
            diff_text=PLANTED_DIFF,
            driver=F.returning(F.driver_state_dict(status="running", reason=None), timed_out=True),
        )
        run_dir = self.go()
        name = self.name(run_dir, 1)
        log = self.docker.log
        driver_at = self.docker.exec_index(name, F.DRIVER_ARGV)
        processes_at = next(i for i, e in enumerate(log) if i > driver_at and e[0] == "processes" and e[1] == name)
        kill_at = next(i for i, e in enumerate(log) if i > driver_at and e[0] == "exec" and e[1] == name and e[2] == F.KILL_ARGV)
        read_at = next(
            i for i, e in enumerate(log)
            if i > driver_at and e[0] == "read_bytes" and e[1] == name and e[2] == "/selfcheck/out/state.json"
        )
        self.assertLess(processes_at, kill_at)
        self.assertLess(kill_at, read_at)

    def failure_scenarios(self):
        marker = ROW_A.lower()
        return (
            ("image missing", "baseline", {}, lambda n: n.startswith("selfcheck-agent.") and marker in n,
             lambda r: r.startswith("image missing: ")),
            ("installer exit", "harness", dict(installer=(3, "broken\n")), None, lambda r: r == "install failed: exit 3"),
            ("install commit", "harness", dict(exec_fail={"core.hooksPath=/dev/null": (1, "commit boom output\n", False)}),
             None, lambda r: r.startswith("install failed")),
            ("driver exit 2", "baseline", dict(driver=F.returning(F.driver_state_dict(), exit_code=2)), None,
             lambda r: r == "driver exit 2"),
            ("driver exit 3", "baseline", dict(driver=F.returning(F.driver_state_dict(), exit_code=3)), None,
             lambda r: r == "driver exit 3"),
            ("driver state missing", "baseline", dict(driver=F.returning(omit_state=True)), None,
             lambda r: r == "driver state missing"),
            ("git add", "baseline", dict(add_fail=(128, "fatal: boom-add")), None, lambda r: r == "git failed: fatal: boom-add"),
            ("git diff", "baseline", dict(diff_fail=(129, "fatal: boom-diff")), None, lambda r: r == "git failed: fatal: boom-diff"),
        )

    def assert_host_failure(self, run_dir, arm, reason_ok):
        entry = self.entry(run_dir, ROW_A, arm)
        state = self.load(entry / "state.json")
        self.assertEqual(state["status"], "error")
        self.assertTrue(reason_ok(state["reason"]), state["reason"])
        self.assertEqual(state["error"], state["reason"])
        self.assertFalse((entry / "prediction.json").exists())
        predictions = run_dir / ("predictions.%s.jsonl" % arm)
        lines = [l for l in predictions.read_text(encoding="utf-8").splitlines() if l.strip()] if predictions.exists() else []
        self.assertEqual(lines, [])
        self.assertEqual(self.load(run_dir / "run.json")["entries"][0]["status"], "error")

    def test_vo9_r14_host_detected_failures_write_no_prediction_and_set_error_to_the_reason(self):
        for name, arm, script, missing, reason_ok in self.failure_scenarios():
            with self.subTest(name):
                self.docker = F.FakeDocker(image_missing=missing)
                self.egress.docker = self.docker
                self.docker.configure(diff_text=PLANTED_DIFF, **script)
                run_dir = self.go(arms=(arm,))
                self.assert_host_failure(run_dir, arm, reason_ok)

    def test_vo9_r14_a_lost_container_on_resume_writes_no_prediction_and_sets_error_to_the_reason(self):
        run_dir = self.interrupted_run()
        self.docker.vanish(self.name(run_dir, 1))
        self.resume(run_dir.name)
        self.assert_host_failure(run_dir, "baseline", lambda r: r == "container lost")

    def test_vo9_r14_a_driver_reported_error_keeps_host_error_null_and_is_extracted_and_predicted(self):
        reported = F.driver_state_dict(status="error", reason="RuntimeError: boom")
        self.docker.configure(diff_text=PLANTED_DIFF, driver=F.returning(reported))
        run_dir = self.go()
        name = self.name(run_dir, 1)
        entry = self.entry(run_dir, ROW_A, "baseline")
        state = self.entry_state(run_dir)
        self.assertEqual((state["status"], state["reason"]), ("error", "RuntimeError: boom"))
        self.assertIsNone(state["error"])
        prediction = self.load(entry / "prediction.json")
        self.assertEqual(prediction, F.expected_prediction(PLANTED_DIFF, ROW_A, "baseline", run_dir.name, F.BASE_HEAD))
        lines = (run_dir / "predictions.baseline.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual([json.loads(l) for l in lines], [prediction])
        self.assertIsNotNone(self.docker.exec_index(name, F.diff_argv(F.BASE_HEAD)))
        self.assertNotIn(name, self.docker.containers)
        self.assertIn(name, self.docker.removed)
        self.assertEqual(self.load(run_dir / "run.json")["entries"][0]["status"], "error")

    def test_vo9_r15_an_egress_failure_raises_before_any_container_or_entry_directory(self):
        error = docker_exec.DockerError("proxy could not be started: daemon exploded")
        self.egress.error = error
        with self.assertRaises(docker_exec.DockerError) as caught:
            self.go(ids=(ROW_A, ROW_B))
        self.assertIn(str(error), str(caught.exception))
        self.assertEqual(self.docker.started(), [])
        self.assertEqual(self.docker.calls("exec"), [])
        for instance_id in (ROW_A, ROW_B):
            self.assertEqual(list(self.runs_dir.rglob(instance_id)), [])
        self.assertEqual(self.egress.calls, 1)

    def test_vo9_r16_created_at_is_the_injected_now_and_the_manifest_records_user_and_unset_hooks_path(self):
        run_dir = self.go(arms=("harness", "baseline"), now=lambda: 1700000000.25)
        self.assertEqual(self.load(run_dir / "run.json")["created_at"], 1700000000.25)
        for arm in ("harness", "baseline"):
            with self.subTest(arm=arm):
                manifest = self.load(self.entry(run_dir, ROW_A, arm) / "manifest.json")
                self.assertEqual(manifest["container"], {"cpus": 4, "memory": "6g", "user": "nonroot"})
        harness = self.load(self.entry(run_dir, ROW_A, "harness") / "manifest.json")
        self.assertIsNone(harness["install"]["hooks_path"])

    def test_vo9_r18_resume_of_a_run_directory_without_params_json_raises_and_changes_nothing(self):
        run_dir = self.go()
        (run_dir / "params.json").unlink()
        snapshot = {str(p.relative_to(run_dir)): (p.read_bytes() if p.is_file() else None) for p in run_dir.rglob("*")}
        self.docker.log.clear()
        calls_before = self.egress.calls
        with self.assertRaises(run.UnknownRunError) as caught:
            self.resume(run_dir.name)
        self.assertIsInstance(caught.exception, LookupError)
        self.assertEqual(self.docker.log, [])
        self.assertEqual(self.egress.calls, calls_before)
        after = {str(p.relative_to(run_dir)): (p.read_bytes() if p.is_file() else None) for p in run_dir.rglob("*")}
        self.assertEqual(after, snapshot)

    # -- R19: the pinned install commands --------------------------------------------------------------

    def install_sequence(self, name):
        pinned = {
            tuple(F.MKDIR_OUT_ARGV): "mkdir", tuple(F.EXTRACT_ARGV): "extract", tuple(F.CHOWN_AGENTS_ARGV): "chown",
            tuple(F.COMMIT_ARGV): "commit", tuple(F.REV_PARSE_ARGV): "start_commit", tuple(F.HOOKS_ARGV): "hooks",
            tuple(F.PRECOMMIT_ARGV): "precommit", tuple(F.CLEANUP_ARGV): "cleanup",
        }
        driver_at = self.docker.exec_index(name, F.DRIVER_ARGV)
        steps = []
        for entry in self.docker.log[:driver_at]:
            if len(entry) < 2 or entry[1] != name:
                continue
            if entry[0] == "copy_in" and entry[3] == "/opt/harness-src.tar":
                steps.append(("copy_tar", None, None, entry))
            elif entry[0] == "write_text" and entry[2] == "/testbed/AGENTS.md":
                steps.append(("write_agents", None, None, entry))
            elif entry[0] == "exec":
                argv, kw = entry[2], entry[3]
                if tuple(argv) in pinned:
                    steps.append((pinned[tuple(argv)], kw["user"], kw["workdir"], entry))
                elif argv[:2] == ["sh", "-c"] and F.INSTALLER_FRAGMENT in argv[2]:
                    steps.append(("installer", kw["user"], kw["workdir"], entry))
        return steps

    def test_vo9_r19_the_harness_install_follows_the_pinned_commands_and_order(self):
        original = "# Project\n\n%s\n\nrest\n" % F.PLACEHOLDERS[1]
        run_dir = self.harness_run(agents_md=original, hooks_path=".githooks", precommit=True)
        name = self.name(run_dir, 1)
        steps = self.install_sequence(name)
        self.assertEqual(
            [s[0] for s in steps],
            ["mkdir", "copy_tar", "extract", "installer", "write_agents", "chown", "commit", "start_commit", "hooks",
             "precommit", "cleanup"],
        )
        users = {s[0]: (s[1], s[2]) for s in steps if s[1] is not None}
        for step in ("extract", "chown", "cleanup", "mkdir"):
            self.assertEqual(users[step][0], "root", step)
        for step in ("installer", "commit", "start_commit", "hooks", "precommit"):
            self.assertEqual(users[step], ("nonroot", "/testbed"), step)
        for step in ("extract", "chown", "cleanup"):
            self.assertEqual(users[step][1], "/testbed", step)
        written = [s[3] for s in steps if s[0] == "write_agents"][0]
        self.assertEqual(written[3], original.replace(F.PLACEHOLDERS[1], F.project_definition(self.rows[ROW_A]["repo"])))
        install = self.load(self.entry(run_dir, ROW_A, "harness") / "manifest.json")["install"]
        self.assertEqual(install, {"hooks_path": ".githooks", "pre_commit_config_present": True, "definition_replaced": True})
        self.assertEqual(self.load(self.entry(run_dir, ROW_A, "harness") / "prediction.json")["start_commit"], F.INSTALL_HEAD)
        self.assertEqual(self.entry_state(run_dir, arm="harness")["status"], "completed")

    def test_vo9_r19_head_changes_only_through_the_pinned_commit_command(self):
        run_dir = self.harness_run()
        name = self.name(run_dir, 1)
        revs = [e for e in self.docker.log if e[0] == "exec" and e[1] == name and e[2] == F.REV_PARSE_ARGV]
        self.assertEqual(len(revs), 1)
        commit_at = self.docker.exec_index(name, F.COMMIT_ARGV)
        self.assertIsNotNone(commit_at)
        self.assertLess(commit_at, self.docker.log.index(revs[0]))
        self.assertEqual(self.load(self.entry(run_dir, ROW_A, "harness") / "manifest.json")["start_commit"], F.INSTALL_HEAD)

    def test_vo9_r19_without_a_pre_commit_config_the_manifest_records_false(self):
        run_dir = self.harness_run(precommit=False)
        install = self.load(self.entry(run_dir, ROW_A, "harness") / "manifest.json")["install"]
        self.assertIs(install["pre_commit_config_present"], False)

    def test_vo9_r19_agents_md_without_a_placeholder_is_left_untouched(self):
        original = "# Project\n\nAlready has a real definition.\n"
        run_dir = self.harness_run(agents_md=original)
        name = self.name(run_dir, 1)
        steps = self.install_sequence(name)
        self.assertEqual(
            [s[0] for s in steps],
            ["mkdir", "copy_tar", "extract", "installer", "commit", "start_commit", "hooks", "precommit", "cleanup"],
        )
        self.assertEqual(
            [e for e in self.docker.log if e[0] == "write_text" and e[1] == name and e[2] == "/testbed/AGENTS.md"], []
        )
        self.assertEqual(self.docker.history[name].files["/testbed/AGENTS.md"], original.encode("utf-8"))
        install = self.load(self.entry(run_dir, ROW_A, "harness") / "manifest.json")["install"]
        self.assertIs(install["definition_replaced"], False)

    def test_vo9_r19_the_baseline_creates_the_output_directory_before_reading_the_start_commit(self):
        run_dir = self.go(arms=("baseline",))
        name = self.name(run_dir, 1)
        steps = self.install_sequence(name)
        self.assertEqual([s[0] for s in steps], ["mkdir", "start_commit"])
        self.assertEqual(steps[0][1], "root")
        self.assertEqual(steps[1][1:3], ("nonroot", "/testbed"))
        self.assertEqual(self.load(self.entry(run_dir, ROW_A, "baseline") / "manifest.json")["start_commit"], F.BASE_HEAD)


class EgressTests(unittest.TestCase):
    PROXY = "selfcheck-proxy-t"

    def setUp(self):
        self.docker = F.FakeDocker()
        self.cfg = F.cfg_copy(
            network="selfcheck-int-t", proxy_name=self.PROXY, proxy_image="example/squid@sha256:" + "d" * 64,
            allow_hosts=["api.anthropic.com", "example.org", "second.test"],
        )

    def ensure(self, cfg=None):
        run.ensure_egress(cfg or self.cfg, docker=self.docker)

    def proxy_starts(self):
        return [e for e in self.docker.log if e[0] == "start_proxy"]

    def proxy_removals(self):
        return [e for e in self.docker.log if e[0] in ("remove_container", "remove") and e[1] == self.PROXY]

    def first_label(self):
        self.ensure()
        (_, name, kwargs), = self.proxy_starts()
        return kwargs["labels"]["selfcheck.proxy"]

    def test_vo9_r17_an_absent_proxy_is_started_with_the_exact_arguments(self):
        self.ensure()
        self.assertIn(("ensure_network", "selfcheck-int-t", True), self.docker.log)
        (entry,) = self.proxy_starts()
        _, name, kwargs = entry
        self.assertEqual(name, self.PROXY)
        self.assertEqual(kwargs["image"], self.cfg["proxy_image"])
        self.assertEqual(kwargs["networks"], ["bridge", "selfcheck-int-t"])
        conf = kwargs["conf_text"]
        self.assertEqual(kwargs["labels"], {"selfcheck.proxy": hashlib.sha256(conf.encode("utf-8")).hexdigest()})
        for host in self.cfg["allow_hosts"]:
            self.assertIn(host, conf)
        log_kinds = [e[0] for e in self.docker.log]
        self.assertLess(log_kinds.index("ensure_network"), log_kinds.index("start_proxy"))
        self.assertTrue(self.docker.container_status(self.PROXY)["running"])

    def test_vo9_r17_a_running_proxy_with_the_matching_label_is_kept(self):
        sha = self.first_label()
        self.docker.log.clear()
        self.ensure()
        self.assertEqual(self.proxy_starts(), [])
        self.assertEqual(self.proxy_removals(), [])
        self.assertIn(("ensure_network", "selfcheck-int-t", True), self.docker.log)
        self.assertEqual(self.docker.container_status(self.PROXY)["labels"], {"selfcheck.proxy": sha})

    def test_vo9_r17_a_stopped_or_differently_labelled_proxy_is_removed_and_recreated(self):
        sha = self.first_label()
        cases = (
            ("stopped, matching label", {"selfcheck.proxy": sha}, False),
            ("running, other label", {"selfcheck.proxy": "0" * 64}, True),
            ("running, no label", {}, True),
            ("stopped, other label", {"selfcheck.proxy": "1" * 64}, False),
        )
        for name, labels, running in cases:
            with self.subTest(name):
                self.docker = F.FakeDocker()
                self.docker.preload(self.PROXY, labels, running=running)
                self.ensure()
                self.assertEqual(len(self.proxy_removals()), 1)
                (entry,) = self.proxy_starts()
                kinds = [e[0] for e in self.docker.log]
                removal_at = min(i for i, k in enumerate(kinds) if k in ("remove_container", "remove"))
                self.assertLess(removal_at, kinds.index("start_proxy"))
                kwargs = entry[2]
                self.assertEqual(kwargs["labels"], {"selfcheck.proxy": sha})
                self.assertEqual(
                    (entry[1], kwargs["image"], kwargs["networks"]),
                    (self.PROXY, self.cfg["proxy_image"], ["bridge", "selfcheck-int-t"]),
                )
                self.assertEqual(self.docker.container_status(self.PROXY), {"running": True, "labels": {"selfcheck.proxy": sha}})

    def test_vo9_r17_the_label_and_conf_follow_allow_hosts(self):
        sha = self.first_label()
        widened = dict(self.cfg, allow_hosts=self.cfg["allow_hosts"] + ["third.test"])
        self.docker.log.clear()
        self.ensure(widened)
        (entry,) = self.proxy_starts()
        kwargs = entry[2]
        self.assertIn("third.test", kwargs["conf_text"])
        self.assertNotEqual(kwargs["labels"]["selfcheck.proxy"], sha)
        self.assertEqual(kwargs["labels"]["selfcheck.proxy"], hashlib.sha256(kwargs["conf_text"].encode("utf-8")).hexdigest())
        self.assertEqual(len(self.proxy_removals()), 1)


if __name__ == "__main__":
    unittest.main()
