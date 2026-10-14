import hashlib
import json
import os
import re
import secrets
import shlex
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from selfcheck import docker_exec, images
from selfcheck import run as run_mod
from selfcheck.tests import agent_fakes as F
from selfcheck.tests.helpers import (
    PYTEST_ID, docker_only, make_shim, pilot, remove_image, require_image, wait_for_docker,
)

TEST_LABEL = "selfcheck.agenttest=1"
TESTBED_PY = "/opt/miniconda3/envs/testbed/bin/python"
IMPORT_NAMES = {"mutmut": "mutmut", "hypothesis": "hypothesis", "coverage": "coverage", "pytest-cov": "pytest_cov"}


def agent_cfg():
    return json.loads((F.ROOT / "selfcheck" / "config.json").read_text(encoding="utf-8"))["agent"]


def docker(*args, timeout=600, input=None):
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout, input=input)


def run_in(image, script, *, entrypoint="bash", user=None, network=None, timeout=300):
    args = ["run", "--rm", "--label", TEST_LABEL, "--entrypoint", entrypoint]
    if user:
        args += ["-u", user]
    if network:
        args += ["--network", network]
    args += [image, "-c", script]
    return docker(*args, timeout=timeout)


def normalise(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_freeze(text):
    parsed = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "==" in line:
            name, version = line.split("==", 1)
        elif " @ " in line:
            name, version = line.split(" @ ", 1)
        else:
            name, version = line, None
        parsed[normalise(name)] = version
    return parsed


def remove_container_named(name):
    docker("rm", "-f", name)


@docker_only
class DerivedImageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        wait_for_docker()
        cls.row = pilot(PYTEST_ID)
        cls.instance_image = require_image(cls.row)
        cls.cfg = agent_cfg()
        cls.tools = images.build_tools_image(cls.cfg)
        cls.derived = images.build_derived_image(cls.row, cls.cfg)

    def test_vo12_i1_second_build_returns_the_same_names_and_runs_no_docker_build(self):
        with tempfile.TemporaryDirectory() as directory:
            log = os.path.join(directory, "calls.log")
            make_shim(directory, 'echo "$*" >> "%s"\nexec @REAL@ "$@"\n' % log)
            with mock.patch.dict(os.environ, {"PATH": directory + os.pathsep + os.environ["PATH"]}):
                tools_again = images.build_tools_image(self.cfg)
                derived_again = images.build_derived_image(self.row, self.cfg)
            calls = Path(log).read_text(encoding="utf-8").splitlines() if os.path.exists(log) else []
        self.assertEqual(tools_again, self.tools)
        self.assertEqual(derived_again, self.derived)
        self.assertEqual(self.tools, images.tools_image_name(self.cfg))
        self.assertEqual(self.derived, images.derived_image_name(self.row, self.cfg))
        self.assertRegex(self.tools, r"^selfcheck-tools:[0-9a-f]{12}$")
        self.assertRegex(self.derived, r"^selfcheck-agent\.arm64\.pytest-dev__pytest-5787:[0-9a-f]{12}$")
        builds = [c for c in calls if c.split()[:1] in (["build"], ["buildx"]) or c.startswith("image build")]
        self.assertEqual(builds, [])

    def test_vo12_i2_shim_and_env_file_route_python3_by_script_location(self):
        script = r'''
EXPECT_TESTBED="$(%s --version 2>&1)"
source /opt/selfcheck/env.sh
mkdir -p /tmp/probe/.harness
cat > /tmp/probe/.harness/v.py <<'EOF'
import sys
print("v%%d.%%d" %% sys.version_info[:2])
EOF
echo "MODE=$(stat -c %%a /opt/selfcheck/bin/python3)"
echo "WHICH=$(command -v python3)"
echo "TESTBED=$EXPECT_TESTBED"
echo "SHIM=$(python3 --version 2>&1)"
echo "HARNESSPY=$(python3 /tmp/probe/.harness/v.py)"
echo "LANG=$LANG"
echo "LC_ALL=$LC_ALL"
echo "LANGUAGE=$LANGUAGE"
echo "PATH1=${PATH%%%%:*}"
''' % TESTBED_PY
        result = run_in(self.derived, script, user="nonroot")
        self.assertEqual(result.returncode, 0, result.stderr)
        values = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
        self.assertEqual(values["MODE"], "755")
        self.assertEqual(values["WHICH"], "/opt/selfcheck/bin/python3")
        self.assertFalse(values["TESTBED"].startswith("Python 3.12"), values["TESTBED"])
        self.assertEqual(values["SHIM"], values["TESTBED"])
        self.assertEqual(values["HARNESSPY"], "v3.12")
        self.assertEqual(values["LANG"], "en_US.UTF-8")
        self.assertEqual(values["LC_ALL"], "en_US.UTF-8")
        self.assertIn("en_US", values["LANGUAGE"])
        self.assertEqual(values["PATH1"], "/opt/selfcheck/bin")

    def test_vo12_i3_sdk_is_importable_by_the_python_312_venv(self):
        script = "import importlib.metadata as m, sys; print(m.version('claude-agent-sdk')); print('%d.%d' % sys.version_info[:2])"
        result = run_in(self.derived, script, entrypoint="/opt/selfcheck-py/venv/bin/python", user="nonroot")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.split(), [self.cfg["sdk"].split("==")[1], self.cfg["python"]])

    def test_vo12_i4_freeze_files_keep_every_preexisting_version_and_tools_import(self):
        result = run_in(
            self.derived,
            "cat /opt/selfcheck/freeze-before.txt; echo ====; cat /opt/selfcheck/freeze-after.txt; echo ====; "
            "%s -m pip list --format=freeze 2>/dev/null" % TESTBED_PY,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        before_text, after_text, live_text = result.stdout.split("====\n")
        before, after = parse_freeze(before_text), parse_freeze(after_text)
        self.assertTrue(before)
        changed_or_removed = {name: (version, after.get(name)) for name, version in before.items() if after.get(name) != version}
        self.assertEqual(changed_or_removed, {})
        self.assertEqual(parse_freeze(live_text), after)
        for item in self.cfg["testbed_tools"]:
            name = re.split(r"[=<>!~ ]", item, 1)[0]
            with self.subTest(tool=item):
                self.assertIn(normalise(name), after)
                if "==" in item:
                    self.assertEqual(after[normalise(name)], item.split("==", 1)[1])
        imports = ", ".join(IMPORT_NAMES[re.split(r"[=<>!~ ]", item, 1)[0]] for item in self.cfg["testbed_tools"])
        probe = run_in(self.derived, "%s -c 'import %s; print(\"ok\")'" % (TESTBED_PY, imports))
        self.assertEqual(probe.stdout.strip(), "ok", probe.stderr)

    def inspect_image(self, tag):
        result = docker("image", "inspect", tag)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)[0]

    def assert_inputs_label(self, tag, *, dockerfile_bytes, tools_name):
        info = self.inspect_image(tag)
        label = json.loads(info["Config"]["Labels"]["selfcheck.inputs"])
        self.assertEqual(
            set(label),
            {"dockerfile", "shim", "env", "tools_image_id", "instance_image_id", "testbed_tools"},
        )
        self.assertEqual(label["dockerfile"], hashlib.sha256(dockerfile_bytes).hexdigest())
        self.assertEqual(label["shim"], hashlib.sha256(Path(images.SHIM).read_bytes()).hexdigest())
        self.assertEqual(label["env"], hashlib.sha256(Path(images.ENV_FILE).read_bytes()).hexdigest())
        for key, image in (("tools_image_id", tools_name), ("instance_image_id", self.instance_image)):
            real = self.inspect_image(image)["Id"]
            self.assertIn(label[key], (real, real.removeprefix("sha256:")), key)
        self.assertEqual(label["testbed_tools"], self.cfg["testbed_tools"])

    def test_vo12_i4_freeze_before_equals_pip_list_run_in_the_instance_image_itself(self):
        recorded = run_in(self.derived, "cat /opt/selfcheck/freeze-before.txt")
        oracle = run_in(
            self.instance_image, "%s -m pip list --format=freeze 2>/dev/null" % TESTBED_PY, network="none"
        )
        self.assertEqual(recorded.returncode, 0, recorded.stderr)
        self.assertEqual(oracle.returncode, 0, oracle.stderr)
        self.assertTrue(oracle.stdout.strip())
        self.assertEqual(recorded.stdout.rstrip("\n"), oracle.stdout.rstrip("\n"))

    def test_vo12_i7_the_inputs_label_holds_the_documented_keys_real_image_ids_and_the_configured_tools(self):
        self.assert_inputs_label(
            self.derived, dockerfile_bytes=Path(images.DERIVED_DOCKERFILE).read_bytes(), tools_name=self.tools
        )

    def test_vo12_i8_uv_and_uvx_are_absent_while_the_tools_python_exists(self):
        script = r'''
for name in uv uvx; do
  command -v "$name" >/dev/null 2>&1 && echo "ON-PATH=$name"
done
echo "FOUND=$(find /usr /opt /bin /sbin /root /home /srv -xdev -type f \( -name uv -o -name uvx \) 2>/dev/null | tr '\n' ',')"
test -x /opt/selfcheck-py/venv/bin/python && echo "PYTHON=present"
'''
        result = run_in(self.derived, script, user="root")
        self.assertEqual(result.returncode, 0, result.stderr)
        values = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
        self.assertNotIn("ON-PATH", values, result.stdout)
        self.assertEqual(values["FOUND"], "")
        self.assertEqual(values["PYTHON"], "present")

    def replaced_derived_dockerfile(self, body):
        directory = tempfile.mkdtemp(prefix="derivedreplaced-")
        self.addCleanup(shutil.rmtree, directory, True)
        path = Path(directory) / "derived.Dockerfile"
        path.write_text("# %s\n%s" % (secrets.token_hex(8), body), encoding="utf-8")
        patcher = mock.patch.object(images, "DERIVED_DOCKERFILE", path)
        patcher.start()
        self.addCleanup(patcher.stop)
        return path

    def test_vo12_i9_a_failing_build_raises_with_exactly_the_last_forty_lines_and_leaves_no_image(self):
        self.replaced_derived_dockerfile(
            "ARG TOOLS\nARG BASE\nFROM ${BASE}\n"
            "RUN i=1; while [ $i -le 50 ]; do echo \"LINE-$i\"; i=$((i+1)); done; exit 1\n"
        )
        name = images.derived_image_name(self.row, self.cfg)
        self.addCleanup(remove_image, name)
        shim_dir = tempfile.mkdtemp(prefix="buildshim-")
        self.addCleanup(shutil.rmtree, shim_dir, True)
        log = os.path.join(shim_dir, "build.log")
        make_shim(shim_dir, (
            'if [ "$1" = build ] || [ "$1" = buildx ] || { [ "$1" = image ] && [ "$2" = build ]; }; then\n'
            '  out="$(mktemp)"\n'
            '  @REAL@ "$@" >"$out" 2>&1\n'
            '  rc=$?\n'
            '  cat "$out" >> "@LOG@"\n'
            '  cat "$out"\n'
            '  rm -f "$out"\n'
            '  exit $rc\n'
            'fi\n'
            'exec @REAL@ "$@"\n'
        ).replace("@LOG@", log))
        with mock.patch.dict(os.environ, {"PATH": shim_dir + os.pathsep + os.environ["PATH"]}):
            with self.assertRaises(images.ImageBuildError) as caught:
                images.build_derived_image(self.row, self.cfg)
        captured = Path(log).read_text(encoding="utf-8", errors="replace")
        lines = captured.splitlines()
        self.assertIn("LINE-50", captured)
        self.assertGreaterEqual(len(lines), 41)
        message = str(caught.exception)
        self.assertIn(name, message)
        self.assertIn("\n".join(lines[-40:]), message)
        self.assertNotIn("\n".join(lines[-41:]), message)
        self.assertNotEqual(docker("image", "inspect", name).returncode, 0, "a failed build must leave no image")

    def test_vo12_i10_a_minimal_replaced_dockerfile_builds_an_image_with_the_shim_env_tools_name_and_base(self):
        path = self.replaced_derived_dockerfile(
            "ARG TOOLS\nARG BASE\nFROM ${BASE}\nARG TOOLS\n"
            "COPY python3 env.sh /probe/\n"
            "RUN mkdir -p /probe && echo \"${TOOLS}\" > /probe/tools\n"
        )
        name = images.derived_image_name(self.row, self.cfg)
        self.addCleanup(remove_image, name)
        built = images.build_derived_image(self.row, self.cfg)
        self.assertEqual(built, name)

        def cat(file):
            return subprocess.run(
                ["docker", "run", "--rm", "--entrypoint", "cat", name, file], capture_output=True, timeout=300
            )

        for file, source in (("/probe/python3", images.SHIM), ("/probe/env.sh", images.ENV_FILE)):
            with self.subTest(file):
                result = cat(file)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, Path(source).read_bytes())
        written = cat("/probe/tools")
        self.assertEqual(written.stdout.decode("utf-8"), self.tools + "\n")
        base_layers = json.loads(docker("image", "inspect", "--format", "{{json .RootFS.Layers}}", self.instance_image).stdout)
        built_layers = json.loads(docker("image", "inspect", "--format", "{{json .RootFS.Layers}}", name).stdout)
        self.assertEqual(built_layers[:len(base_layers)], base_layers)
        self.assertGreater(len(built_layers), len(base_layers))
        self.assert_inputs_label(name, dockerfile_bytes=path.read_bytes(), tools_name=self.tools)

    def test_vo12_i5_testbed_ownership_safe_directory_and_locale(self):
        script = r'''
echo "OWNER=$(stat -c %u:%g /testbed)"
echo "FOREIGN=$(find /testbed ! -uid 1000 -print -quit)"
echo "SAFE=$(git config --system --get-all safe.directory | tr '\n' ',')"
echo "UID=$(id -u nonroot)"
echo "LOCALES=$(locale -a | tr '\n' ',')"
'''
        result = run_in(self.derived, script, user="root")
        self.assertEqual(result.returncode, 0, result.stderr)
        values = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
        self.assertEqual(values["OWNER"], "1000:1000")
        self.assertEqual(values["FOREIGN"], "")
        self.assertIn("/testbed", values["SAFE"].split(","))
        self.assertEqual(values["UID"], "1000")
        self.assertIn("en_us.utf8", values["LOCALES"].lower().split(","))

    def test_vo12_i6_derived_image_adds_at_most_one_and_a_half_gigabytes(self):
        sizes = []
        for tag in (self.derived, self.instance_image):
            inspected = docker("image", "inspect", "--format", "{{.Size}}", tag)
            self.assertEqual(inspected.returncode, 0, inspected.stderr)
            sizes.append(int(inspected.stdout.strip()))
        self.assertLessEqual(sizes[0] - sizes[1], 1.5 * 10**9)


PROBE = r'''
import http.client, socket, sys
mode, host, proxy = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    if mode == "direct":
        socket.create_connection((host, 443), timeout=8).close()
    else:
        conn = http.client.HTTPConnection(proxy, 3128, timeout=20)
        conn.set_tunnel(host, 443)
        conn.connect()
        conn.close()
    print("OK")
except OSError as exc:
    print("ERR", exc)
'''


@docker_only
class EgressAndContainerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        wait_for_docker()
        cls.row = pilot(PYTEST_ID)
        require_image(cls.row)
        cls.cfg = agent_cfg()
        cls.derived = images.build_derived_image(cls.row, cls.cfg)
        run_mod.ensure_egress(cls.cfg)

    def probe(self, mode, host):
        result = docker(
            "run", "--rm", "--label", TEST_LABEL, "--network", self.cfg["network"], "--entrypoint",
            "/opt/selfcheck-py/venv/bin/python", self.derived, "-c", PROBE, mode, host, self.cfg["proxy_name"],
        )
        return result.stdout.strip()

    def inspect(self, name):
        result = docker("inspect", name)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)[0]

    def test_vo13_n1_direct_connection_to_github_fails_on_the_internal_network(self):
        network = docker("network", "inspect", "--format", "{{.Internal}}", self.cfg["network"])
        self.assertEqual(network.stdout.strip(), "true")
        proxy = self.inspect(self.cfg["proxy_name"])
        self.assertTrue({"bridge", self.cfg["network"]} <= set(proxy["NetworkSettings"]["Networks"]))
        self.assertTrue(self.probe("direct", "github.com").startswith("ERR"))

    def test_vo13_n2_proxy_denies_github_and_pypi_with_403(self):
        for host in ("github.com", "pypi.org"):
            with self.subTest(host=host):
                outcome = self.probe("proxy", host)
                self.assertTrue(outcome.startswith("ERR"), outcome)
                self.assertIn("403", outcome)

    def test_vo13_n3_proxy_allows_the_connect_to_api_anthropic_com(self):
        self.assertEqual(self.probe("proxy", "api.anthropic.com"), "OK")

    def test_vo13_n4_changed_allow_hosts_recreates_the_proxy(self):
        name = self.cfg["proxy_name"]
        label = lambda: self.inspect(name)["Config"]["Labels"]["selfcheck.proxy"]
        identity = lambda: self.inspect(name)["Id"]
        self.addCleanup(run_mod.ensure_egress, self.cfg)
        run_mod.ensure_egress(self.cfg)
        first_id, first_label = identity(), label()
        run_mod.ensure_egress(self.cfg)
        self.assertEqual(identity(), first_id)
        widened = dict(self.cfg, allow_hosts=list(self.cfg["allow_hosts"]) + ["example.org"])
        run_mod.ensure_egress(widened)
        self.assertNotEqual(identity(), first_id)
        self.assertNotEqual(label(), first_label)
        self.assertEqual(self.probe("proxy", "example.org"), "OK")
        run_mod.ensure_egress(self.cfg)
        self.assertEqual(label(), first_label)
        self.assertIn("403", self.probe("proxy", "example.org"))

    def test_vo13_n8_a_second_ensure_egress_with_unchanged_cfg_keeps_the_same_proxy_container(self):
        self.addCleanup(run_mod.ensure_egress, self.cfg)
        name = self.cfg["proxy_name"]
        run_mod.ensure_egress(self.cfg)
        first = self.inspect(name)
        run_mod.ensure_egress(self.cfg)
        run_mod.ensure_egress(self.cfg)
        second = self.inspect(name)
        self.assertEqual(second["Id"], first["Id"])
        self.assertIs(second["State"]["Running"], True)
        self.assertEqual(second["Config"]["Labels"]["selfcheck.proxy"], first["Config"]["Labels"]["selfcheck.proxy"])

    def start_agent_container(self):
        suffix = secrets.token_hex(6)
        name = "selfcheck-agent-test-%s-1" % suffix
        self.addCleanup(remove_container_named, name)
        token = F.dummy_token()
        token_dir = tempfile.mkdtemp(prefix="agenttest-")
        self.addCleanup(shutil.rmtree, token_dir, True)
        token_path = Path(token_dir) / "oauth_token"
        token_path.write_text(token + "\n", encoding="utf-8")
        token_path.chmod(0o600)
        shim_dir = tempfile.mkdtemp(prefix="agentshim-")
        self.addCleanup(shutil.rmtree, shim_dir, True)
        log = os.path.join(shim_dir, "calls.log")
        make_shim(shim_dir, 'echo "$*" >> "%s"\nexec @REAL@ "$@"\n' % log)
        mount = "type=bind,src=%s,dst=/run/secrets/oauth_token,readonly" % token_path
        with mock.patch.dict(os.environ, {"PATH": shim_dir + os.pathsep + os.environ["PATH"]}):
            container = docker_exec.start_container(
                self.derived, name=name, network=self.cfg["network"], labels={"selfcheck.agent": "test-" + suffix},
                cpus=self.cfg["cpus"], memory=self.cfg["memory"], mounts=[mount],
            )
        runs = [l for l in Path(log).read_text(encoding="utf-8").splitlines() if l.startswith("run ")]
        return container, name, token, mount, runs, suffix

    def test_vo13_n5_started_container_has_exactly_one_read_only_token_bind_mount(self):
        container, name, token, mount, runs, suffix = self.start_agent_container()
        info = self.inspect(name)
        self.assertEqual(len(info["Mounts"]), 1)
        mounted = info["Mounts"][0]
        self.assertEqual(mounted["Type"], "bind")
        self.assertEqual(mounted["Destination"], "/run/secrets/oauth_token")
        self.assertIs(mounted["RW"], False)
        self.assertTrue(mounted["Source"].endswith("/oauth_token"))
        write = docker("exec", "-u", "root", name, "sh", "-c", "echo x >> /run/secrets/oauth_token")
        self.assertNotEqual(write.returncode, 0)
        self.assertEqual(info["HostConfig"]["NetworkMode"], self.cfg["network"])
        self.assertEqual(info["Config"]["Labels"]["selfcheck.agent"], "test-" + suffix)

    def test_vo13_n6_token_value_is_absent_from_inspect_config_and_the_docker_run_argv(self):
        container, name, token, mount, runs, suffix = self.start_agent_container()
        info = self.inspect(name)
        config = {key: info["Config"].get(key) for key in ("Env", "Cmd", "Entrypoint")}
        config["Args"] = info.get("Args")
        self.assertEqual(json.dumps(config).count(token), 0)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].count(token), 0)
        tokens = shlex.split(runs[0])
        self.assertNotIn("-e", tokens)
        self.assertFalse([t for t in tokens if t.startswith("--env")])
        for flag, value in (("--name", name), ("--network", self.cfg["network"]), ("--cpus", str(self.cfg["cpus"])),
                            ("--memory", self.cfg["memory"]), ("--mount", mount), ("--pull", "never"),
                            ("--label", "selfcheck.agent=test-" + suffix), ("--entrypoint", "sleep")):
            with self.subTest(flag=flag):
                self.assertIn(value, [tokens[i + 1] for i, t in enumerate(tokens[:-1]) if t == flag])
        self.assertEqual(tokens[-2:], [self.derived, "infinity"])

    def test_vo13_n7_a_nonroot_exec_reads_the_token_file_as_uid_1000(self):
        container, name, token, mount, runs, suffix = self.start_agent_container()
        code, output, timed_out = container.exec(["cat", "/run/secrets/oauth_token"], user="nonroot", timeout=60)
        self.assertEqual((code, timed_out), (0, False))
        self.assertEqual(output.strip(), token)
        code, output, _ = container.exec(["id", "-u"], user="nonroot", timeout=60)
        self.assertEqual((code, output.strip()), (0, "1000"))


class InterceptedContainer:
    """Real container whose driver exec (and optionally the installer) is replaced."""

    def __init__(self, inner, owner):
        self.inner = inner
        self.owner = owner

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def exec(self, argv, *, timeout=None, user=None, workdir=None):
        argv = list(argv)
        if argv == F.DRIVER_ARGV:
            return self.owner.on_driver(self.inner)
        if self.owner.break_installer and argv[:2] == ["sh", "-c"] and F.INSTALLER_FRAGMENT in argv[2]:
            return self.inner.exec(
                ["sh", "-c", "echo INSTALLER_BROKEN >&2; exit 3"], timeout=timeout, user=user, workdir=workdir
            )
        return self.inner.exec(argv, timeout=timeout, user=user, workdir=workdir)

    def remove(self):
        self.owner.before_remove(self.inner)
        return self.inner.remove()


class InterceptingDocker:
    def __init__(self, on_driver=None, break_installer=False):
        self._on_driver = on_driver
        self.break_installer = break_installer
        self.driver_calls = 0
        self.process_snapshots = []
        self.names = []

    def __getattr__(self, name):
        return getattr(docker_exec, name)

    def start_container(self, *args, **kwargs):
        container = docker_exec.start_container(*args, **kwargs)
        self.names.append(kwargs["name"])
        return InterceptedContainer(container, self)

    def Container(self, cid):
        return InterceptedContainer(docker_exec.Container(cid), self)

    def remove_container(self, name):
        self.before_remove(docker_exec.Container(name))
        docker_exec.remove_container(name)

    def on_driver(self, inner):
        self.driver_calls += 1
        return self._on_driver(inner)

    def before_remove(self, inner):
        self.process_snapshots.append(inner.processes())


WORKTREE = {"user": "nonroot", "workdir": "/testbed", "timeout": 300}

PLANT = r'''set -e
cd /testbed
printf '\n# planted src edit\n' >> src/_pytest/reports.py
printf '\n# planted test edit\n' >> testing/test_reports.py
printf 'x = 1\n' > src/_pytest/planted_new.py
printf 'print(1)\n' > scratch_notes.py
printf 'planted\n' > .harness/planted.txt
printf 'planted\n' >> AGENTS.md
mkdir -p .hypothesis mutants
printf 'p\n' > .hypothesis/planted
printf 'm = 1\n' > mutants/planted.py
/opt/selfcheck-py/venv/bin/python .harness/bin/seed.py backup src/_pytest/skipping.py
printf '\n# SEEDED_DEFECT_MARK\n' >> src/_pytest/skipping.py
setsid nohup sh -c 'sleep 600; echo mutmut' >/dev/null 2>&1 < /dev/null &
sleep 1
'''


def real_run(testcase, arms, intercepting, *, cap_min=1):
    row = pilot(PYTEST_ID)
    tmp = tempfile.mkdtemp(prefix="agentrun-")
    testcase.addClassCleanup(shutil.rmtree, tmp, True)
    token_path, token = F.write_token_file(tmp)
    cfg = agent_cfg()
    cfg["runs_dir"] = str(Path(tmp) / "runs")
    cfg["token_file"] = token_path
    docker_exec.ensure_network(cfg["network"], internal=True)
    with mock.patch.object(run_mod, "ensure_egress", lambda *a, **k: None):
        run_dir = run_mod.run([row], list(arms), cfg=cfg, docker=intercepting, cap_min=cap_min)
    for name in intercepting.names:
        testcase.addClassCleanup(remove_container_named, name)
    return run_dir, token


def exec_out(container, *argv):
    code, output, timed_out = container.exec(list(argv), user="nonroot", workdir="/testbed", timeout=120)
    return code, output


@docker_only
class HarnessInstallAndExtractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        wait_for_docker()
        cls.row = pilot(PYTEST_ID)
        cls.instance_image = require_image(cls.row)
        cls.cfg = agent_cfg()
        images.build_tools_image(cls.cfg)
        images.build_derived_image(cls.row, cls.cfg)
        cls.snapshot = {}

        def on_driver(container):
            snap = cls.snapshot
            snap["head"] = exec_out(container, "git", "log", "-1", "--format=%H")[1].strip()
            snap["subject"] = exec_out(container, "git", "log", "-1", "--format=%s")[1].strip()
            snap["status"] = exec_out(container, "git", "status", "--porcelain")[1]
            snap["tracked_harness"] = exec_out(container, "git", "ls-files", ".harness")[1].split()
            snap["tracked_claude"] = exec_out(container, "git", "ls-files", ".claude")[1].split()
            code, out = exec_out(container, "git", "config", "--get", "core.hooksPath")
            snap["hooks_path"] = out.strip() if code == 0 else None
            snap["precommit"] = exec_out(container, "test", "-f", ".pre-commit-config.yaml")[0] == 0
            snap["agents_md"] = exec_out(container, "cat", "AGENTS.md")[1]
            snap["harness_src_present"] = exec_out(container, "test", "-e", "/opt/harness-src")[0] == 0
            snap["h6"] = {
                "out_owner": exec_out(container, "stat", "-c", "%u", "/selfcheck/out")[1].strip(),
                "out_writable": exec_out(
                    container, "sh", "-c", "touch /selfcheck/out/.h6-probe && rm /selfcheck/out/.h6-probe"
                )[0],
                "readable": {
                    path: exec_out(container, "sh", "-c", "cat %s > /dev/null" % path)[0]
                    for path in (
                        "/selfcheck/in/input.json", "/opt/selfcheck/agent/driver.py", "/opt/selfcheck/agent/user_sim.py",
                    )
                },
                "agents_owner": exec_out(container, "stat", "-c", "%u", "/testbed/AGENTS.md")[1].strip(),
            }
            code, out = exec_out(container, "sh", "-c", PLANT)
            snap["plant"] = (code, out)
            container.write_text("/selfcheck/out/state.json", json.dumps(F.driver_state_dict()))
            return 0, "", False

        cls.intercepting = InterceptingDocker(on_driver)
        cls.run_dir, cls.token = real_run(cls, ("harness",), cls.intercepting)
        cls.entry = cls.run_dir / cls.row["instance_id"] / "harness"
        cls.manifest = json.loads((cls.entry / "manifest.json").read_text(encoding="utf-8"))
        cls.prediction = json.loads((cls.entry / "prediction.json").read_text(encoding="utf-8"))
        cls.state = json.loads((cls.entry / "state.json").read_text(encoding="utf-8"))

    def test_vo14_h1_install_commit_is_head_and_harness_files_are_committed(self):
        snap = self.snapshot
        self.assertEqual(snap["plant"][0], 0, snap["plant"][1])
        self.assertEqual(snap["subject"], "selfcheck: install harness")
        self.assertEqual(snap["head"], self.manifest["start_commit"])
        self.assertEqual(self.prediction["start_commit"], snap["head"])
        self.assertEqual(snap["status"], "")
        self.assertIn(".harness/bin/seed.py", snap["tracked_harness"])
        self.assertTrue(snap["tracked_claude"])

    def test_vo14_h2_agents_md_placeholder_is_replaced_by_the_project_definition(self):
        definition = F.project_definition(self.row["repo"])
        agents = self.snapshot["agents_md"]
        for placeholder in F.PLACEHOLDERS:
            self.assertNotIn(placeholder, agents)
        self.assertIn(definition, agents)

    def test_vo14_h3_hooks_path_and_pre_commit_presence_are_recorded(self):
        install = self.manifest["install"]
        self.assertEqual(set(install), {"hooks_path", "pre_commit_config_present", "definition_replaced"})
        self.assertEqual(install["hooks_path"] or None, self.snapshot["hooks_path"])
        self.assertIs(install["pre_commit_config_present"], self.snapshot["precommit"])
        self.assertIs(install["definition_replaced"], True)

    def test_vo14_h4_harness_source_is_removed_after_the_install(self):
        self.assertIs(self.snapshot["harness_src_present"], False)

    def test_vo14_h6_the_driver_exec_user_owns_the_output_directory_and_reads_its_inputs(self):
        h6 = self.snapshot["h6"]
        self.assertEqual(h6["out_owner"], "1000")
        self.assertEqual(h6["out_writable"], 0)
        self.assertEqual(h6["readable"], {
            "/selfcheck/in/input.json": 0, "/opt/selfcheck/agent/driver.py": 0, "/opt/selfcheck/agent/user_sim.py": 0,
        })
        self.assertEqual(h6["agents_owner"], "1000")

    def test_vo15_x1_planted_edits_are_split_as_expected_and_apply_to_a_fresh_instance_container(self):
        prediction = self.prediction
        files = lambda text: sorted(path for path, _ in F.diff_sections(text))
        self.assertEqual(files(prediction["src_diff"]), ["src/_pytest/planted_new.py", "src/_pytest/reports.py"])
        self.assertEqual(files(prediction["test_patch"]), ["testing/test_reports.py"])
        self.assertEqual(files(prediction["scratch_diff"]), ["scratch_notes.py"])
        planted = {".harness/planted.txt", "AGENTS.md", "mutants/planted.py"}
        # .hypothesis is ignored by the pilot repository's .gitignore, so git add -A never stages it.
        everything = prediction["src_diff"] + prediction["test_patch"] + prediction["scratch_diff"]
        self.assertNotIn(".hypothesis/planted", prediction["excluded_paths"])
        self.assertNotIn(".hypothesis/planted", files(everything))
        self.assertLessEqual(planted, set(prediction["excluded_paths"]))
        for path in prediction["excluded_paths"]:
            self.assertNotIn(path, files(prediction["src_diff"] + prediction["test_patch"]))
        patch = prediction["src_diff"] + prediction["test_patch"]
        name = "selfcheck-agenttest-%s" % secrets.token_hex(6)
        started = docker("run", "-d", "--name", name, "--label", TEST_LABEL, "--entrypoint", "sleep", self.instance_image, "infinity")
        self.addCleanup(remove_container_named, name)
        self.assertEqual(started.returncode, 0, started.stderr)
        with tempfile.TemporaryDirectory() as directory:
            patch_file = Path(directory) / "pred.diff"
            patch_file.write_bytes(patch.encode("utf-8"))
            copied = docker("cp", str(patch_file), "%s:/tmp/pred.diff" % name)
            self.assertEqual(copied.returncode, 0, copied.stderr)
        checked = docker("exec", name, "sh", "-c", "cd /testbed && git -c safe.directory=/testbed apply --check /tmp/pred.diff")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)

    def test_vo15_x2_pending_seed_backup_is_restored_before_the_diff(self):
        seed = self.prediction["seed"]
        self.assertIs(seed["ok"], True)
        self.assertIs(seed["restored"], True)
        everything = self.prediction["src_diff"] + self.prediction["test_patch"] + self.prediction["scratch_diff"]
        self.assertNotIn("SEEDED_DEFECT_MARK", everything)
        self.assertNotIn("src/_pytest/skipping.py", [p for p, _ in F.diff_sections(everything)])

    def test_vo15_x3_running_mutmut_process_taints_the_prediction_and_is_killed(self):
        self.assertIs(self.prediction["tainted"], True)
        last = self.intercepting.process_snapshots[-1]
        self.assertEqual([p for p in last if "mutmut" in p["cmd"]], [])

    def test_vo15_x4_no_nonroot_process_and_no_agent_container_remain_after_completion(self):
        last = self.intercepting.process_snapshots[-1]
        self.assertEqual([p for p in last if p["uid"] == 1000], [])
        self.assertEqual(self.state["status"], "completed")
        listed = docker("ps", "-a", "-q", "--filter", "label=selfcheck.agent=%s" % self.run_dir.name)
        self.assertEqual(listed.stdout.split(), [])

    def test_vo15_x4_the_token_value_appears_nowhere_in_the_run_directory(self):
        needle = self.token.encode()
        hits = [p for p in self.run_dir.rglob("*") if p.is_file() and needle in p.read_bytes()]
        self.assertEqual(hits, [])


@docker_only
class FailingInstallerTests(unittest.TestCase):
    def test_vo14_h5_a_failing_installer_ends_in_error_with_install_log_and_no_container(self):
        wait_for_docker()
        row = pilot(PYTEST_ID)
        require_image(row)
        cfg = agent_cfg()
        images.build_tools_image(cfg)
        images.build_derived_image(row, cfg)
        intercepting = InterceptingDocker(lambda container: (0, "", False), break_installer=True)
        run_dir, _ = real_run(self, ("harness",), intercepting)
        entry = run_dir / row["instance_id"] / "harness"
        state = json.loads((entry / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "error")
        self.assertEqual(state["reason"], "install failed: exit 3")
        self.assertIn("INSTALLER_BROKEN", (entry / "raw" / "install.log").read_text(encoding="utf-8"))
        self.assertEqual(intercepting.driver_calls, 0)
        listed = docker("ps", "-a", "-q", "--filter", "label=selfcheck.agent=%s" % run_dir.name)
        self.assertEqual(listed.stdout.split(), [])


if __name__ == "__main__":
    unittest.main()
