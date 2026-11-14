import re

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_BOLD_ITEM = re.compile(r"^\*\*\s*\d+[.)]\s*(.+?)\*\*")
_LIST_ITEM = re.compile(r"^(?:[-*+]|\d+[.)])\s+(.+)$")
_FENCES = ("```", "~~~")


def _blocks(record):
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    return content if isinstance(content, list) else []


def _is_text(block):
    return isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str)


def _is_human_prompt(record) -> bool:
    if record.get("type") != "user" or record.get("isMeta") is True or record.get("isCompactSummary") is True:
        return False
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        stripped = content.strip()
        return bool(stripped) and not stripped.startswith("<")
    if not isinstance(content, list):
        return False
    if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
        return False
    return any(_is_text(b) and b["text"].strip() and not b["text"].strip().startswith("<") for b in content)


def _is_main_assistant(record) -> bool:
    return isinstance(record, dict) and record.get("type") == "assistant" and record.get("isSidechain") is not True


def locate_brief_turn(records: list[dict], tool_use_id: str) -> str | None:
    records = [r for r in records if isinstance(r, dict)]
    found = next((
        i for i, r in enumerate(records) if _is_main_assistant(r)
        and any(isinstance(b, dict) and b.get("type") == "tool_use" and b.get("id") == tool_use_id for b in _blocks(r))
    ), None)
    if found is None:
        return None
    start = 0
    for i in range(found - 1, -1, -1):
        if _is_human_prompt(records[i]):
            start = i + 1
            break
    end = len(records)
    for i in range(found + 1, len(records)):
        if _is_human_prompt(records[i]):
            end = i
            break
    texts = []
    for record in records[start:end]:
        if not _is_main_assistant(record):
            continue
        for block in _blocks(record):
            if _is_text(block) and block["text"].strip():
                texts.append(block["text"].strip())
    return "\n\n".join(texts)


def _classify(title: str) -> str | None:
    folded = re.sub(r"[*_`]", "", title).lower()
    if "fact question" in folded or "사실 질문" in folded:
        return "fact"
    if "decision round" in folded or "결정 라운드" in folded:
        return "decision"
    if "understood" in folded or "understanding" in folded or "이해" in folded:
        return "understanding"
    return None


def _normalize(text: str) -> str:
    return " ".join(text.replace("**", "").replace("__", "").split())


def parse_brief_text(text: str) -> dict:
    lines = []
    fenced = False
    for line in text.split("\n"):
        if line.startswith(_FENCES):
            fenced = not fenced
            continue
        if not fenced:
            lines.append(line)

    headings = []
    for index, line in enumerate(lines):
        match = _HEADING.match(line)
        if match:
            headings.append((index, len(match.group(1)), _classify(match.group(2))))
    heading_at = {index for index, _, _ in headings}

    sections = []
    for position, (index, level, kind) in enumerate(headings):
        end = next((later for later, lv, _ in headings[position + 1:] if lv <= level), len(lines))
        sections.append((index, end, kind))

    understanding = None
    first = next((s for s in sections if s[2] == "understanding"), None)
    if first is not None:
        content = "\n".join(lines[first[0] + 1:first[1]]).strip()
        understanding = content or None

    questions = []
    item_sections = [s for s in sections if s[2] in ("fact", "decision")]
    has_bold = {
        s[:2]: any(_BOLD_ITEM.match(line) for line in lines[s[0] + 1:s[1]])
        for s in item_sections
    }
    for index, line in enumerate(lines):
        if index in heading_at:
            continue
        enclosing = [s for s in item_sections if s[0] < index < s[1]]
        if not enclosing:
            continue
        section = max(enclosing, key=lambda s: s[0])
        bold = _BOLD_ITEM.match(line)
        if has_bold[section[:2]]:
            match = bold
        else:
            match = None if bold else _LIST_ITEM.match(line)
        if not match:
            continue
        raw = match.group(1)
        if not bold and raw.startswith("**") and "**" in raw[2:]:
            raw = raw[2:].split("**", 1)[0]
        item = _normalize(raw)
        if item:
            questions.append({"kind": section[2], "text": item})
    return {"understanding": understanding, "questions": questions}
