PHRASE = "확인했습니다. 이슈 외 정보는 없습니다. 언급된 개념은 알고 있습니다. Ask 항목을 포함한 모든 질문에 당신의 권장안을 제 답으로 삼습니다. 승인합니다, 진행하세요."
APPROVAL_WORDS = ("approve", "proceed", "continue", "accept", "yes", "승인", "진행", "계속", "예")
RECOMMENDED = "(Recommended)"


def _labels(question: dict) -> list[str]:
    return [o["label"] for o in question.get("options", [])]


def _single(labels: list[str]) -> str:
    if not labels:
        return ""
    for label in labels:
        if RECOMMENDED in label:
            return label
    for label in labels:
        if any(word in label.lower() for word in APPROVAL_WORDS):
            return label
    return labels[0]


def answer(questions: list[dict]) -> dict[str, str]:
    out = {}
    for q in questions:
        labels = _labels(q)
        recommended = [label for label in labels if RECOMMENDED in label]
        if q.get("multiSelect") and recommended:
            out[q["question"]] = ", ".join(recommended)
        else:
            out[q["question"]] = _single(labels)
    return out


def on_idle(phrases_sent: int, tool_calls_since_phrase: int, max_user_turns: int) -> tuple[str, str | None]:
    if phrases_sent == 0:
        return "send", PHRASE
    if tool_calls_since_phrase == 0:
        return "stop", "completed"
    if phrases_sent >= max_user_turns:
        return "stop", "stalled"
    return "send", PHRASE
