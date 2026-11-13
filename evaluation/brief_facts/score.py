#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

SURFACED = {"asked", "assumed"}


def grade(case: dict, judgement: dict) -> tuple[list[dict], dict]:
    unknowns = {item["id"]: item for item in judgement.get("unknowns", [])}
    questions = judgement.get("questions", [])
    expectations = []
    for item in case["unknowns"]:
        got = unknowns.get(item["id"], {"status": "absent", "evidence": ""})
        expectations.append({
            "text": f"Surfaces the unknown fact: {item['fact']}",
            "passed": got["status"] in SURFACED,
            "evidence": f"{got['status']}: {got.get('evidence', '')}",
        })
    repo = [q for q in questions if str(q["target"]).startswith("R")]
    noise = [q for q in questions if q["target"] == "dont_care" or (q["target"] == "other" and q.get("useful") is False)]
    decisions = [q for q in questions if q["form"] == "decision"]
    recommended = [q for q in questions if q.get("recommendation")]
    for text, bad in (
        ("Asks nothing the repository already answers", repo),
        ("Asks nothing that would not change the design", noise),
        ("Asks for facts, not for design choices", decisions),
        ("Gives no recommended answer with a question", recommended),
    ):
        expectations.append({"text": text, "passed": not bad, "evidence": "; ".join(q["text"] for q in bad) or "none"})
    statuses = [unknowns.get(item["id"], {}).get("status", "absent") for item in case["unknowns"]]
    metrics = {
        "unknowns": len(statuses),
        "asked": statuses.count("asked"),
        "assumed": statuses.count("assumed"),
        "decided": statuses.count("decided"),
        "absent": statuses.count("absent"),
        "questions": len(questions),
        "fact_questions": len(questions) - len(decisions),
        "decision_questions": len(decisions),
        "repo_answerable_questions": len(repo),
        "noise_questions": len(noise),
        "recommended_answers": len(recommended),
    }
    return expectations, metrics


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("iteration", type=Path)
    parser.add_argument("--cases", type=Path, default=Path(__file__).parent / "cases")
    args = parser.parse_args()
    rows = []
    for eval_dir in sorted(args.iteration.glob("eval-*")):
        case = json.loads((args.cases / f"{eval_dir.name[5:]}.json").read_text(encoding="utf-8"))
        for run_dir in sorted(eval_dir.glob("*/run-*")):
            path = run_dir / "judgement.json"
            if not path.exists():
                print(f"missing {path}", file=sys.stderr)
                continue
            expectations, metrics = grade(case, json.loads(path.read_text(encoding="utf-8")))
            passed = sum(1 for item in expectations if item["passed"])
            (run_dir / "grading.json").write_text(json.dumps({
                "expectations": expectations,
                "summary": {"passed": passed, "failed": len(expectations) - passed, "total": len(expectations),
                            "pass_rate": round(passed / len(expectations), 4)},
            }, indent=2, ensure_ascii=False), encoding="utf-8")
            rows.append({"case": case["id"], "config": run_dir.parent.name, "run": run_dir.name, **metrics})
    (args.iteration / "metrics.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    keys = [key for key in rows[0] if key not in ("case", "config", "run")] if rows else []
    groups: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        groups.setdefault((row["case"], row["config"]), []).append(row)
    print("case\tconfig\truns\t" + "\t".join(keys))
    for (case_id, config), items in sorted(groups.items()):
        means = [f"{sum(item[key] for item in items) / len(items):.1f}" for key in keys]
        print(f"{case_id}\t{config}\t{len(items)}\t" + "\t".join(means))
    return 0


if __name__ == "__main__":
    sys.exit(main())
