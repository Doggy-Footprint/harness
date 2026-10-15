"""Synthetic evidence builders for the M3 tests (spec 94b886658b88a7ef v1).

Every shape here is copied from the spec text or from the M2 test fakes. Nothing is derived from the
modules under test: expected verdicts are written next to the entries they belong to.
"""
import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from selfcheck.tests import agent_fakes as F

WF = "wf0123456789ab"
SPEC_SLUG = "feat"
SPEC_LOGS = "agent-docs/spec-logs"
SPECS = "agent-docs/specs"
SPEC_REL = "%s/%s-%s.md" % (SPECS, WF, SPEC_SLUG)
ARCHIVE_REL = "%s/%s-%s.md" % (SPEC_LOGS, WF, SPEC_SLUG)
IMPL = ["src/pkg/mod.py"]
TESTS = ["tests/test_x.py"]
IMPL_FILE = IMPL[0]
TEST_FILE = TESTS[0]

# Spec text, section "Fixture": EXEMPT.
EXEMPT = {
    "run_id", "instance_id", "arm", "selfcheck_commit", "harness_ref", "harness_commit", "start_commit",
    "install", "prompt_template_hash", "images",
}
CHECK_IDS = ["PC%d" % n for n in range(1, 13)]


def tb(path):
    return "/testbed/" + path


def ts(n):
    base = datetime(2026, 3, 1, tzinfo=timezone.utc)
    return (base + timedelta(seconds=n)).strftime("%Y-%m-%dT%H:%M:%SZ")


# ----------------------------------------------------------------------------------------------
# telemetry / ledger / diff
# ----------------------------------------------------------------------------------------------

def ev(n, event, *, run=WF, spec=SPEC_SLUG, **fields):
    row = {"v": 1, "ts": ts(n), "event": event, "workflow_run_id": run, "spec": spec}
    row.update(fields)
    return row


def E(event, **fields):
    return ev(0, event, **fields)


def reseq(events):
    out = []
    for i, e in enumerate(events, 1):
        e = dict(e)
        e["ts"] = ts(i)
        out.append(e)
    return out


def compliant_events():
    return [
        ev(1, "workflow_start"),
        ev(2, "workflow_phase", phase="implement_test"),
        ev(3, "workflow_phase", phase="verify"),
        ev(4, "verifier_result", result="pass"),
        ev(5, "verification_result", mutants=10, killed=9),
        ev(6, "seed", action="backup"),
        ev(7, "seed", action="restore"),
        ev(8, "workflow_end", status="complete"),
    ]


def L(agent_type, tool, **tool_input):
    return (agent_type, tool, tool_input)


def ledger_rows(items):
    rows = []
    for n, (agent_type, tool, tool_input) in enumerate(items):
        rows.append({
            "t": float(n), "session_id": "sess-1",
            "agent_id": None if agent_type is None else "ag-" + agent_type, "agent_type": agent_type,
            "tool_name": tool, "tool_use_id": "toolu_%d" % n, "tool_input": copy.deepcopy(tool_input),
        })
    return rows


def compliant_ledger_items():
    return [
        L(None, "Write", file_path=tb(SPEC_REL), content="spec"),
        L(None, "Agent", subagent_type="test-implementer", prompt="t"),
        L("test-implementer", "Write", file_path=tb(TEST_FILE), content="x"),
        L(None, "Agent", subagent_type="implementer", prompt="i"),
        L("implementer", "Edit", file_path=tb(IMPL_FILE), old_string="a", new_string="b"),
        L(None, "Agent", subagent_type="test-verifier", prompt="v"),
        L("test-verifier", "Read", file_path=tb(TEST_FILE)),
        L("test-verifier", "Bash", command="python -m unittest -q"),
    ]


def new_file_section(path, lines):
    return "diff --git a/%s b/%s\nnew file mode 100644\n--- /dev/null\n+++ b/%s\n@@ -0,0 +1,%d @@\n%s" % (
        path, path, path, len(lines), "".join("+%s\n" % line for line in lines),
    )


def spec_lines(status="complete", impl=IMPL, tests=TESTS, tail=()):
    return [
        "---", "version: 1", "run_id: %s" % WF, "status: %s" % status, "---", "",
        "# Paths", "Implementation: " + ", ".join(impl), "Tests: " + ", ".join(tests),
        "Test command: x", *tail,
    ]


def decoy_section():
    """A non-spec new file whose text looks like spec metadata: it must never be parsed."""
    return new_file_section("src/decoy.py", ["status: active", "Implementation: decoy_impl.py", "Tests: tests/decoy.py"])


def archived_diff(status="complete", where=SPEC_LOGS, name=None, **kw):
    path = name or "%s/%s-%s.md" % (where, WF, SPEC_SLUG)
    return decoy_section() + new_file_section(path, spec_lines(status, **kw))


# ----------------------------------------------------------------------------------------------
# entry directories
# ----------------------------------------------------------------------------------------------

def jsonl_text(rows):
    out = []
    for row in rows:
        out.append(row if isinstance(row, str) else json.dumps(row))
    return "\n".join(out) + ("\n" if out else "")


def write_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def score(iid="inst-1", *, resolved=True, swt=True, f2p=1.0, primary=0.5, secondary=0.25, incompat=0.0, sampled=18):
    return {
        "instance_id": iid, "resolved": resolved, "f2p_frac": f2p,
        "swt": {"applicable": True, "success": swt, "f2p": [], "x2f": []},
        "incompatible_frac": incompat,
        "kill": {"sampled": sampled, "killed": 1, "primary": primary, "secondary": secondary},
    }


def prediction(iid="inst-1", arm="harness", run_id="r1", *, seed_before="seed: none\n", **extra):
    row = {
        "instance_id": iid, "arm": arm, "run_id": run_id, "start_commit": "e" * 40, "tainted": False,
        "seed": {"before": seed_before, "after": "seed: none\n"}, "src_diff": "", "test_patch": "",
        "scratch_diff": "", "excluded_paths": [],
    }
    row.update(extra)
    return row


AUTO = object()


def write_entry(root, iid="inst-1", arm="harness", *, manifest=AUTO, events=AUTO, ledger=AUTO, diff=AUTO,
                prediction_=AUTO, state=None, raw_files=None):
    """Write an entry directory <root>/<iid>/<arm>. A value of None omits the file; AUTO is the compliant default.

    `events` is a list (one file `raw/telemetry/a.jsonl`) or {filename: list}; `ledger` is a list of
    (agent_type, tool, input) items or ready rows; list members that are str are written verbatim.
    """
    entry = Path(root) / iid / arm
    entry.mkdir(parents=True, exist_ok=True)
    if manifest is AUTO:
        manifest = {"instance_id": iid, "arm": arm}
    if manifest is not None:
        write_text(entry / "manifest.json", json.dumps(manifest))
    if events is AUTO:
        events = compliant_events()
    if events is not None:
        files = events if isinstance(events, dict) else {"a.jsonl": events}
        (entry / "raw" / "telemetry").mkdir(parents=True, exist_ok=True)
        for name, rows in files.items():
            write_text(entry / "raw" / "telemetry" / name, jsonl_text(rows))
    if ledger is AUTO:
        ledger = compliant_ledger_items()
    if ledger is not None:
        rows = []
        for n, item in enumerate(ledger):
            if isinstance(item, tuple):
                row = ledger_rows([item])[0]
                row["t"], row["tool_use_id"] = float(n), "toolu_%d" % n
                rows.append(row)
            else:
                rows.append(item)
        write_text(entry / "raw" / "ledger.jsonl", jsonl_text(rows))
    if diff is AUTO:
        diff = archived_diff()
    if diff is not None:
        write_text(entry / "raw" / "full.diff", diff)
    if prediction_ is AUTO:
        prediction_ = prediction(iid, arm)
    if prediction_ is not None:
        write_text(entry / "prediction.json", json.dumps(prediction_))
    if state is not None:
        write_text(entry / "state.json", json.dumps(state))
    for name, text in (raw_files or {}).items():
        write_text(entry / name, text)
    return entry


# ----------------------------------------------------------------------------------------------
# manifests, run directories, fixtures
# ----------------------------------------------------------------------------------------------

def images_for(iid):
    return {"tools": "selfcheck-tools:aaaaaaaaaaaa", "derived": "selfcheck-agent.arm64.%s:bbbbbbbbbbbb" % iid.lower()}


def manifest(iid="inst-1", arm="harness", run_id="r1", **over):
    base = {
        "run_id": run_id, "instance_id": iid, "arm": arm, "selfcheck_commit": "c" * 40,
        "harness_ref": "HEAD", "harness_commit": "d" * 40 if arm == "harness" else None,
        "start_commit": "e" * 40, "install": {"agents_md": "placeholder"},
        "model": "claude-opus-5-5", "effort": "low", "aliases": dict(F.SPEC_AGENT_CFG["aliases"]),
        "sdk": F.SPEC_AGENT_CFG["sdk"], "cli_version": "2.1.294", "tools": ["Bash", "Edit"],
        "disallowed_tools": list(F.SPEC_AGENT_CFG["disallowed_tools"]),
        "caps": {"wall_clock_min": 180, "max_user_turns": 8, "idle_grace_s": 120},
        "container": {"cpus": 4, "memory": "6g", "user": "nonroot"},
        "env_keys": sorted(F.SPEC_ENV_KEYS), "prompt_template_hash": "p" * 16, "user_sim_hash": "u" * 16,
        "images": images_for(iid), "network": "selfcheck-int",
    }
    base.update(over)
    return base


def conditions_of(m):
    return {k: v for k, v in m.items() if k not in EXEMPT}


def fixture_id_of(conds):
    text = json.dumps(conds, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def dirname(arm, repeat=None, mode=None):
    """Entry directory: <arm>[-informed][-r<k>] (spec 54ad633104783ebe R2)."""
    name = arm if mode in (None, "unassisted") else "%s-%s" % (arm, mode)
    return name if repeat is None else "%s-r%d" % (name, repeat)


def informed_manifest(iid="inst-1", run_id="r1", **over):
    """Informed harness manifest: user_mode key and a user_sim_hash over three files (R4)."""
    return manifest(iid, "harness", run_id, **dict({"user_mode": "informed", "user_sim_hash": "i" * 16}, **over))


def state(status="completed", *, results=None, elapsed_s=12.5, rate_limit=None, **over):
    st = F.driver_state_dict(status=status, results=results if results is not None else [], elapsed_s=elapsed_s,
                             rate_limit=rate_limit)
    st.update(over)
    return st


def write_run(runs_dir, run_id, entries, *, halted=None, created_at=0, params=None):
    """entries: dicts {instance_id, arm, status, repeat?, user_mode?, manifest?, state?, prediction?, extra?: kwargs for write_entry}.

    manifest/state/prediction default to None (file omitted) unless given. Returns the run directory.
    """
    run_dir = Path(runs_dir) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    listed = []
    for item in entries:
        iid, arm, status = item["instance_id"], item["arm"], item.get("status", "completed")
        repeat = item.get("repeat")
        mode = item.get("user_mode")
        listing = {"instance_id": iid, "arm": arm, "status": status}
        if mode is not None:
            listing["user_mode"] = mode
        if repeat is not None:
            listing["repeat"] = repeat
        listed.append(listing)
        kw = dict(item.get("extra", {}))
        kw.setdefault("events", None)
        kw.setdefault("ledger", None)
        kw.setdefault("diff", None)
        write_entry(run_dir, iid, dirname(arm, repeat, mode), manifest=item.get("manifest"), prediction_=item.get("prediction"),
                    state=item.get("state"), **kw)
    write_text(run_dir / "run.json", json.dumps({
        "run_id": run_id, "entries": listed, "created_at": created_at, "halted": halted,
    }))
    if params is not None:
        write_text(run_dir / "params.json", json.dumps(params))
    return run_dir


def write_fixture(root, manifests, *, scores=None, repeats=2, runs=("r1", "r2"), created_at=0):
    """A committed-looking fixture directory. `scores`: {iid: [score|None per repeat]}. Returns its path."""
    conds = conditions_of(manifests[0])
    fid = fixture_id_of(conds)
    directory = Path(root) / fid
    directory.mkdir(parents=True)
    instances = sorted({m["instance_id"] for m in manifests})
    images = {m["instance_id"]: m["images"] for m in manifests}
    write_text(directory / "manifest.json", json.dumps({
        "fixture_id": fid, "conditions": conds, "images": images, "runs": list(runs), "repeats": repeats,
        "instances": instances, "created_at": created_at,
    }))
    write_text(directory / "predictions.jsonl", "")
    table = {}
    for iid in instances:
        values = (scores or {}).get(iid, [None] * repeats)
        table[iid] = [
            {"repeat": k, "run_id": runs[k - 1] if k <= len(runs) else "r%d" % k,
             "status": "completed" if v is not None else "error", "score": v}
            for k, v in enumerate(values, 1)
        ]
    write_text(directory / "scores.json", json.dumps(table))
    return directory


def tree(root):
    """{relative path: bytes} of every file below root."""
    root = Path(root)
    if not root.exists():
        return {}
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}
