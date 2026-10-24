import re

from . import docker_exec, evaluate, patches, swe
from .evaluate import FAIL, PASS



def _in_fail(status: dict, test: str) -> bool:
    return status.get(test) in FAIL or test not in status


def validate_instance(
    instance: dict, *, repeats: int = 3, evaluate_fn=evaluate.evaluate, leak_fn=None
) -> dict:
    leak_fn = leak_fn or leak_check
    runs = {"base": [], "gold": []}
    for label, src in (("base", ""), ("gold", instance["patch"])):
        for i in range(repeats):
            runs[label].append(evaluate_fn(instance, src, instance["test_patch"], repeat=i))
    try:
        leak = leak_fn(instance)
    except RuntimeError as exc:
        leak = {"ok": False, "error": str(exc)}

    reasons = []
    allruns = runs["base"] + runs["gold"]
    if any(r["apply"] != "ok" for r in allruns):
        reasons.append("apply_failed")
    if any(r.get("timed_out") for r in allruns):
        reasons.append("timeout")
    f2p = list(instance["FAIL_TO_PASS"])
    if any(not _in_fail(r["status"], t) for r in runs["base"] for t in f2p):
        reasons.append("f2p_passes_on_base")
    if any(r["status"].get(t) not in PASS for r in runs["gold"] for t in f2p):
        reasons.append("f2p_fails_on_gold")
    effective, flaky, broken = [], [], []
    for t in instance["PASS_TO_PASS"]:
        n = sum(1 for r in allruns if r["status"].get(t) in PASS)
        if n == len(allruns):
            effective.append(t)
        elif n == 0:
            broken.append(t)
        else:
            flaky.append(t)
    if broken:
        reasons.append("p2p_broken")
    if not leak.get("ok"):
        reasons.append("leak")
    return {
        "instance_id": instance["instance_id"],
        "valid": not reasons,
        "reasons": reasons,
        "f2p": f2p,
        "p2p_effective": effective,
        "p2p_flaky": flaky,
        "p2p_broken": broken,
        "leak": leak,
        "runs": runs,
    }


# Scratch lives outside /opt /usr /root /home /tmp so it is never counted as a gold copy.
_SCRATCH = "/selfcheck_scratch"

_LEAK_SCRIPT = r"""
set -u
B="$1"
S=/selfcheck_scratch/w
cd /testbed
git config --global --add safe.directory /testbed
N=0
BC=$(git rev-parse "$B^{commit}")
# swebench's own setup commit ("SWE-bench", sole parent = base) is not history leakage.
for c in $(git rev-list --all "^$B"); do
  if [ "$(git log -1 --format=%s "$c")" = "SWE-bench" ] && [ "$(git log -1 --format=%P "$c")" = "$BC" ]; then continue; fi
  N=$((N+1))
done
echo "FUTURE_COMMITS=$N"
git for-each-ref --format='%(refname:short)' refs/tags | while IFS= read -r t; do
  c=$(git rev-parse -q --verify "$t^{commit}") || continue
  git merge-base --is-ancestor "$c" "$B" || echo "FUTURE_TAG=$t"
done
rm -rf "$S"; mkdir -p "$S"
while IFS= read -r p; do
  mkdir -p "$S/$(dirname "$p")"
  git -C /testbed show "$B:$p" > "$S/$p"
done < /selfcheck_scratch/base_paths
(cd "$S" && git init -q . && git apply --whitespace=nowarn /selfcheck_scratch/gold.diff) || echo GOLD_APPLY_FAILED
: > /selfcheck_scratch/hashes
while IFS= read -r p; do
  [ -f "$S/$p" ] || continue
  h=$(git -C "$S" hash-object --no-filters "$p")
  if git -C /testbed cat-file -e "$h" 2>/dev/null; then echo "BLOB_PRESENT=$p"; fi
  sz=$(stat -c %s "$S/$p")
  [ "$sz" -gt 0 ] && echo "$(sha256sum "$S/$p" | cut -d' ' -f1) $sz" >> /selfcheck_scratch/hashes
done < /selfcheck_scratch/post_paths
awk '{print $2}' /selfcheck_scratch/hashes | sort -u | while read -r sz; do
  find /opt /usr /root /home /tmp -type f -size "${sz}c" -print0 2>/dev/null | xargs -0 -r sha256sum 2>/dev/null
done | while read -r h f; do
  grep -q "^$h " /selfcheck_scratch/hashes && echo "COPY=$f"
done
exit 0
"""


def leak_check(instance: dict) -> dict:
    gold_src = patches.split_patch(instance["patch"], instance["repo"])["src"]
    secs = patches.file_sections(gold_src)
    base_paths = [s["old_path"] for s in secs if not s["is_new"]]
    post_paths = [s["path"] for s in secs if not s["is_deleted"]]
    image = swe.image_name(instance)
    docker_exec.image_id(image)
    with docker_exec.container(image, network=False) as c:
        c.exec(["mkdir", "-p", _SCRATCH], timeout=60)
        c.write_text(f"{_SCRATCH}/gold.diff", gold_src)
        c.write_text(f"{_SCRATCH}/base_paths", "".join(p + "\n" for p in base_paths))
        c.write_text(f"{_SCRATCH}/post_paths", "".join(p + "\n" for p in post_paths))
        c.write_text(f"{_SCRATCH}/leak.sh", _LEAK_SCRIPT)
        rc, out, timed_out = c.exec(
            ["bash", f"{_SCRATCH}/leak.sh", instance["base_commit"]], timeout=900
        )
    if timed_out or "GOLD_APPLY_FAILED" in out:
        raise RuntimeError(f"leak_check could not complete for {instance['instance_id']}")
    commits = re.search(r"^FUTURE_COMMITS=(\d+)$", out, re.M)
    if commits is None:
        raise RuntimeError(f"leak_check produced no result for {instance['instance_id']}: {out[-500:]}")
    tags = re.findall(r"^FUTURE_TAG=(.*)$", out, re.M)
    blobs = re.findall(r"^BLOB_PRESENT=(.*)$", out, re.M)
    copies = re.findall(r"^COPY=(.*)$", out, re.M)
    n = int(commits.group(1))
    return {
        "ok": n == 0 and not tags and not blobs and not copies,
        "future_commits": n,
        "future_tags": tags,
        "gold_blobs_present": blobs,
        "gold_copies": copies,
    }
