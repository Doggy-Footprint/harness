"""PreToolUse/PostToolUse helpers shared by contract_gate and telemetry_hook.

Test command matching must stay identical between the two hooks: telemetry
should recognize exactly the commands the gate blocks on.
"""
from pathlib import Path

TEST_COMMAND_PREFIX = "Test command:"


def normalize(command: str) -> str:
    return " ".join(command.split())


def iter_test_commands(contracts_dir: Path):
    """Yield (normalized_command, contract_stem) for every `Test command:` line."""
    if not contracts_dir.is_dir():
        return
    for contract in sorted(contracts_dir.glob("*.md")):
        for line in contract.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith(TEST_COMMAND_PREFIX):
                command = normalize(line[len(TEST_COMMAND_PREFIX):])
                if command:
                    yield command, contract.stem


def test_commands(contracts_dir: Path) -> set:
    return {command for command, _ in iter_test_commands(contracts_dir)}


def shell_command(tool_input) -> str:
    command = (tool_input or {}).get("command")
    if isinstance(command, list):
        if len(command) >= 3 and command[1] in ("-c", "-lc"):
            return command[-1]
        return " ".join(command)
    return command if isinstance(command, str) else ""
