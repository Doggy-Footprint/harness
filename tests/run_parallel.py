import argparse
import os
import re
import subprocess
import sys
import time
import unittest
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parent
RAN = re.compile(r"^Ran (\d+) tests? in ", re.M)
STATUS = re.compile(r"^(OK|FAILED)(?: \((.*)\))?\s*$", re.M)


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


def collect_units(modules, chunk):
    sys.path[:0] = [str(TESTS), str(ROOT)]
    suite = unittest.defaultTestLoader.discover(str(TESTS), top_level_dir=str(TESTS))
    groups = {}
    for test in flatten(suite):
        if isinstance(test, unittest.loader._FailedTest):
            name = test._testMethodName
            groups[(name,)] = [name]
            continue
        module, cls, _ = test.id().split(".", 2)
        groups.setdefault((module, cls), []).append(test.id())
    units = []
    for key, ids in groups.items():
        if modules and key[0] not in modules:
            continue
        units.extend(ids[i:i + chunk] for i in range(0, len(ids), chunk))
    return sorted(units, key=len, reverse=True)


def run_unit(ids):
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(TESTS), env.get("PYTHONPATH")]))
    started = time.perf_counter()
    proc = subprocess.run([sys.executable, "-m", "unittest", *ids], cwd=ROOT, env=env, capture_output=True, text=True)
    output = proc.stdout + proc.stderr
    counts = {"ran": 0, "failures": 0, "errors": 0, "skipped": 0}
    ran = RAN.search(output)
    if ran:
        counts["ran"] = int(ran.group(1))
    status = STATUS.findall(output)
    if status and status[-1][1]:
        for part in status[-1][1].split(","):
            name, _, value = part.strip().partition("=")
            if name in counts:
                counts[name] = int(value)
    failed = proc.returncode != 0
    if failed and not counts["failures"] and not counts["errors"]:
        counts["errors"] = 1
    return ids, counts, failed, output, time.perf_counter() - started


def label(ids):
    first = ids[0]
    return first if len(ids) == 1 else f"{first.rsplit('.', 1)[0]} ({len(ids)} tests)"


def main():
    parser = argparse.ArgumentParser(description="Run the test suite in parallel worker processes.")
    parser.add_argument("modules", nargs="*", help="test module names to run, e.g. test_progress (default: all)")
    parser.add_argument("-j", "--jobs", type=int, default=os.cpu_count() or 1)
    parser.add_argument("--chunk", type=int, default=8, help="maximum tests from one class per worker process")
    args = parser.parse_args()

    started = time.perf_counter()
    units = collect_units(set(args.modules), args.chunk)
    totals = {"ran": 0, "failures": 0, "errors": 0, "skipped": 0}
    durations = []
    failed_units = 0
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = [pool.submit(run_unit, ids) for ids in units]
        for future in as_completed(futures):
            ids, counts, failed, output, elapsed = future.result()
            for key in totals:
                totals[key] += counts[key]
            durations.append((elapsed, label(ids)))
            if failed:
                failed_units += 1
                print(f"===== FAILED: {label(ids)}\n{output}", flush=True)

    print("slowest worker runs:")
    for elapsed, name in sorted(durations, reverse=True)[:5]:
        print(f"  {elapsed:6.1f}s  {name}")
    wall = time.perf_counter() - started
    print(f"Ran {totals['ran']} tests in {len(units)} worker runs with {args.jobs} jobs in {wall:.1f}s")
    detail = ", ".join(f"{k}={totals[k]}" for k in ("failures", "errors", "skipped") if totals[k])
    print(("FAILED" if failed_units else "OK") + (f" ({detail})" if detail else ""))
    return 1 if failed_units else 0


if __name__ == "__main__":
    sys.exit(main())
