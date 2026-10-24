from .languages import CFGTEST, INLINE_TESTS, classify_path, diff_paths, split_inline


def _paths(entry: dict, *parts: str) -> list[str]:
    return [p for part in parts for p in diff_paths((entry.get("split") or {}).get(part, ""))]


def _text(entry: dict, path: str) -> str | None:
    after = entry.get("after") or {}
    if path in after:
        return after[path]
    return (entry.get("base") or {}).get(path)


def _compose(language: str, impl: dict, tests: dict) -> dict[str, str | None]:
    tree: dict[str, str | None] = {}
    for path in _paths(impl, "src", "other"):
        text = (impl.get("after") or {}).get(path)
        if text is not None and language in INLINE_TESTS and classify_path(language, path) == "src":
            text = split_inline(language, text)[0]
        tree[path] = text
    inline: list[str] = []
    for path in _paths(tests, "tests"):
        if path.endswith(CFGTEST):
            inline.append(path[: -len(CFGTEST)])
        else:
            tree[path] = (tests.get("after") or {}).get(path)
    if language in INLINE_TESTS:
        for path in dict.fromkeys(inline):
            current = tree[path] if path in tree else _text(impl, path)
            if current is None:
                continue
            rest = split_inline(language, current)[0].rstrip("\n") + "\n"
            mods = split_inline(language, _text(tests, path) or "")[1]
            tree[path] = rest + ("\n" + "\n\n".join(mods) + "\n" if mods else "")
    return tree


def hidden_tree(language: str, gold: dict, agent: dict) -> dict[str, str | None]:
    return _compose(language, agent, gold)


def validity_tree(language: str, gold: dict, agent: dict) -> dict[str, str | None]:
    return _compose(language, gold, agent)


def cross_tree(language: str, gold: dict, impl: dict, tests: dict) -> dict[str, str | None]:
    return _compose(language, impl, tests)
