import hashlib
import json
import time
from pathlib import Path

EXEMPT = {
    "run_id", "instance_id", "arm", "selfcheck_commit", "harness_ref", "harness_commit",
    "start_commit", "install", "prompt_template_hash", "images",
}


class FixtureError(Exception):
    pass


def conditions(manifest: dict) -> dict:
    return {k: v for k, v in manifest.items() if k not in EXEMPT}


def fixture_id(conds: dict) -> str:
    text = json.dumps(conds, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _read_json(path: Path):
    return json.loads(path.read_text()) if path.is_file() else None


def _differing(a: dict, b: dict) -> list[str]:
    return sorted(k for k in a.keys() | b.keys() if a.get(k) != b.get(k))


def assemble(run_dirs: list[Path], *, score_fn, out_root: Path, token: str, now=time.time) -> Path:
    rows = []
    for repeat, run_dir in enumerate(run_dirs, start=1):
        run_dir = Path(run_dir)
        meta = _read_json(run_dir / "run.json")
        for entry in meta["entries"]:
            if entry["arm"] != "baseline":
                continue
            d = run_dir / entry["instance_id"] / "baseline"
            state = _read_json(d / "state.json") or {}
            rows.append({
                "repeat": repeat, "run_id": meta["run_id"], "iid": entry["instance_id"],
                "status": state.get("status") or entry["status"],
                "manifest": _read_json(d / "manifest.json"),
                "prediction": _read_json(d / "prediction.json"),
            })
    manifests = [r["manifest"] for r in rows if r["manifest"] is not None]
    if not manifests:
        raise FixtureError("no baseline manifests found")
    base = conditions(manifests[0])
    differing = sorted({k for m in manifests[1:] for k in _differing(base, conditions(m))})
    if differing:
        raise FixtureError(f"baseline conditions differ in: {', '.join(differing)}")
    images: dict[str, dict] = {}
    for r in rows:
        if r["manifest"] is None:
            continue
        seen = images.setdefault(r["iid"], r["manifest"]["images"])
        if seen != r["manifest"]["images"]:
            raise FixtureError(f"images differ across repeats for {r['iid']}")

    fid = fixture_id(base)
    target = Path(out_root) / fid
    if target.exists():
        raise FixtureError(f"fixture already exists: {target}")

    rows.sort(key=lambda r: (r["iid"], r["repeat"]))
    scores: dict[str, list[dict]] = {}
    predictions = []
    for r in rows:
        score = score_fn(r["prediction"]) if r["prediction"] is not None else None
        if r["prediction"] is not None:
            predictions.append({**r["prediction"], "repeat": r["repeat"]})
        scores.setdefault(r["iid"], []).append(
            {"repeat": r["repeat"], "run_id": r["run_id"], "status": r["status"], "score": score}
        )
    manifest = {
        "fixture_id": fid,
        "conditions": base,
        "images": images,
        "runs": [_read_json(Path(d) / "run.json")["run_id"] for d in run_dirs],
        "repeats": len(run_dirs),
        "instances": sorted({r["iid"] for r in rows}),
        "created_at": now(),
    }
    outputs = {
        "manifest.json": json.dumps(manifest, indent=1, sort_keys=True),
        "predictions.jsonl": "".join(json.dumps(p, sort_keys=True) + "\n" for p in predictions),
        "scores.json": json.dumps(scores, indent=1, sort_keys=True),
    }
    if token and any(token in text for text in outputs.values()):
        raise FixtureError("token found in fixture output; nothing written")
    target.mkdir(parents=True)
    for name, text in outputs.items():
        (target / name).write_text(text)
    return target


def _save_progress(path: Path, progress: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(progress, indent=1))


def create(
    instances: list[dict], *, repeats: int, cfg: dict, progress_path: Path,
    run_fn, resume_fn, assemble_fn,
) -> tuple[str, str]:
    progress_path = Path(progress_path)
    ids = [i["instance_id"] for i in instances]
    progress = _read_json(progress_path)
    if progress is None:
        progress = {"instances": ids, "repeats": repeats, "run_ids": []}
        _save_progress(progress_path, progress)
    elif progress.get("instances") != ids or progress.get("repeats") != repeats:
        raise FixtureError(
            f"progress file {progress_path} was created with different instances or repeats; "
            "delete it to start over"
        )
    runs_dir = Path(cfg["runs_dir"]).expanduser()

    def halted(run_id: str):
        return _read_json(runs_dir / run_id / "run.json").get("halted")

    for run_id in progress["run_ids"]:
        meta = _read_json(runs_dir / run_id / "run.json")
        unfinished = any(e["status"] in ("pending", "interrupted") for e in meta["entries"])
        if meta.get("halted") or unfinished:
            resume_fn(run_id)
            if halted(run_id):
                return "halted", run_id
    while len(progress["run_ids"]) < repeats:
        run_dir = Path(run_fn(instances, ["baseline"]))
        progress["run_ids"].append(run_dir.name)
        _save_progress(progress_path, progress)
        if _read_json(run_dir / "run.json").get("halted"):
            return "halted", run_dir.name
    fixture_dir = assemble_fn([runs_dir / run_id for run_id in progress["run_ids"]])
    progress_path.unlink()
    return "done", str(fixture_dir)


def compare(fixture_manifest: dict, manifest: dict) -> list[str]:
    diffs = _differing(fixture_manifest["conditions"], conditions(manifest))
    iid = manifest.get("instance_id")
    if fixture_manifest["images"].get(iid) != manifest.get("images"):
        diffs.append("images")
    if iid not in fixture_manifest["instances"]:
        diffs.append("instance_id")
    return sorted(diffs)


def find(fixtures_root: Path, manifests: list[dict]) -> tuple[Path | None, dict[str, list[str]]]:
    root = Path(fixtures_root)
    differing: dict[str, list[str]] = {}
    for d in sorted(p for p in root.iterdir() if p.is_dir()) if root.is_dir() else []:
        fm = _read_json(d / "manifest.json")
        if fm is None:
            continue
        keys = sorted({k for m in manifests for k in compare(fm, m)})
        if not keys:
            return d, {}
        differing[d.name] = keys
    return None, differing


def precheck(fixtures_root: Path, cfg: dict) -> bool:
    expected = {
        "model": cfg["model"],
        "effort": cfg["effort"],
        "aliases": cfg["aliases"],
        "sdk": cfg["sdk"],
        "disallowed_tools": cfg["disallowed_tools"],
        "caps": {
            "wall_clock_min": cfg["wall_clock_min"],
            "max_user_turns": cfg["max_user_turns"],
            "idle_grace_s": cfg["idle_grace_s"],
        },
        "container": {"cpus": cfg["cpus"], "memory": cfg["memory"], "user": "nonroot"},
    }
    root = Path(fixtures_root)
    for d in sorted(p for p in root.iterdir() if p.is_dir()) if root.is_dir() else []:
        fm = _read_json(d / "manifest.json")
        if fm and all(fm["conditions"].get(k) == v for k, v in expected.items()):
            return True
    return False
