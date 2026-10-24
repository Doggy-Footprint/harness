import re

LANGUAGES = ("python", "typescript", "go", "rust")

HARNESS_PREFIXES = ("agent-docs/", ".harness/", ".claude/", ".agents/", ".codex/")
HARNESS_ROOT_FILES = ("AGENTS.md", "CLAUDE.md")
SRC_EXTENSIONS = {
    "python": (".py",),
    "typescript": (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"),
    "go": (".go",),
    "rust": (".rs",),
}
TEST_SEGMENTS = {
    "python": ("tests", "test"),
    "typescript": ("__tests__", "test", "tests"),
    "go": ("testdata",),
    "rust": (),
}
CFGTEST = "#cfgtest"
REPO_LANGUAGES = {
    "python": ("python",), "typescript": ("typescript", "javascript"), "go": ("go",), "rust": ("rust",),
}
_TEST_BASENAME = {
    "python": re.compile(r"^(test_.*\.py|.*_test\.py|conftest\.py)$"),
    "typescript": re.compile(r"^.*\.(test|spec)\..*$"),
    "go": re.compile(r"^.*_test\.go$"),
    "rust": None,
}
_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")
# A hunk can start inside a test module, so its opener is not visible; git puts the nearest column-0
# line (`mod tests {` in rustfmt-formatted code) after the second `@@`, which is the only evidence left.
_RUST_TEST_MOD_HINT = re.compile(r"^\s*(?:pub\s+)?mod\s+tests?\b")


def _check(language: str) -> None:
    if language not in LANGUAGES:
        raise ValueError(f"unsupported language: {language}")


def classify_path(language: str, path: str) -> str:
    _check(language)
    if path.startswith(HARNESS_PREFIXES) or path in HARNESS_ROOT_FILES:
        return "harness"
    parts = path.split("/")
    base = parts[-1]
    if language == "rust":
        is_test = parts[0] == "tests" and len(parts) > 1
    else:
        is_test = any(p in TEST_SEGMENTS[language] for p in parts[:-1]) or bool(
            _TEST_BASENAME[language].match(base)
        )
    if is_test:
        return "test"
    if base.endswith(SRC_EXTENSIONS[language]):
        return "src"
    return "other"


def _unquote(token: str) -> str:
    if not (len(token) >= 2 and token[0] == '"' and token[-1] == '"'):
        return token
    body, out, i = token[1:-1], bytearray(), 0
    escapes = {"n": 10, "t": 9, "r": 13, '"': 34, "\\": 92, "a": 7, "b": 8, "f": 12, "v": 11}
    while i < len(body):
        ch = body[i]
        if ch == "\\" and i + 1 < len(body):
            nxt = body[i + 1]
            if nxt in "01234567":
                j = i + 1
                while j < len(body) and j < i + 4 and body[j] in "01234567":
                    j += 1
                out.append(int(body[i + 1:j], 8) & 0xFF)
                i = j
                continue
            out += bytes([escapes[nxt]]) if nxt in escapes else nxt.encode()
            i += 2
            continue
        out += ch.encode()
        i += 1
    return out.decode(errors="replace")


def _strip_prefix(path: str, prefix: str) -> str:
    return path[len(prefix):] if path.startswith(prefix) else path


def _header_paths(line: str) -> tuple[str, str]:
    rest = line[len("diff --git "):]
    if rest.startswith('"'):
        end = 1
        while end < len(rest) and not (rest[end] == '"' and rest[end - 1] != "\\"):
            end += 1
        left, right = rest[:end + 1], rest[end + 2:]
    elif ' "b/' in rest:
        left, right = rest.split(' "b/', 1)
        right = '"b/' + right
    else:
        left = right = None
        for m in re.finditer(r" b/", rest):
            cand_l, cand_r = rest[:m.start()], rest[m.start() + 1:]
            if cand_l[2:] == cand_r[2:]:
                left, right = cand_l, cand_r
                break
        if left is None:
            m = re.search(r" b/", rest)
            left, right = (rest[:m.start()], rest[m.start() + 1:]) if m else (rest, rest)
    return _strip_prefix(_unquote(left), "a/"), _strip_prefix(_unquote(right), "b/")


class Hunk:
    def __init__(self, old_start: int, new_start: int, hint: str):
        self.old_start, self.new_start, self.hint = old_start, new_start, hint
        self.ops: list[tuple[str, str]] = []


class Section:
    def __init__(self, header: list[str], old: str, new: str):
        self.header, self.old, self.new = header, old, new
        self.hunks: list[Hunk] = []
        self.tail: list[str] = []

    @property
    def path(self) -> str:
        return self.old if self.new == "/dev/null" else self.new

    def text(self) -> str:
        lines = list(self.header)
        for h in self.hunks:
            oc = sum(1 for t, _ in h.ops if t in " -")
            nc = sum(1 for t, _ in h.ops if t in " +")
            lines.append(f"@@ -{_range(h.old_start, oc)} +{_range(h.new_start, nc)} @@{h.hint}")
            lines += [t + s for t, s in h.ops]
        lines += self.tail
        return "".join(line + "\n" for line in lines)


def _range(start: int, count: int) -> str:
    return str(start) if count == 1 else f"{start},{count}"


def parse_diff(diff: str) -> list[Section]:
    sections: list[Section] = []
    cur: Section | None = None
    lines = diff.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        if line.startswith("diff --git "):
            old, new = _header_paths(line)
            cur = Section([line], old, new)
            sections.append(cur)
            continue
        if cur is None:
            continue
        m = _HUNK_RE.match(line)
        if m:
            hunk = Hunk(int(m.group(1)), int(m.group(3)), m.group(5))
            old_n = int(m.group(2)) if m.group(2) is not None else 1
            new_n = int(m.group(4)) if m.group(4) is not None else 1
            cur.hunks.append(hunk)
            while i < len(lines) and (old_n > 0 or new_n > 0 or lines[i].startswith("\\")):
                body = lines[i]
                tag = body[:1] or " "
                if tag == "\\":
                    hunk.ops.append(("\\", body[1:]))
                elif tag == " ":
                    hunk.ops.append((" ", body[1:]))
                    old_n, new_n = old_n - 1, new_n - 1
                elif tag == "-":
                    hunk.ops.append(("-", body[1:]))
                    old_n -= 1
                elif tag == "+":
                    hunk.ops.append(("+", body[1:]))
                    new_n -= 1
                else:
                    break
                i += 1
        elif cur.hunks:
            cur.tail.append(line)
        else:
            cur.header.append(line)
            if line.startswith("--- "):
                cur.old = _strip_prefix(_unquote(line[4:].split("\t")[0]), "a/")
            elif line.startswith("+++ "):
                cur.new = _strip_prefix(_unquote(line[4:].split("\t")[0]), "b/")
            elif line.startswith("rename to "):
                cur.new = line[len("rename to "):]
            elif line.startswith("rename from "):
                cur.old = line[len("rename from "):]
    return sections


def diff_paths(diff: str) -> list[str]:
    return [s.path for s in parse_diff(diff)]


def _skip_string(text: str, i: int) -> int:
    n = len(text)
    ch = text[i]
    if ch == '"':
        i += 1
        while i < n and text[i] != '"':
            i += 2 if text[i] == "\\" else 1
        return min(i + 1, n)
    if ch == "r" and re.match(r'r#*"', text[i:i + 66]):
        hashes = re.match(r"r(#*)\"", text[i:]).group(1)
        end = text.find('"' + hashes, i + 2 + len(hashes))
        return n if end == -1 else end + 1 + len(hashes)
    return i + 1


def _scan(text: str):
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        two = text[i:i + 2]
        if two == "//":
            j = text.find("\n", i)
            i = n if j == -1 else j
        elif two == "/*":
            depth, i = 1, i + 2
            while i < n and depth:
                if text[i:i + 2] == "/*":
                    depth, i = depth + 1, i + 2
                elif text[i:i + 2] == "*/":
                    depth, i = depth - 1, i + 2
                else:
                    i += 1
        elif ch == '"' or (ch == "r" and (i == 0 or not (text[i - 1].isalnum() or text[i - 1] == "_"))
                           and re.match(r'r#*"', text[i:i + 66])):
            i = _skip_string(text, i)
        elif ch == "'":
            m = re.match(r"'(?:\\.[^']*|[^\\'])'", text[i:i + 16])
            if m:
                i += m.end()
            else:
                yield i, ch
                i += 1
        else:
            yield i, ch
            i += 1


_CFG_TEST_RE = re.compile(r"#\s*\[\s*cfg\s*\(\s*test\s*\)\s*\]")
_ATTR_RE = re.compile(r"\s*#\s*!?\[[^\]]*\]")
_MOD_RE = re.compile(r"\s*(?:pub(?:\s*\([^)]*\))?\s+)?mod\s+[A-Za-z_]\w*\s*([{;])")


def _blank_comments(text: str) -> str:
    chars = list(text)
    code = {i for i, _ in _scan(text)}
    for i, ch in enumerate(text):
        if i not in code and ch != "\n":
            chars[i] = " "
    return "".join(chars)


def _rust_test_spans(text: str, open_ended: bool = False) -> list[tuple[int, int]]:
    code = _blank_comments(text)
    spans: list[tuple[int, int]] = []
    pos = 0
    while True:
        m = _CFG_TEST_RE.search(code, pos)
        if not m:
            break
        k = m.end()
        while True:
            a = _ATTR_RE.match(code, k)
            if not a:
                break
            k = a.end()
        mod = _MOD_RE.match(code, k)
        if not mod:
            pos = m.end()
            continue
        if mod.group(1) == "{":
            depth, end = 0, None
            for idx in range(mod.end() - 1, len(code)):
                if code[idx] == "{":
                    depth += 1
                elif code[idx] == "}":
                    depth -= 1
                    if depth == 0:
                        end = idx + 1
                        break
            if end is None and not open_ended:
                pos = m.end()
                continue
            end = len(code) if end is None else end
        else:
            end = mod.end()
        start = m.start()
        line_start = text.rfind("\n", 0, start) + 1
        if not text[line_start:start].strip():
            start = line_start
        tail_end = text.find("\n", end)
        if tail_end != -1 and not text[end:tail_end].strip():
            end = tail_end + 1
        spans.append((start, end))
        pos = end
    return spans


def split_rust_inline(text: str) -> tuple[str, list[str]]:
    spans = _rust_test_spans(text)
    rest, mods, last = [], [], 0
    for start, end in spans:
        rest.append(text[last:start])
        mods.append(text[start:end].rstrip("\n"))
        last = end
    rest.append(text[last:])
    return "".join(rest), mods


_TEST_ATTR = re.compile(r"^\s+#\[(?:\w+::)*test\b")


def _only_test_items(hunk: Hunk) -> bool:
    """No column-0 item in the hunk and an indented test attribute: the hunk lies inside a test module."""
    body = [text for tag, text in hunk.ops if tag != "\\"]
    flat = all(not t.strip() or t[0] in " \t}" for t in body)
    return flat and any(_TEST_ATTR.match(t) for t in body)


def _rust_module_flags(hunk: Hunk) -> list[bool]:
    flags = [False] * len(hunk.ops)
    hinted = bool(_RUST_TEST_MOD_HINT.match(hunk.hint.strip())) or _only_test_items(hunk)
    for side in ("old", "new"):
        skip = "+" if side == "old" else "-"
        idx = [k for k, (t, _) in enumerate(hunk.ops) if t not in (skip, "\\")]
        body = "\n".join(hunk.ops[k][1] for k in idx) + "\n"
        offsets, off = [], 0
        for k in idx:
            offsets.append(off)
            off += len(hunk.ops[k][1]) + 1
        spans = _rust_test_spans(body, open_ended=True)
        if hinted:
            depth, end = 0, None
            for pos, ch in _scan(body):
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth < 0:
                        end = pos
                        break
            spans.append((0, len(body) if end is None else end))
        for k, o in zip(idx, offsets):
            if any(s <= o < e for s, e in spans):
                flags[k] = True
    for k, (t, _) in enumerate(hunk.ops):
        if t == "\\" and k:
            flags[k] = flags[k - 1]
    return flags


def _pieces(hunk: Hunk, flags: list[bool], want: bool) -> list[Hunk]:
    out: list[Hunk] = []
    old_n = hunk.old_start + (0 if any(t in " -" for t, _ in hunk.ops) else 1)
    new_n = hunk.new_start + (0 if any(t in " +" for t, _ in hunk.ops) else 1)
    cur: Hunk | None = None
    for (tag, text), flag in zip(hunk.ops, flags):
        if flag == want:
            if cur is None:
                cur = Hunk(old_n, new_n, hunk.hint)
                out.append(cur)
            cur.ops.append((tag, text))
        else:
            cur = None
        if tag in " -":
            old_n += 1
        if tag in " +":
            new_n += 1
    for h in out:
        oc = sum(1 for t, _ in h.ops if t in " -")
        nc = sum(1 for t, _ in h.ops if t in " +")
        if oc == 0:
            h.old_start -= 1
        if nc == 0:
            h.new_start -= 1
    return out


def _significant(h: Hunk) -> bool:
    return any(t in "+-" for t, _ in h.ops)


def _split_rust_section(sec: Section) -> tuple[Section | None, Section | None]:
    src_hunks: list[Hunk] = []
    mod_hunks: list[Hunk] = []
    for h in sec.hunks:
        flags = _rust_module_flags(h)
        src_hunks += [p for p in _pieces(h, flags, False) if _significant(p)]
        mod_hunks += [p for p in _pieces(h, flags, True) if _significant(p)]
    if not mod_hunks:
        return sec, None
    src = None
    if src_hunks:
        src = Section(list(sec.header), sec.old, sec.new)
        src.hunks = src_hunks
    tests_header = [f"diff --git a/{sec.path}{CFGTEST} b/{sec.path}{CFGTEST}"]
    for line in sec.header[1:]:
        if line.startswith("--- "):
            line = "--- /dev/null" if sec.old == "/dev/null" else f"--- a/{sec.path}{CFGTEST}"
        elif line.startswith("+++ "):
            line = "+++ /dev/null" if sec.new == "/dev/null" else f"+++ b/{sec.path}{CFGTEST}"
        elif line.startswith(("index ", "similarity ", "rename ")):
            continue
        tests_header.append(line)
    tests = Section(tests_header, sec.old, sec.new)
    tests.hunks = mod_hunks
    return src, tests


def split_diff(language: str, diff: str) -> dict[str, str]:
    _check(language)
    parts = {"src": [], "tests": [], "harness": [], "other": []}
    key = {"harness": "harness", "test": "tests", "src": "src", "other": "other"}
    for sec in parse_diff(diff):
        kind = classify_path(language, sec.path)
        if kind == "src" and language == "rust":
            src, tests = _split_rust_section(sec)
            if src is not None:
                parts["src"].append(src.text())
            if tests is not None:
                parts["tests"].append(tests.text())
            continue
        parts[key[kind]].append(sec.text())
    return {k: "".join(v) for k, v in parts.items()}


def changed_lines(diff: str) -> dict[str, set[int]]:
    out: dict[str, set[int]] = {}
    for sec in parse_diff(diff):
        if sec.new == "/dev/null":
            continue
        for h in sec.hunks:
            n = h.new_start
            for tag, _ in h.ops:
                if tag == "+":
                    out.setdefault(sec.new, set()).add(n)
                if tag in " +":
                    n += 1
    return out


def canonical(name: str) -> str | None:
    lowered = str(name).lower()
    return next((lang for lang, names in REPO_LANGUAGES.items() if lowered in names), None)


def infer_language(paths: list[str]) -> str | None:
    counts: dict[str, int] = {}
    for path in paths:
        for lang, exts in SRC_EXTENSIONS.items():
            if path.endswith(exts):
                counts[lang] = counts.get(lang, 0) + 1
    return max(counts, key=lambda k: (counts[k], k)) if counts else None


INLINE_TESTS = {"rust": split_rust_inline}


def split_inline(language: str, text: str) -> tuple[str, list[str]]:
    splitter = INLINE_TESTS.get(language)
    return splitter(text) if splitter else (text, [])


def base_test_name(language: str, test_id: str) -> str:
    name = test_id.rsplit("::", 1)[-1].split("[", 1)[0]
    return name.split("/", 1)[0] if language == "go" else name


def id_matches_file(language: str, id_file: str, path: str) -> bool:
    path = path.replace(CFGTEST, "")
    if id_file == path:
        return True
    return language == "go" and id_file.endswith(path.rsplit("/", 1)[0] if "/" in path else id_file)
