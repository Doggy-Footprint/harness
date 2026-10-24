import subprocess


def claude_call(prompt: str, *, model: str, effort: str, timeout_s: int) -> str:
    try:
        proc = subprocess.run(
            ["claude", "-p", "--model", model, "--effort", effort, "--output-format", "text",
             "--tools", ""],
            input=prompt, text=True, capture_output=True, timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"claude timed out after {timeout_s}s") from exc
    if proc.returncode != 0:
        # In print mode the CLI reports usage-limit and auth failures on stdout with an empty stderr.
        detail = (proc.stderr or "").strip() or (proc.stdout or "").strip()[-500:]
        raise RuntimeError(f"claude exited {proc.returncode}: {detail}")
    return proc.stdout
