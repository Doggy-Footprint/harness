import posixpath
import re

ROOT = "/testbed"
_ASSIGN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_PYTHON = re.compile(r"python(\d+(\.\d+)*)?")
_LITERAL = re.compile(
    r'''"""(?:\\.|[^\\])*?"""|\'\'\'(?:\\.|[^\\])*?\'\'\'|"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*\''''
)
_MODE = re.compile(r"[rwxabt+U]+")
_EXT = re.compile(r"\.[A-Za-z0-9]+$")
_WRITE_REDIRECTS = {">", ">>", ">|", "&>", "&>>"}
_DUP_TARGET = re.compile(r"\d+-?|-")
_READERS = {"cat", "head", "tail", "less", "more", "nl", "grep", "egrep", "rg", "awk", "sed", "diff", "wc"}
_PATTERN_FIRST = {"grep", "egrep", "rg", "awk", "sed"}
_ARG_FLAGS = {
    "head": {"-n", "-c"},
    "tail": {"-n", "-c"},
    "grep": {"-A", "-B", "-C", "-m", "-e", "-f"},
    "egrep": {"-A", "-B", "-C", "-m", "-e", "-f"},
    "rg": {"-A", "-B", "-C", "-m", "-e", "-f", "-g", "-t", "-T", "--glob"},
    "awk": {"-F", "-v", "-f"},
    "sed": {"-e", "-f", "--expression", "--file"},
}
_SCRIPT_FLAGS = {
    "grep": {"-e", "-f", "--regexp", "--file"},
    "egrep": {"-e", "-f", "--regexp", "--file"},
    "rg": {"-e", "-f", "--regexp", "--file"},
    "awk": {"-f"},
    "sed": {"-e", "-f", "--expression", "--file"},
}
_TEST_COMMANDS = {"pytest", "py.test", "tox", "nox"}
_TEST_MODULES = {"pytest", "unittest", "tox"}
_TIMEOUT_VALUE_FLAGS = {"-s", "-k", "--signal", "--kill-after"}
_PY_VALUE_FLAGS = {"-W", "-X"}


class _Heredoc:
    def __init__(self, delim: str, dash: bool):
        self.delim, self.dash, self.body = delim, dash, ""


class _Segment:
    def __init__(self):
        self.words: list[str] = []
        self.redirs: list[tuple[str, str]] = []
        self.heredocs: list[_Heredoc] = []
        self.assign_prefix = True

    def empty(self) -> bool:
        return not (self.words or self.redirs or self.heredocs)


class _Lexer:
    def __init__(self, command: str):
        self.s = command
        self.i = 0
        self.vars: dict[str, str] = {}
        self.segments: list[_Segment] = []
        self.seg = _Segment()
        self.buf: list[str] = []
        self.in_word = False
        self.pending_redir: str | None = None
        self.pending_heredocs: list[_Heredoc] = []
        self.unknown = False

    def end_word(self) -> None:
        if not self.in_word:
            return
        text = "".join(self.buf)
        self.buf, self.in_word = [], False
        if self.pending_redir is not None:
            self.seg.redirs.append((self.pending_redir, text))
            self.pending_redir = None
            return
        seg = self.seg
        assignment = _ASSIGN.match(text)
        if assignment and (seg.assign_prefix or seg.words[0] in ("export", "local", "declare", "readonly")):
            name, value = text[: assignment.end() - 1], text[assignment.end():]
            if "$(" not in value and "`" not in value:
                self.vars[name] = value
        elif not (seg.words and seg.words[0] in ("export", "local", "declare", "readonly")):
            seg.assign_prefix = False
        seg.words.append(text)

    def end_segment(self) -> None:
        self.end_word()
        if self.pending_redir is not None:
            self.unknown = True
            self.pending_redir = None
        if not self.seg.empty():
            self.segments.append(self.seg)
        self.seg = _Segment()

    def add(self, text: str) -> None:
        self.buf.append(text)
        self.in_word = True

    def skip_balanced(self, start: int, open_ch: str, close_ch: str) -> int:
        depth, j = 0, start
        while j < len(self.s):
            if self.s[j] == open_ch:
                depth += 1
            elif self.s[j] == close_ch:
                depth -= 1
                if depth == 0:
                    return j + 1
            j += 1
        self.unknown = True
        return j

    def dollar(self, quoted: bool) -> None:
        s, i = self.s, self.i
        nxt = s[i + 1] if i + 1 < len(s) else ""
        if nxt == "(":
            end = self.skip_balanced(i + 1, "(", ")")
            self.add(s[i:end])
            self.i = end
            return
        if nxt == "{":
            end = s.find("}", i)
            end = len(s) if end == -1 else end + 1
            body = s[i + 2: end - 1]
            if _NAME.fullmatch(body) and body in self.vars:
                self.expand(self.vars[body], quoted)
            else:
                self.add(s[i:end])
            self.i = end
            return
        m = _NAME.match(s, i + 1)
        if m is None:
            self.add("$")
            self.i = i + 1
            return
        if m.group() in self.vars:
            self.expand(self.vars[m.group()], quoted)
        else:
            self.add(s[i: m.end()])
        self.i = m.end()

    def expand(self, value: str, quoted: bool) -> None:
        if quoted:
            self.add(value)
            return
        for piece in re.split(r"(\s+)", value):
            if piece.isspace():
                self.end_word()
            elif piece:
                self.add(piece)

    def single(self) -> None:
        end = self.s.find("'", self.i + 1)
        if end == -1:
            self.unknown = True
            self.in_word = True
            self.i = len(self.s)
            return
        self.add(self.s[self.i + 1: end])
        self.i = end + 1

    def double(self) -> None:
        s = self.s
        self.i += 1
        self.in_word = True
        while self.i < len(s):
            c = s[self.i]
            if c == '"':
                self.i += 1
                return
            if c == "\\" and self.i + 1 < len(s) and s[self.i + 1] in '"\\$`\n':
                if s[self.i + 1] != "\n":
                    self.add(s[self.i + 1])
                self.i += 2
            elif c == "$":
                self.dollar(True)
            elif c == "`":
                end = s.find("`", self.i + 1)
                end = len(s) if end == -1 else end + 1
                self.add(s[self.i:end])
                self.i = end
            else:
                self.add(c)
                self.i += 1
        self.unknown = True

    def redirect(self, c: str) -> None:
        s, i = self.s, self.i
        if self.in_word and "".join(self.buf).isdigit():
            self.buf, self.in_word = [], False
        else:
            self.end_word()
        if c == "<":
            if s.startswith("<<<", i):
                self.pending_redir = "<<<"
                self.i = i + 3
            elif s.startswith("<<", i):
                self.i = i + 2
                self.heredoc()
            elif s.startswith("<&", i):
                self.pending_redir = "<&"
                self.i = i + 2
            else:
                self.pending_redir = "<"
                self.i = i + 1
            return
        for op in (">>", ">|", ">&", ">"):
            if s.startswith(op, i):
                self.pending_redir = op
                self.i = i + len(op)
                return

    def heredoc(self) -> None:
        s = self.s
        dash = s.startswith("-", self.i)
        self.i += dash
        while self.i < len(s) and s[self.i] in " \t":
            self.i += 1
        delim = []
        while self.i < len(s) and s[self.i] not in " \t\n;&|<>()":
            c = s[self.i]
            if c in "'\"":
                end = s.find(c, self.i + 1)
                if end == -1:
                    self.unknown = True
                    self.i = len(s)
                    return
                delim.append(s[self.i + 1: end])
                self.i = end + 1
            elif c == "\\":
                delim.append(s[self.i + 1: self.i + 2])
                self.i += 2
            else:
                delim.append(c)
                self.i += 1
        if not delim:
            self.unknown = True
            return
        doc = _Heredoc("".join(delim), dash)
        self.seg.heredocs.append(doc)
        self.pending_heredocs.append(doc)

    def read_bodies(self) -> None:
        s = self.s
        for doc in self.pending_heredocs:
            lines, found = [], False
            while self.i < len(s):
                end = s.find("\n", self.i)
                line = s[self.i:] if end == -1 else s[self.i: end]
                self.i = len(s) if end == -1 else end + 1
                if (line.lstrip("\t") if doc.dash else line) == doc.delim:
                    found = True
                    break
                lines.append(line)
            doc.body = "\n".join(lines)
            self.unknown = self.unknown or not found
        self.pending_heredocs = []

    def run(self) -> None:
        s = self.s
        while self.i < len(s):
            c = s[self.i]
            if c == "\\":
                if s[self.i + 1: self.i + 2] != "\n":
                    self.add(s[self.i + 1: self.i + 2])
                self.i += 2
            elif c == "'":
                self.single()
            elif c == '"':
                self.double()
            elif c == "`":
                end = s.find("`", self.i + 1)
                end = len(s) if end == -1 else end + 1
                self.add(s[self.i:end])
                self.i = end
            elif c == "$":
                if s.startswith("$'", self.i):
                    self.i += 1
                    self.single()
                else:
                    self.dollar(False)
            elif c == "#" and not self.in_word:
                end = s.find("\n", self.i)
                self.i = len(s) if end == -1 else end
            elif c in " \t\r":
                self.end_word()
                self.i += 1
            elif c == "\n":
                self.end_segment()
                self.i += 1
                self.read_bodies()
            elif c in ";()|":
                self.end_segment()
                self.i += 1
            elif c == "&":
                if s.startswith("&>", self.i):
                    self.end_word()
                    op = "&>>" if s.startswith("&>>", self.i) else "&>"
                    self.pending_redir = op
                    self.i += len(op)
                else:
                    self.end_segment()
                    self.i += 1
            elif c in "<>":
                self.redirect(c)
            else:
                self.add(c)
                self.i += 1
        self.end_segment()
        if self.pending_heredocs:
            self.unknown = True


def _path_like(text: str) -> bool:
    return bool(text) and not re.search(r"\s", text) and ("/" in text or bool(_EXT.search(text)))


def _unquote(literal: str) -> str:
    for q in ('"""', "'''", '"', "'"):
        if literal.startswith(q):
            return literal[len(q): -len(q)]
    return literal


def _open_modes(code: str) -> tuple[bool, bool]:
    writes = bool(re.search(r"\.write_(text|bytes)\(", code))
    reads = bool(re.search(r"\.read_(text|bytes)\(", code))
    for m in re.finditer(r"\bopen\(", code):
        depth, end = 1, m.end()
        while end < len(code) and depth:
            depth += (code[end] == "(") - (code[end] == ")")
            end += 1
        call = code[m.end(): end]
        literals = [_unquote(x.group()) for x in _LITERAL.finditer(call)]
        first_is_literal = bool(re.match(r"\s*[rbufRBUF]{0,2}['\"]", call))
        method = m.start() > 0 and code[m.start() - 1] == "."
        candidates = literals if method or not first_is_literal else literals[1:]
        modes = [x for x in candidates if _MODE.fullmatch(x) and re.search(r"[rwxa+]", x)]
        if any(re.search(r"[wax+]", x) for x in modes):
            writes = True
        else:
            reads = True
    return writes, reads


class _Analysis:
    def __init__(self, result: dict):
        self.result = result
        self.cwd: str | None = ROOT

    def norm(self, path) -> str | None:
        if not isinstance(path, str) or not path or path.startswith("~"):
            return None
        if path.startswith("/"):
            full = posixpath.normpath(path)
        elif self.cwd is None:
            self.result["unknown"] = True
            return None
        else:
            full = posixpath.normpath(posixpath.join(self.cwd, path))
        return full[len(ROOT) + 1:] if full.startswith(ROOT + "/") else None

    def put(self, key: str, paths) -> None:
        for p in paths:
            norm = self.norm(p)
            if norm is not None and norm not in self.result[key]:
                self.result[key].append(norm)

    def mention(self, args) -> None:
        paths = []
        for a in args:
            if a.startswith("-"):
                if "=" not in a:
                    continue
                a = a.split("=", 1)[1]
            paths += [p for p in (a.split() if len(a.split()) > 1 else [a]) if "/" in p or "." in p]
        self.put("mentions", paths)

    def chdir(self, args) -> None:
        rest = [a for a in args if a not in ("-P", "-L", "--")]
        if not rest or rest[0] == "-" or rest[0].startswith("~") or "$" in rest[0]:
            self.cwd = None
            self.result["unknown"] = True
        elif rest[0].startswith("/"):
            self.cwd = posixpath.normpath(rest[0])
        elif self.cwd is not None:
            self.cwd = posixpath.normpath(posixpath.join(self.cwd, rest[0]))

    @staticmethod
    def positional(args, name: str) -> tuple[list[str], bool]:
        value_flags = _ARG_FLAGS.get(name, set())
        script_flags = _SCRIPT_FLAGS.get(name, set())
        found, supplied, dd, i = [], False, False, 0
        while i < len(args):
            a = args[i]
            if dd or not a.startswith("-"):
                found.append(a)
            elif a == "--":
                dd = True
            elif a != "-":
                flag = a.split("=", 1)[0] if a.startswith("--") else a
                if flag in value_flags:
                    i += 1
                if flag in script_flags or (not a.startswith("--") and a[:2] in script_flags):
                    supplied = True
            i += 1
        return found, supplied

    def unwrap(self, words: list[str]) -> list[str]:
        while words:
            name = posixpath.basename(words[0])
            rest = words[1:]
            if name == "env":
                while rest and (rest[0].startswith("-") or _ASSIGN.match(rest[0])):
                    rest = rest[2:] if rest[0] == "-u" else rest[1:]
            elif name == "timeout":
                while rest and rest[0].startswith("-"):
                    skip = 2 if rest[0] in _TIMEOUT_VALUE_FLAGS else 1
                    rest = rest[skip:]
                rest = rest[1:]
            else:
                break
            words = rest
        return words

    def python(self, args: list[str], seg: _Segment) -> None:
        code = module = script = None
        stdin = False
        rest: list[str] = []
        i = 0
        while i < len(args):
            a = args[i]
            if a == "-c" and i + 1 < len(args):
                code, rest = args[i + 1], args[i + 2:]
                break
            if a == "-m" and i + 1 < len(args):
                module, rest = args[i + 1], args[i + 2:]
                break
            if a == "-":
                stdin, rest = True, args[i + 1:]
                break
            if a in _PY_VALUE_FLAGS:
                i += 2
                continue
            if a.startswith("-"):
                i += 1
                continue
            script, rest = a, args[i + 1:]
            break
        if module in _TEST_MODULES:
            self.result["test_runs"] += 1
            return
        if module is not None or script is not None:
            self.mention(([script] if script else []) + rest)
            return
        if code is None and (stdin or seg.heredocs):
            code = "\n".join(h.body for h in seg.heredocs) if seg.heredocs else None
        if code is None:
            self.mention(rest)
            return
        self.code(code, rest)

    def code(self, code: str, args: list[str]) -> None:
        writes, reads = _open_modes(code)
        literals = [x for x in (_unquote(m.group()) for m in _LITERAL.finditer(code)) if _path_like(x)]
        paths = literals + list(args)
        if writes:
            self.put("writes", paths)
            if not paths:
                self.result["unknown"] = True
        elif reads:
            self.put("reads", paths)
        else:
            self.mention(paths)

    def segment(self, seg: _Segment) -> None:
        words = seg.words
        k = 0
        while k < len(words) and _ASSIGN.match(words[k]):
            k += 1
        for op, target in seg.redirs:
            if op in _WRITE_REDIRECTS or (op == ">&" and not _DUP_TARGET.fullmatch(target)):
                self.put("writes", [target])
            elif op not in (">&", "<&", "<<<"):
                self.mention([target])
        words = self.unwrap(words[k:])
        if not words:
            return
        name, args = posixpath.basename(words[0]), words[1:]
        if name == "cd":
            self.chdir(args)
        elif name in _TEST_COMMANDS:
            self.result["test_runs"] += 1
        elif _PYTHON.fullmatch(name):
            self.python(args, seg)
        elif name == "tee":
            self.put("writes", self.positional(args, name)[0])
        elif name == "sed" and any(re.match(r"-[A-Za-z]*i", a) or a.startswith("--in-place") for a in args):
            found, supplied = self.positional(args, name)
            self.put("writes", found if supplied else found[1:])
        elif name in _READERS:
            found, supplied = self.positional(args, name)
            self.put("reads", found if supplied or name not in _PATTERN_FIRST else found[1:])
        elif name in ("cp", "mv", "install"):
            found = self.positional(args, name)[0]
            if len(found) >= 2:
                self.put("writes", found[-1:])
        elif name == "patch" or self.git_unknown(name, args):
            self.result["unknown"] = True
        elif not seg.redirs or any(op not in _WRITE_REDIRECTS for op, _ in seg.redirs):
            self.mention(args)

    @staticmethod
    def git_unknown(name: str, args: list[str]) -> bool:
        if name != "git":
            return False
        i = 0
        while i < len(args) and args[i].startswith("-"):
            i += 2 if args[i] in ("-C", "-c") else 1
        sub = args[i] if i < len(args) else ""
        return sub in ("apply", "restore") or (sub == "checkout" and "--" in args[i + 1:])


def _empty() -> dict:
    return {"writes": [], "reads": [], "test_runs": 0, "mentions": [], "unknown": False}


def classify(command) -> dict:
    result = _empty()
    if not isinstance(command, str):
        return result
    try:
        lexer = _Lexer(command)
        lexer.run()
        result["unknown"] = lexer.unknown
        analysis = _Analysis(result)
        for seg in lexer.segments:
            analysis.segment(seg)
    except Exception:
        result["unknown"] = True
    return result
