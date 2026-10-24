import json
import os
import tempfile
from pathlib import Path

REDACTED = "[REDACTED]"
DEFAULT_DATA_DIR = "~/.harness/evaluation"


def atomic_write(path, data: str | bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data.encode() if isinstance(data, str) else data)
        # mkstemp creates 0600; the IAP ssh user that runs `gce pull` is not the owner on the VM.
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def session_cost(results: list[dict]) -> float | None:
    # Each SDK result's total_cost_usd is cumulative for its CLI process; a resumed process counts again from 0.
    costs = [r["total_cost_usd"] for r in results if r.get("total_cost_usd") is not None]
    if not costs:
        return None
    return sum(prev for prev, cur in zip(costs, costs[1:]) if cur < prev) + costs[-1]


def write_json(path, obj, **kw) -> None:
    atomic_write(path, json.dumps(obj, ensure_ascii=False, **kw))


def read_json(path, default=None):
    path = Path(path)
    return json.loads(path.read_text()) if path.is_file() else default


def read_jsonl(path) -> list[dict]:
    path = Path(path)
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def write_jsonl(path, rows: list[dict]) -> None:
    atomic_write(path, "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows))


def data_dir(cfg: dict) -> Path:
    return Path(os.environ.get("EVALUATION_DATA_DIR") or cfg.get("data_dir") or DEFAULT_DATA_DIR).expanduser()


def results_dir(cfg: dict) -> Path:
    path = Path(os.environ.get("EVALUATION_RESULTS_DIR") or cfg.get("results_dir") or "evaluation/reference_mutation/results").expanduser()
    return path if path.is_absolute() else Path(__file__).parents[2] / path


def tasks_path(cfg: dict, language: str) -> Path:
    return data_dir(cfg) / "tasks" / language / "tasks.jsonl"


def candidates_path(cfg: dict, language: str) -> Path:
    return data_dir(cfg) / "tasks" / language / "candidates.jsonl"


def section(cfg: dict, name: str) -> dict:
    return cfg.get(name) or {}
