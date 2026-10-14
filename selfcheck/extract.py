from . import docker_exec, patches

SEED_STATUS = ["/opt/selfcheck-py/venv/bin/python", ".harness/bin/seed.py", "status"]
SEED_RESTORE = ["/opt/selfcheck-py/venv/bin/python", ".harness/bin/seed.py", "restore"]
DIFF_ARGV = [
    "git", "-c", "core.quotePath=true", "diff", "--cached", "--binary", "--no-color",
    "--no-ext-diff", "--no-textconv", "--no-renames", "--src-prefix=a/", "--dst-prefix=b/",
]


class GitError(docker_exec.DockerError):
    pass


def _agent_exec(container, argv, **kwargs):
    return container.exec(argv, user="nonroot", workdir="/testbed", **kwargs)


def freeze(container) -> dict:
    mutmut = [p["cmd"] for p in container.processes() if "mutmut" in p["cmd"]]
    _agent_exec(container, ["sh", "-c", "kill -9 -1"])
    return {"tainted": bool(mutmut), "mutmut_processes": mutmut}


def restore_seed(container, arm: str) -> dict:
    if arm != "harness":
        return {"skipped": True}
    _, before, _ = _agent_exec(container, SEED_STATUS)
    if "seed: none" in before:
        return {"before": before, "restored": False, "after": before, "ok": True}
    code, _, _ = _agent_exec(container, SEED_RESTORE)
    _, after, _ = _agent_exec(container, SEED_STATUS)
    return {
        "before": before,
        "restored": code == 0,
        "after": after,
        "ok": code == 0 and "seed: none" in after,
    }


def full_diff(container, start_commit: str) -> str:
    code, out, _ = _agent_exec(container, ["git", "add", "-A"])
    if code != 0:
        raise GitError(out)
    code, out, _ = _agent_exec(container, [*DIFF_ARGV, start_commit])
    if code != 0:
        raise GitError(out)
    return out


def build_prediction(full_diff, instance, arm, run_id, start_commit, freeze_info, seed_info) -> dict:
    repo = instance["repo"]
    split = patches.split_patch(full_diff, repo)
    excluded = sorted(
        {
            sec["old_path"] if sec["is_deleted"] else sec["path"]
            for sec in patches.file_sections(full_diff)
            if patches.classify_path(
                sec["old_path"] if sec["is_deleted"] else sec["path"], repo, is_new=sec["is_new"]
            )
            == "excluded"
        }
    )
    return {
        "instance_id": instance["instance_id"],
        "arm": arm,
        "run_id": run_id,
        "start_commit": start_commit,
        "src_diff": split["src"],
        "test_patch": split["test"],
        "scratch_diff": split["scratch"],
        "excluded_paths": excluded,
        "tainted": freeze_info["tainted"],
        "seed": seed_info,
    }
