import argparse
import functools
import json
import sys
from pathlib import Path

from . import (
    calibrate, docker_exec, evaluate, fixture, images, informed, manifest, mutants, patches, pool,
    process, report, review, run, score, swe, validate,
)

ROOT = Path(__file__).parent
FIXTURES = ROOT / "fixtures"
CONFIG = json.loads((ROOT / "config.json").read_text())
SUBCOMMANDS = (
    "pool", "images", "validate", "mutants", "calibrate", "score", "run",
    "process", "baseline", "check", "report", "review",
)
BASELINE_HINT = "run `python3 -m selfcheck baseline create`"
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
    meta = json.loads((Path(run_dir) / "run.json").read_text())
    if meta["halted"]:
        h = meta["halted"]
        print(run_dir, file=sys.stderr)
        print(
            f"halted: {h['reason']} at {h['instance_id']}/{h['arm']}; "
            f"resume with: python3 -m selfcheck run --resume {meta['run_id']}",
            file=sys.stderr,
        )
        return 3
    return 1 if any(e["status"] == "error" for e in meta["entries"]) else 0


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


def _repo_path(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else ROOT.parent / path


def _run_dir(run_id: str) -> Path | None:
    run_dir = Path(CONFIG["agent"]["runs_dir"]).expanduser() / run_id
    return run_dir if (run_dir / "run.json").is_file() else None


def _unknown_run(run_id: str) -> int:
    print(f"unknown run id: {run_id}", file=sys.stderr)
    return 2


def _read_token() -> str:
    return run._token_path(CONFIG["agent"]).read_text().strip()


def _harness_entries(run_dir: Path, mode: str | None = None) -> list[dict]:
    meta = json.loads((run_dir / "run.json").read_text())
    return [
        e for e in meta["entries"]
        if e["arm"] == "harness" and (mode is None or run.entry_mode(e) == mode)
    ]


def _scores_name(mode: str) -> str:
    return "scores.harness-informed.jsonl" if mode == "informed" else "scores.harness.jsonl"


def _load_scores(run_dir: Path, mode: str = "unassisted") -> dict[tuple[str, int], dict]:
    path = run_dir / _scores_name(mode)
    rows = _read_jsonl(path) if path.is_file() else []
    return {(r["instance_id"], r.get("repeat", 1)): r for r in rows}


def _process_entries(
    run_dir: Path, *, write: bool, mode: str = "unassisted"
) -> dict[tuple[str, int], dict]:
    scores = _load_scores(run_dir, mode)
    out = {}
    for entry in _harness_entries(run_dir, mode):
        key = (entry["instance_id"], run.entry_repeat(entry))
        edir = run.entry_dir(run_dir, entry)
        if not edir.is_dir():
            continue
        saved = edir / "process.json"
        if not write and saved.is_file():
            out[key] = json.loads(saved.read_text())
            continue
        out[key] = process.evaluate_entry(edir, score=scores.get(key))
        if write:
            saved.write_text(json.dumps(out[key], indent=1, sort_keys=True))
    return out


def _label(iid: str, repeat: int, multi: bool, mode: str = "unassisted") -> str:
    base = f"{iid} informed" if mode == "informed" else iid
    return f"{base} r{repeat}" if multi else base


def cmd_process(args) -> int:
    run_dir = _run_dir(args.run_id)
    if run_dir is None:
        return _unknown_run(args.run_id)
    by_mode = {m: _process_entries(run_dir, write=True, mode=m) for m in informed.CONDITIONS}
    multi = any(repeat != 1 for results in by_mode.values() for _, repeat in results)
    for mode, results in by_mode.items():
        for (iid, repeat), result in results.items():
            counts = [
                sum(c["verdict"] == v for c in result["checks"].values()) for v in ("pass", "fail", "n/a")
            ]
            print(f"{_label(iid, repeat, multi, mode)} pass={counts[0]} fail={counts[1]} n/a={counts[2]}")
    return 0


def _score_fn():
    rows = {r["instance_id"]: r for r in _load_pool(None)}
    validation = _load_validation()
    evaluate_fn = _evaluate_fn()

    def score_one(pred: dict) -> dict:
        iid = pred["instance_id"]
        return score.score_prediction(
            rows[iid], pred, validation=validation[iid], mutants=_load_mutants(iid),
            evaluate_fn=evaluate_fn, workers=2,
        )

    return score_one


def cmd_baseline(args) -> int:
    cfg, bcfg = CONFIG["agent"], CONFIG["baseline"]
    try:
        token = _read_token()
        rows = _load_pool(_csv(args.instances))
        out_root = _repo_path(bcfg["fixtures_dir"])
        status, ref = fixture.create(
            rows, repeats=args.repeats or bcfg["repeats"], cfg=cfg,
            progress_path=_repo_path(bcfg["progress"]),
            run_fn=lambda insts, arms: run.run(insts, arms, cfg=cfg),
            resume_fn=lambda run_id: run.resume(run_id, cfg=cfg),
            assemble_fn=lambda dirs: fixture.assemble(
                dirs, score_fn=_score_fn(), out_root=out_root, token=token
            ),
        )
    except (fixture.FixtureError, run.TokenFileMissing, docker_exec.DockerError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if status == "halted":
        print(
            f"halted in run {ref}; rerun `python3 -m selfcheck baseline create` to resume",
            file=sys.stderr,
        )
        return 3
    print(ref)
    return 0


def _entry_manifests(run_dir: Path, mode: str) -> list[dict]:
    manifests = []
    for entry in _harness_entries(run_dir, mode):
        path = run.entry_dir(run_dir, entry) / "manifest.json"
        if path.is_file():
            manifests.append(json.loads(path.read_text()))
    return manifests


def _manifest_candidates(run_dir: Path) -> list[list[dict]]:
    manifests = _entry_manifests(run_dir, "unassisted")
    if manifests or not _harness_entries(run_dir, "informed"):
        return [manifests]
    # Baseline fixtures record the two-file user_sim_hash, so informed manifests carry the
    # unassisted hash and lose user_mode before the lookup.
    return [[
        {**{k: v for k, v in m.items() if k != "user_mode"}, "user_sim_hash": manifest.user_sim_hash()}
        for m in _entry_manifests(run_dir, "informed")
    ]]


def _emit_report(run_dir: Path, *, no_baseline: bool, token: str) -> int:
    fixture_dir = None
    if not no_baseline:
        for candidate in _manifest_candidates(run_dir):
            fixture_dir, differing = fixture.find(
                _repo_path(CONFIG["baseline"]["fixtures_dir"]), candidate
            )
            if fixture_dir is not None:
                break
        if fixture_dir is None:
            for fid, keys in differing.items():
                print(f"fixture {fid} differs in: {', '.join(keys)}", file=sys.stderr)
            if not differing:
                print("no baseline fixture exists", file=sys.stderr)
            print(f"{BASELINE_HINT} to create one", file=sys.stderr)
            return 2
    built = report.build(
        run_dir, fixture_dir=fixture_dir, scores=_load_scores(run_dir),
        processes=_process_entries(run_dir, write=False),
        min_mutants=CONFIG["report"]["min_mutants"], reviews=None,
        informed_scores=_load_scores(run_dir, "informed"),
        informed_processes=_process_entries(run_dir, write=False, mode="informed"),
    )
    try:
        paths = report.write(built, _repo_path(CONFIG["report"]["results_dir"]), token=token)
    except report.ReportError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    for path in paths:
        print(path)
    return 0


def cmd_report(args) -> int:
    run_dir = _run_dir(args.run_id)
    if run_dir is None:
        return _unknown_run(args.run_id)
    try:
        token = _read_token()
    except run.TokenFileMissing as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return _emit_report(run_dir, no_baseline=args.no_baseline, token=token)


def cmd_review(args) -> int:
    run_dir = _run_dir(args.run_id)
    if run_dir is None:
        return _unknown_run(args.run_id)
    try:
        token = _read_token()
    except run.TokenFileMissing as exc:
        print(str(exc), file=sys.stderr)
        return 1
    rows = {r["instance_id"]: r for r in _load_pool(None)}
    ids = _csv(args.instances)
    call_fn = functools.partial(review.claude_call, **CONFIG["review"])
    failed = False
    entries = _harness_entries(run_dir)
    multi = any(run.entry_repeat(e) != 1 for e in entries)
    for entry in entries:
        iid = entry["instance_id"]
        edir = run.entry_dir(run_dir, entry)
        if (ids is not None and iid not in ids) or not edir.is_dir() or iid not in rows:
            continue
        result = review.review_entry(
            edir, rows[iid], call_fn=call_fn, token=token,
            model=CONFIG["review"]["model"], effort=CONFIG["review"]["effort"],
        )
        label = _label(iid, run.entry_repeat(entry), multi, run.entry_mode(entry))
        print(f"{label} {result['status']}", flush=True)
        failed = failed or result["status"] == "error"
    return 1 if failed else 0


def cmd_check(args) -> int:
    cfg = CONFIG["agent"]
    if args.resume and _run_dir(args.resume) is None:
        return _unknown_run(args.resume)
    conditions = tuple(dict.fromkeys(_csv(args.conditions) or ["unassisted"]))
    unknown = [c for c in conditions if c not in informed.CONDITIONS]
    if unknown and not args.resume:
        print(f"unknown conditions: {', '.join(unknown)}", file=sys.stderr)
        return 2
    try:
        token = _read_token()
        if not (args.no_baseline or args.resume or fixture.precheck(
            _repo_path(CONFIG["baseline"]["fixtures_dir"]), cfg
        )):
            print(
                "no baseline fixture matches the current conditions; "
                "run `python3 -m selfcheck baseline create`",
                file=sys.stderr,
            )
            return 2
        if args.resume:
            run_dir = run.resume(args.resume, cfg=cfg)
        else:
            ids = _csv(args.instances)
            rows = _load_pool(ids)
            if ids is None:
                rows = [r for r in rows if r.get("core")]
            run_dir = run.run(
                rows, ["harness"], cfg=cfg, harness_ref=args.harness_ref, repeats=args.repeats,
                conditions=conditions,
            )
    except run.UnknownRunError:
        return _unknown_run(args.resume)
    except (run.TokenFileMissing, docker_exec.DockerError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    run_dir = Path(run_dir)
    meta = json.loads((run_dir / "run.json").read_text())
    print(run_dir)
    if meta["halted"]:
        h = meta["halted"]
        print(
            f"halted: {h['reason']} at {h['instance_id']}/{h['arm']}; "
            f"resume with: python3 -m selfcheck check --resume {meta['run_id']}",
            file=sys.stderr,
        )
        return 3
    score_one = _score_fn()
    modes = ["unassisted"] + (["informed"] if _harness_entries(run_dir, "informed") else [])
    for mode in modes:
        suffix = "-informed" if mode == "informed" else ""
        predictions = run_dir / f"predictions.harness{suffix}.jsonl"
        results = [
            {**score_one(p), "repeat": p.get("repeat", 1)} for p in _read_jsonl(predictions)
        ] if predictions.is_file() else []
        _write_jsonl(run_dir / _scores_name(mode), results)
        _process_entries(run_dir, write=True, mode=mode)
    return _emit_report(run_dir, no_baseline=args.no_baseline, token=token)


def _positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid int value: {value!r}") from None
    if number < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1: {value}")
    return number


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
    add("process", cmd_process, instances=False).add_argument("run_id")
    base = add("baseline", cmd_baseline, repeats={"type": int})
    base.add_argument("action", choices=("create",))
    add("check", cmd_check, harness_ref={"default": "HEAD"}, resume={},
        repeats={"type": _positive_int, "default": CONFIG["check"]["repeats"]},
        no_baseline={"action": "store_true"}, conditions={"default": "unassisted"})
    add("report", cmd_report, instances=False, no_baseline={"action": "store_true"}).add_argument("run_id")
    add("review", cmd_review).add_argument("run_id")
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
