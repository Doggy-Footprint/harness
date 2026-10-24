import random

MIN_TASKS = 10


def _percentile(sorted_values: list[float], q: float) -> float:
    pos = q * (len(sorted_values) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


def cluster_bootstrap(diffs: dict[str, list[float]], *, resamples: int, seed: int, alpha: float = 0.05) -> dict:
    clusters = [list(diffs[k]) for k in sorted(diffs) if diffs[k]]
    n_tasks = sum(len(c) for c in clusters)
    if not clusters:
        return {"mean": None, "lo": None, "hi": None, "n_tasks": 0, "n_clusters": 0}
    mean = sum(sum(c) for c in clusters) / n_tasks
    rng = random.Random(seed)
    sums = [sum(c) for c in clusters]
    sizes = [len(c) for c in clusters]
    k = len(clusters)
    means = []
    for _ in range(resamples):
        picks = [rng.randrange(k) for _ in range(k)]
        means.append(sum(sums[i] for i in picks) / sum(sizes[i] for i in picks))
    means.sort()
    return {
        "mean": mean, "lo": _percentile(means, alpha / 2), "hi": _percentile(means, 1 - alpha / 2),
        "n_tasks": n_tasks, "n_clusters": k,
    }


def verdict(ci: dict, rule: dict) -> str:
    if ci["n_tasks"] < rule.get("min_tasks", MIN_TASKS):
        return "insufficient"
    if "guard_upper" in rule:
        return "harmful" if ci["hi"] > rule["guard_upper"] else "ok"
    if ci["lo"] > 0:
        return "help"
    if ci["hi"] < 0:
        return "harmful"
    return "no_help"
