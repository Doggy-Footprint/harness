import argparse
import functools
import json
import sys
from pathlib import Path

from . import calibrate, docker_exec, evaluate, images, mutants, patches, pool, run, score, swe, validate

ROOT = Path(__file__).parent
FIXTURES = ROOT / "fixtures"
CONFIG = json.loads((ROOT / "config.json").read_text())
SUBCOMMANDS = ("pool", "images", "validate", "mutants", "calibrate", "score", "run")
ARMS = ("harness", "baseline")


def _cache_dir() -> Path:
    return Path(CONFIG["cache_dir"]).expanduser()


def _evaluate_fn(cache: bool = True):
    return functools.partial(
        evaluate.evaluate,
        cache_dir=_cache_dir() if cache else None,
        timeout_s=CONFIG["eval"]["timeout_s"],
    )


def _csv(value: str | None) -> list[str] | None:
    return [v for v in value.split(",") if v] if value else None


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))


def _load_pool(ids: list[str] | None) -> list[dict]:
    path = FIXTURES / "instances.jsonl"
    if not path.is_file():
        raise SystemExit(f"{path} missing; run `python3 -m selfcheck pool` first")
    rows = _read_jsonl(path)
    if ids is not None:
        known = {r["instance_id"] for r in rows}
        missing = [i for i in ids if i not in known]
        if missing:
            raise SystemExit(f"unknown pool instances: {', '.join(missing)}")
        rows = [r for r in rows if r["instance_id"] in ids]
    return rows


def _load_validation() -> dict:
    path = FIXTURES / "validation.json"
    return json.loads(path.read_text()) if path.is_file() else {}


def _slim_validation(result: dict) -> dict:
    out = dict(result)
    out["runs"] = {
        k: [{kk: vv for kk, vv in run.items() if kk != "log_path"} for run in runs]
        for k, runs in result["runs"].items()
    }
    return out


def _normalize_row(row: dict) -> dict:
    keys = (
        "instance_id", "repo", "version", "base_commit", "environment_setup_commit", "patch",
        "test_patch", "FAIL_TO_PASS", "PASS_TO_PASS", "problem_statement", "difficulty", "created_at",
    )
    out = {k: row[k] for k in keys}
    for k in ("FAIL_TO_PASS", "PASS_TO_PASS"):
        if isinstance(out[k], str):
            out[k] = json.loads(out[k])
    return out


def cmd_pool(args) -> int:
    import datasets

    cfg = CONFIG
    ds = datasets.load_dataset(cfg["dataset"]["name"], split="test", revision=cfg["dataset"]["revision"])
    swt = datasets.load_dataset(cfg["swt_dataset"]["name"], split="test", revision=cfg["swt_dataset"]["revision"])
    swt_ids = {r["instance_id"] for r in swt}
    rows = [_normalize_row(r) for r in ds]
    ranked = pool.rank_candidates(
        rows, swt_ids=swt_ids, seed=args.seed,
        difficulties=cfg["pool"]["difficulties"], min_hunks=cfg["pool"]["min_hunks"],
    )
    evaluate_fn = _evaluate_fn()
    attempts: dict[str, dict] = {}

    def validate_fn(row: dict) -> dict:
        built, failed = swe.build_images([row])
        if failed:
            result = {"instance_id": row["instance_id"], "valid": False, "reasons": ["image_build_failed"],
                      "f2p": [], "p2p_effective": [], "p2p_flaky": [], "p2p_broken": [], "leak": {},
                      "runs": {"base": [], "gold": []}}
        else:
            result = validate.validate_instance(row, repeats=CONFIG["validation"]["repeats"], evaluate_fn=evaluate_fn)
        attempts[row["instance_id"]] = _slim_validation(result)
        print(f"{row['instance_id']}: {'valid' if result['valid'] else 'invalid ' + ','.join(result['reasons'])}", flush=True)
        return result

    kept = pool.build_pool(ranked, size=args.size, validate_fn=validate_fn)
    _write_jsonl(FIXTURES / "instances.jsonl", kept)
    (FIXTURES / "validation.json").write_text(json.dumps(attempts, indent=1, sort_keys=True))
    if len(kept) < args.size:
        print(f"only {len(kept)} of {args.size} instances validated", file=sys.stderr)
        return 1
    return 0


def _cmd_images_agent(args) -> int:
    cfg = CONFIG["agent"]
    rows = _load_pool(_csv(args.instances))
    failed = False
    try:
        images.build_tools_image(cfg=cfg)
    except images.ImageBuildError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    for row in rows:
        try:
            name = images.build_derived_image(row, cfg=cfg)
        except (images.ImageBuildError, docker_exec.ImageMissing, docker_exec.DockerError) as exc:
            print(str(exc), file=sys.stderr)
            failed = True
            continue
        print(f"{row['instance_id']} {name}", flush=True)
    return 1 if failed else 0


def cmd_images(args) -> int:
    if args.agent:
        return _cmd_images_agent(args)
    rows = _load_pool(_csv(args.instances))
    built, failed = swe.build_images(rows)
    print(f"built or existing: {len(built)}; failed: {len(failed)}")
    for i in failed:
        print(f"failed: {i}", file=sys.stderr)
    return 1 if failed else 0


def cmd_run(args) -> int:
    cfg = CONFIG["agent"]
    try:
        if args.resume:
            run_dir = run.resume(args.resume, cfg=cfg)
        else:
            arms = _csv(args.arms) or list(ARMS)
            bad = [a for a in arms if a not in ARMS]
            if bad:
                print(f"unknown arms: {', '.join(bad)}", file=sys.stderr)
                return 2
            ids = _csv(args.instances)
            rows = _load_pool(ids)
            if ids is None:
                rows = [r for r in rows if r.get("core")]
            run_dir = run.run(
                rows, arms, cfg=cfg, harness_ref=args.harness_ref, model=args.model,
                effort=args.effort, cap_min=args.cap_min,
            )
    except run.UnknownRunError:
        print(f"unknown run id: {args.resume}", file=sys.stderr)
        return 2
    except (run.TokenFileMissing, docker_exec.DockerError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(run_dir)
    entries = json.loads((Path(run_dir) / "run.json").read_text())["entries"]
    return 1 if any(e["status"] == "error" for e in entries) else 0


def cmd_validate(args) -> int:
    rows = _load_pool(_csv(args.instances))
    existing = _load_validation()
    evaluate_fn = _evaluate_fn()
    bad = 0
    for row in rows:
        result = validate.validate_instance(row, repeats=args.repeats, evaluate_fn=evaluate_fn)
        existing[row["instance_id"]] = _slim_validation(result)
        print(f"{row['instance_id']}: {'valid' if result['valid'] else 'invalid ' + ','.join(result['reasons'])}", flush=True)
        bad += not result["valid"]
    (FIXTURES / "validation.json").write_text(json.dumps(existing, indent=1, sort_keys=True))
    return 1 if bad else 0


def cmd_mutants(args) -> int:
    rows = _load_pool(_csv(args.instances))
    validation = _load_validation()
    evaluate_fn = _evaluate_fn()
    for row in rows:
        sections = patches.file_sections(patches.split_patch(row["patch"], row["repo"])["src"])
        paths = [s["path"] for s in sections if s["path"].endswith(".py") and not s["is_deleted"]]
        base = evaluate.read_files(row, "", paths)
        gold = {p: t for p, t in evaluate.read_files(row, row["patch"], paths).items() if t is not None}
        generated = mutants.generate(base, gold, row["patch"], sample=args.sample, seed=args.seed)
        detected = mutants.detect(
            row, generated, validation=validation[row["instance_id"]],
            evaluate_fn=evaluate_fn, workers=args.workers,
        )
        _write_jsonl(FIXTURES / "mutants" / f"{row['instance_id']}.jsonl", detected)
        valid = [m for m in detected if m["compile_ok"]]
        d_ref = [m for m in valid if m["killed"]]
        print(f"{row['instance_id']}: {len(detected)} mutants, {len(valid)} compile-valid, D_ref={len(d_ref)}", flush=True)
    return 0


def _load_mutants(instance_id: str) -> list[dict]:
    path = FIXTURES / "mutants" / f"{instance_id}.jsonl"
    if not path.is_file():
        raise SystemExit(f"{path} missing; run `python3 -m selfcheck mutants` first")
    return _read_jsonl(path)


def cmd_calibrate(args) -> int:
    rows = _load_pool(_csv(args.instances))
    validation = _load_validation()
    evaluate_fn = _evaluate_fn()
    score_fn = functools.partial(score.score_prediction, evaluate_fn=evaluate_fn, workers=args.workers)
    out = {}
    for row in rows:
        out[row["instance_id"]] = calibrate.calibrate_instance(
            row, validation=validation[row["instance_id"]],
            mutants=_load_mutants(row["instance_id"]), score_fn=score_fn,
        )
        res = out[row["instance_id"]]
        print(f"{row['instance_id']}: monotonic={res['monotonic']} {res['violations']}", flush=True)
    (FIXTURES / "calibration.json").write_text(json.dumps(out, indent=1, sort_keys=True))
    return 0 if all(r["monotonic"] for r in out.values()) else 1


def cmd_score(args) -> int:
    rows = {r["instance_id"]: r for r in _load_pool(None)}
    validation = _load_validation()
    evaluate_fn = _evaluate_fn(cache=not args.no_cache)
    results = []
    for pred in _read_jsonl(Path(args.predictions)):
        iid = pred["instance_id"]
        if iid not in rows:
            print(f"prediction for unknown instance {iid}", file=sys.stderr)
            return 1
        results.append(
            score.score_prediction(
                rows[iid], pred, validation=validation[iid], mutants=_load_mutants(iid),
                evaluate_fn=evaluate_fn, workers=args.workers,
            )
        )
    _write_jsonl(Path(args.out), results)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="selfcheck")
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name, fn, instances=True, **flags):
        p = sub.add_parser(name)
        if instances:
            p.add_argument("--instances")
        for flag, kw in flags.items():
            p.add_argument(f"--{flag.replace('_', '-')}", **kw)
        p.set_defaults(func=fn)
        return p

    add("pool", cmd_pool, instances=False, size={"type": int, "default": CONFIG["pool"]["size"]},
        seed={"type": int, "default": CONFIG["pool"]["seed"]})
    add("images", cmd_images, agent={"action": "store_true"})
    add("validate", cmd_validate, repeats={"type": int, "default": CONFIG["validation"]["repeats"]})
    add("mutants", cmd_mutants, sample={"type": int, "default": CONFIG["mutants"]["sample"]},
        seed={"type": int, "default": CONFIG["mutants"]["seed"]},
        workers={"type": int, "default": 2})
    add("calibrate", cmd_calibrate, workers={"type": int, "default": 2})
    add("score", cmd_score, instances=False, predictions={"required": True}, out={"required": True},
        no_cache={"action": "store_true"}, workers={"type": int, "default": 2})
    add("run", cmd_run, arms={}, harness_ref={"default": "HEAD"}, model={}, effort={},
        cap_min={"type": int}, resume={})
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (RuntimeError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
