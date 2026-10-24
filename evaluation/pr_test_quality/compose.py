ARMS = ("B0", "Bplus", "H")
BPLUS_PARAGRAPH = (
    "Write thorough automated tests: cover normal cases, boundaries, invalid inputs and error paths, "
    "assert observable behavior rather than implementation details, and run the tests before you finish."
)
H_PREFIX = "/workflow-approach "


def compose_prompt(brief: dict, arm: str) -> str:
    request = brief["request"]
    if arm == "B0":
        return request
    if arm == "Bplus":
        return request + "\n\n" + BPLUS_PARAGRAPH
    if arm == "H":
        return H_PREFIX + request
    raise ValueError(f"unknown arm: {arm}")
