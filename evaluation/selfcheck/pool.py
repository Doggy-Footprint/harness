import random
import re

from .swe import USE_X86

CORE = 3


def count_hunks(patch: str) -> int:
    return len(re.findall(r"(?m)^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@", patch))


def eligible(
    row: dict,
    *,
    swt_ids: set[str],
    difficulties: list[str],
    min_hunks: int,
    excluded_ids: set[str] = frozenset(),
) -> bool:
    iid = row["instance_id"]
    return (
        iid in swt_ids
        and row.get("difficulty") in difficulties
        and count_hunks(row["patch"]) >= min_hunks
        and iid not in USE_X86
        and iid not in excluded_ids
    )


def rank_candidates(
    rows: list[dict],
    *,
    swt_ids,
    seed: int,
    difficulties,
    min_hunks,
    excluded_ids=frozenset(),
) -> list[dict]:
    by_repo: dict[str, dict[str, dict]] = {}
    for row in rows:
        if eligible(
            row,
            swt_ids=swt_ids,
            difficulties=difficulties,
            min_hunks=min_hunks,
            excluded_ids=excluded_ids,
        ):
            by_repo.setdefault(row["repo"], {})[row["instance_id"]] = row
    repos = sorted(by_repo)
    random.Random(seed).shuffle(repos)
    queues = []
    for repo in repos:
        ids = sorted(by_repo[repo])
        random.Random(f"{seed}:{repo}").shuffle(ids)
        queues.append([by_repo[repo][i] for i in ids])
    out = []
    for depth in range(max((len(q) for q in queues), default=0)):
        for q in queues:
            if depth < len(q):
                out.append(q[depth])
    return out


def build_pool(ranked: list[dict], *, size: int, validate_fn) -> list[dict]:
    kept: list[dict] = []
    for row in ranked:
        if len(kept) >= size:
            break
        if validate_fn(row).get("valid"):
            kept.append({**row, "core": len(kept) < CORE})
    return kept
