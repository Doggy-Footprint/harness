import re
from . import candidates_path, read_json, read_jsonl, write_json, write_jsonl
from .brief import interface_signatures
from .languages import LANGUAGES, REPO_LANGUAGES, canonical, classify_path, infer_language

REASONS = (
    "ok", "bot_author", "title_excluded", "no_tests", "src_files", "src_lines", "harness_files", "binary",
)
SRC_LINES = (30, 800)
_LINKED_RE = re.compile(r"(?i)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+(?:[\w.-]+/[\w.-]+)?#(\d+)")


class GitHubError(RuntimeError):
    pass


class RateLimited(GitHubError):
    def __init__(self, message: str, reset: str = ""):
        super().__init__(message)
        self.reset = reset


def _mining(cfg: dict) -> dict:
    return cfg.get("mining", cfg)


def _login(pr: dict) -> str:
    user = pr.get("user")
    if isinstance(user, dict) and user.get("login"):
        return str(user["login"])
    return str(pr.get("author") or pr.get("author_login") or "")


def _language(pr: dict, files: list[dict], cfg: dict) -> str | None:
    for source in (pr.get("language"), cfg.get("language"), _mining(cfg).get("language")):
        if source:
            return canonical(source) or str(source).lower()
    return infer_language([f["filename"] for f in files])


def _is_binary(f: dict) -> bool:
    patch = f.get("patch")
    if f.get("binary") is True:
        return True
    if isinstance(patch, str) and ("Binary files" in patch or "GIT binary patch" in patch):
        return True
    return "patch" not in f and int(f.get("additions", 0)) + int(f.get("deletions", 0)) > 0


def _file_lines(f: dict) -> int:
    if "additions" in f or "deletions" in f:
        return int(f.get("additions", 0)) + int(f.get("deletions", 0))
    patch = f.get("patch") or ""
    return sum(1 for ln in patch.splitlines() if ln[:1] in "+-" and not ln.startswith(("+++", "---")))


def _hunked(patch: str) -> str:
    patch = patch if patch.endswith("\n") else patch + "\n"
    if patch.startswith("@@"):
        return patch
    rows = patch.splitlines()
    old = sum(1 for r in rows if r[:1] in " -")
    new = sum(1 for r in rows if r[:1] in " +")
    return f"@@ -1,{old} +1,{new} @@\n{patch}"


def _src_diff(files: list[dict]) -> str:
    return "".join(
        f"diff --git a/{f['filename']} b/{f['filename']}\n--- a/{f['filename']}\n+++ b/{f['filename']}\n"
        + _hunked(f["patch"])
        for f in files if isinstance(f.get("patch"), str)
    )


def eligible(pr: dict, files: list[dict], cfg: dict) -> tuple[bool, str]:
    mining = _mining(cfg)
    if _login(pr).endswith("[bot]"):
        return False, "bot_author"
    title = pr.get("title") or ""
    if any(re.search(p, title, re.I) for p in mining.get("title_exclude", [])):
        return False, "title_excluded"
    language = _language(pr, files, cfg)
    kinds = {f["filename"]: classify_path(language, f["filename"]) for f in files} if language else {}
    src = [f for f in files if kinds.get(f["filename"]) == "src"]
    if not any(k == "test" for k in kinds.values()):
        return False, "no_tests"
    if len(src) < 2 and not (src and language and interface_signatures(language, _src_diff(src))):
        return False, "src_files"
    lo, hi = SRC_LINES
    if not lo <= sum(_file_lines(f) for f in src) <= hi:
        return False, "src_lines"
    if any(k == "harness" for k in kinds.values()):
        return False, "harness_files"
    if any(_is_binary(f) for f in files):
        return False, "binary"
    return True, "ok"


def _call(gh_fn, endpoint: str):
    out = gh_fn([endpoint])
    if isinstance(out, dict) and str(out.get("message", "")).startswith("API rate limit exceeded"):
        raise RateLimited(out["message"])
    return out


# GitHub search serves only the first 1000 results (10 pages of 100); page 11 is HTTP 422.
SEARCH_MAX_PAGES = 10


def _repos(language: str, mining: dict, gh_fn):
    seen = set()
    for repo_language in REPO_LANGUAGES[language]:
        q = f"language:{repo_language}+stars:>={mining.get('min_stars', 200)}+fork:false+archived:false"
        for page in range(1, SEARCH_MAX_PAGES + 1):
            out = _call(gh_fn, f"search/repositories?q={q}&sort=stars&order=desc&per_page=100&page={page}")
            items = out.get("items", []) if isinstance(out, dict) else (out or [])
            for repo in items:
                if repo["full_name"] not in seen:
                    seen.add(repo["full_name"])
                    yield repo
            if len(items) < 100:
                break


def _repo_ok(repo: dict, language: str, mining: dict) -> bool:
    spdx = (repo.get("license") or {}).get("spdx_id")
    return (
        not repo.get("archived") and not repo.get("fork")
        and (repo.get("language") or REPO_LANGUAGES[language][0]).lower() in REPO_LANGUAGES[language]
        and repo.get("stargazers_count", mining.get("min_stars", 200)) >= mining.get("min_stars", 200)
        and spdx in mining.get("licenses", [])
    )


def _linked_issues(body: str, full_name: str, gh_fn) -> list[str]:
    out = []
    for number in dict.fromkeys(_LINKED_RE.findall(body or "")):
        issue = _call(gh_fn, f"repos/{full_name}/issues/{number}")
        if isinstance(issue, dict) and issue.get("body"):
            out.append(issue["body"])
    return out


def _row(language: str, full_name: str, pr: dict, files: list[dict], gh_fn) -> dict:
    kinds = [(f, classify_path(language, f["filename"])) for f in files]
    return {
        "repo": full_name, "pr": pr["number"], "language": language,
        "base_sha": pr["base"]["sha"], "merge_sha": pr["merge_commit_sha"],
        "title": pr.get("title", ""), "body": pr.get("body") or "",
        "issue_bodies": _linked_issues(pr.get("body") or "", full_name, gh_fn),
        "src_lines": sum(_file_lines(f) for f, k in kinds if k == "src"),
        "test_lines": sum(_file_lines(f) for f, k in kinds if k == "test"),
        "merged_at": pr["merged_at"],
    }


def _state_path(cfg: dict, language: str):
    return candidates_path(cfg, language).with_name("candidates.state.json")


def search(language: str, cfg: dict, *, gh_fn) -> list[dict]:
    if language not in LANGUAGES:
        raise ValueError(f"unsupported language: {language}")
    mining = _mining(cfg)
    out_path = candidates_path(cfg, language)
    rows = read_jsonl(out_path)
    done = set((read_json(_state_path(cfg, language), {}) or {}).get("done", []))
    target, per_repo = mining.get("target_per_language", 40), mining.get("per_repo_max", 3)
    cutoff = mining.get("merged_after", "2026-07-01")

    def persist() -> None:
        write_jsonl(out_path, sorted(rows, key=lambda r: (r["repo"], r["pr"])))
        write_json(_state_path(cfg, language), {"done": sorted(done)})

    try:
        for repo in _repos(language, mining, gh_fn):
            if len(rows) >= target:
                break
            name = repo["full_name"]
            if name in done or not _repo_ok(repo, language, mining):
                continue
            got: list[dict] = []
            hits = _call(
                gh_fn,
                f"search/issues?q=repo:{name}+is:pr+is:merged+merged:>={cutoff}&per_page=100",
            )
            numbers = sorted(h["number"] for h in (hits.get("items", []) if isinstance(hits, dict) else hits or []))
            for number in numbers:
                if len(got) >= per_repo or len(rows) + len(got) >= target:
                    break
                pr = _call(gh_fn, f"repos/{name}/pulls/{number}")
                if not pr.get("merged_at") or pr["merged_at"] < cutoff or not pr.get("merge_commit_sha"):
                    continue
                files = _call(gh_fn, f"repos/{name}/pulls/{number}/files?per_page=100")
                ok, _ = eligible({**pr, "language": language}, files, cfg)
                if ok:
                    got.append(_row(language, name, pr, files, gh_fn))
            rows += got
            done.add(name)
            persist()
    except RateLimited:
        persist()
        raise
    persist()
    return sorted(rows, key=lambda r: (r["repo"], r["pr"]))
