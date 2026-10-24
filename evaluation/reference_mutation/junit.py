import html
import re
import xml.etree.ElementTree as ET

from .languages import LANGUAGES

_RANK = {"pass": 0, "skip": 1, "fail": 2, "error": 3}
_CHAIN_SEP = " > "


class JunitError(ValueError):
    pass


def _status(case: ET.Element) -> str:
    tags = {child.tag for child in case}
    if "error" in tags:
        return "error"
    if "failure" in tags:
        return "fail"
    if "skipped" in tags:
        return "skip"
    return "pass"


def _compose(file: str, suite: list[str], name: str) -> str:
    return "::".join([p for p in [file, *suite, name] if p])


def _python_id(case: ET.Element, ancestors: list) -> str:
    classname, name = case.get("classname", ""), case.get("name", "")
    file = (case.get("file") or "").replace("\\", "/")
    parts = [p for p in classname.split(".") if p]
    if file:
        module = file[:-3] if file.endswith(".py") else file
        mod_parts = module.split("/")
        if parts[:len(mod_parts)] == mod_parts:
            return _compose(file, parts[len(mod_parts):], name)
        return _compose(file, [], name) if not parts else _compose(file, parts[-1:], name)
    split = next((i for i, p in enumerate(parts) if p[:1].isupper()), len(parts))
    module, classes = parts[:split], parts[split:]
    return _compose("/".join(module) + ".py" if module else "", classes, name)


_ROOT_SUITES = ("Root Suite", "")


def _pathlike(text: str) -> bool:
    return "/" in text or bool(re.search(r"\.(?:[cm]?[jt]sx?)$", text))


def _typescript_id(case: ET.Element, ancestors: list) -> str:
    classname, name = case.get("classname", ""), case.get("name", "")
    if _pathlike(classname) or "::" in classname:
        if "::" in classname:
            file, chain = classname.split("::", 1)
            return _compose(file, chain.split(_CHAIN_SEP) if chain else [], name)
        pieces = name.split(_CHAIN_SEP)
        return _compose(classname, pieces[:-1], pieces[-1])
    # mocha-junit-reporter and the Node test runner: file and describe chain come from the suites.
    file_index = next((i for i, a in enumerate(ancestors) if a.get("file") or _pathlike(a.get("name", ""))), None)
    file, start = "", 0
    if file_index is not None:
        holder = ancestors[file_index]
        file = holder.get("file") or holder.get("name", "")
        start = file_index + (0 if holder.get("file") else 1)
    chain = [a.get("name", "") for a in ancestors[start:] if a.get("name", "") not in _ROOT_SUITES]
    title = classname if classname and name != classname and name.endswith(classname) else name
    return _compose(file, chain, title)


def _go_id(case: ET.Element, ancestors: list) -> str:
    suite = ancestors[-1].get("name", "") if ancestors else ""
    return _compose(case.get("classname", "") or suite, [], case.get("name", ""))


_rust_id = _go_id


_ID = {"python": _python_id, "typescript": _typescript_id, "go": _go_id, "rust": _rust_id}
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def parse(xml_text: str, *, language: str) -> dict[str, str]:
    if language not in LANGUAGES:
        raise ValueError(f"unsupported language: {language}")
    if not isinstance(xml_text, str):
        raise JunitError("junit input must be text")
    try:
        root = ET.fromstring(_CONTROL.sub("", xml_text))
    except (ET.ParseError, ValueError, RecursionError) as exc:
        raise JunitError(f"malformed junit xml: {exc}") from exc
    if root.tag not in ("testsuites", "testsuite"):
        raise JunitError(f"unexpected root element: {root.tag}")
    make_id = _ID[language]
    if language == "typescript" and root.tag == "testsuites" and root.get("name") == "jest tests":
        inner = make_id
        make_id = lambda case, ancestors: html.unescape(inner(case, ancestors))
    out: dict[str, str] = {}

    stack = [(root, [root] if root.tag == "testsuite" else [])]
    while stack:
        node, ancestors = stack.pop()
        for child in node:
            if child.tag == "testsuite":
                stack.append((child, [*ancestors, child]))
            elif child.tag == "testcase":
                test_id, status = make_id(child, ancestors), _status(child)
                if test_id not in out or _RANK[status] > _RANK[out[test_id]]:
                    out[test_id] = status
    return out
