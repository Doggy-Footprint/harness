import ast

from . import evaluate, patches, score

LEVELS = ("gold", "stripped", "existing", "empty")
_SUPPRESS = "contextlib.suppress(BaseException)"


def _is_assert_call(call: ast.Call) -> bool:
    f = call.func
    if isinstance(f, ast.Attribute):
        return f.attr.startswith("assert")
    return isinstance(f, ast.Name) and f.id.startswith("assert_")


def _is_raises_call(node: ast.AST) -> bool:
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
        return False
    attr = node.func.attr
    return attr in ("raises", "warns") or attr.startswith(("assertRaises", "assertWarns"))


def _segment(src: patches.SourceView, node: ast.AST) -> str:
    a, b = src.span(node)
    return src.text(a, b)


def strip_assertions(source: str) -> str:
    tree = ast.parse(source)
    src = patches.SourceView(source)
    edits: list[tuple[int, int, str]] = []
    uses_contextlib = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Assert):
            text = _segment(src, node.test)
            if "\n" in text:
                text = f"({text})"
            a, b = src.span(node)
            edits.append((a, b, text))
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and _is_assert_call(node.value):
            call = node.value
            parts = [_segment(src, x) for x in call.args] + [_segment(src, k.value) for k in call.keywords]
            if not parts:
                text = "()"
            elif len(parts) == 1:
                text = f"({parts[0]},)"
            else:
                text = f"({', '.join(parts)})"
            a, b = src.span(node)
            edits.append((a, b, text))
        elif isinstance(node, ast.withitem) and _is_raises_call(node.context_expr):
            a, b = src.span(node.context_expr)
            edits.append((a, b, _SUPPRESS))
            uses_contextlib = True
    data = src.data
    for a, b, text in sorted(edits, reverse=True):
        data = data[:a] + text.encode("utf-8") + data[b:]
    out = data.decode("utf-8")
    if uses_contextlib:
        out = _insert_import(out)
    ast.parse(out)
    return out


def _insert_import(text: str) -> str:
    # `from __future__` imports and the module docstring must stay first.
    tree = ast.parse(text)
    end_line = 0
    for i, node in enumerate(tree.body):
        is_doc = i == 0 and isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
        is_future = isinstance(node, ast.ImportFrom) and node.module == "__future__"
        if not (is_doc or is_future):
            break
        end_line = node.end_lineno
    lines = text.splitlines(keepends=True)
    head = "".join(lines[:end_line])
    if head and not head.endswith("\n"):
        head += "\n"
    return head + "import contextlib\n" + "".join(lines[end_line:])


def ladder_predictions(instance: dict, *, read_files_fn=evaluate.read_files) -> dict[str, dict]:
    test_patch = instance["test_patch"]
    paths = [s["path"] for s in patches.file_sections(test_patch)]
    base = read_files_fn(instance, "", paths)
    post = patches.apply_to_texts(base, test_patch)

    stripped_post = {
        p: strip_assertions(t) if p.endswith(".py") and t is not None else t
        for p, t in ((p, post.get(p)) for p in paths)
    }
    stripped = patches.diff_texts({p: base.get(p) for p in paths}, stripped_post)

    existing_base = {p: base[p] for p in paths if p.endswith(".py") and base.get(p) is not None}
    existing_new = {
        p: t + ("" if t.endswith("\n") or not t else "\n") + "# selfcheck\n"
        for p, t in existing_base.items()
    }
    existing = patches.diff_texts(existing_base, existing_new)

    def pred(src, tests):
        return {"instance_id": instance["instance_id"], "src_diff": src, "test_patch": tests}

    return {
        "gold": pred(instance["patch"], test_patch),
        "stripped": pred(instance["patch"], stripped),
        "existing": pred(instance["patch"], existing),
        "empty": pred("", ""),
    }


def _primary(s: dict) -> float:
    return s["kill"]["primary"] or 0.0


def check_ladder(scores: dict[str, dict]) -> dict:
    g, st, ex, em = (scores[k] for k in LEVELS)
    violations = []
    if not g["resolved"]:
        violations.append("gold_not_resolved")
    if em["resolved"]:
        violations.append("empty_resolved")
    if not g["swt"]["success"]:
        violations.append("gold_swt_failed")
    if ex["swt"]["success"]:
        violations.append("existing_swt_success")
    if em["swt"]["success"]:
        violations.append("empty_swt_success")
    if _primary(g) == 0:
        violations.append("gold_kill_zero")
    if not (_primary(g) >= _primary(st) >= _primary(ex) == _primary(em) == 0):
        violations.append("kill_order")
    return {"monotonic": not violations, "violations": violations}


def calibrate_instance(
    instance: dict,
    *,
    validation: dict,
    mutants: list[dict],
    score_fn=score.score_prediction,
    read_files_fn=evaluate.read_files,
) -> dict:
    preds = ladder_predictions(instance, read_files_fn=read_files_fn)
    levels = {
        name: score_fn(instance, preds[name], validation=validation, mutants=mutants)
        for name in LEVELS
    }
    return {"instance_id": instance["instance_id"], "levels": levels, **check_ladder(levels)}
