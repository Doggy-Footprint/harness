import hashlib
from pathlib import Path

AGENT_DIR = Path(__file__).parent / "agent"
USER_SIM_FILES = (AGENT_DIR / "user_sim.py", AGENT_DIR / "driver.py")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _lines(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if ln.strip()]


def build(
    *, run_id, instance, arm, cfg, selfcheck_commit, harness_ref, harness_commit, start_commit,
    install, images, proxy, driver_state, prompt,
) -> dict:
    problem = instance["problem_statement"].strip()
    template = prompt.replace(problem, "{problem}")
    before = set(_lines(images["freeze_before"]))
    resolved = [ln for ln in _lines(images["freeze_after"]) if ln not in before]
    init = driver_state.get("init") or {}
    return {
        "run_id": run_id,
        "instance_id": instance["instance_id"],
        "arm": arm,
        "selfcheck_commit": selfcheck_commit,
        "harness_ref": harness_ref,
        "harness_commit": harness_commit if arm == "harness" else None,
        "start_commit": start_commit,
        "install": install if arm == "harness" else None,
        "model": cfg["model"],
        "effort": cfg["effort"],
        "aliases": cfg["aliases"],
        "sdk": cfg["sdk"],
        "cli_version": driver_state.get("cli_version"),
        "tools": init.get("tools"),
        "disallowed_tools": cfg["disallowed_tools"],
        "caps": {
            "wall_clock_min": cfg["wall_clock_min"],
            "max_user_turns": cfg["max_user_turns"],
            "idle_grace_s": cfg["idle_grace_s"],
        },
        "container": {"cpus": cfg["cpus"], "memory": cfg["memory"], "user": "nonroot"},
        "env_keys": sorted(driver_state.get("env_keys") or []),
        "prompt_template_hash": _sha256(template.encode()),
        "user_sim_hash": _sha256(b"".join(Path(p).read_bytes() for p in USER_SIM_FILES)),
        "images": {
            "instance_image_id": images["instance_image_id"],
            "tools_image_id": images["tools_image_id"],
            "derived_image": images["derived_image"],
            "derived_image_id": images["derived_image_id"],
            "testbed_tools_resolved": resolved,
        },
        "network": {
            "allow_hosts": proxy["allow_hosts"],
            "proxy_image": proxy["proxy_image"],
            "squid_conf_hash": proxy["squid_conf_hash"],
        },
    }


def differences(a: dict, b: dict) -> set[str]:
    return {k for k in a.keys() | b.keys() if a.get(k) != b.get(k)}
