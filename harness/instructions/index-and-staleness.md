## Index & Staleness Management
1. Every agent-managed directory (e.g., `agent-docs/try-n-fail`, `agent-docs/todos`) must contain `index.md`, `stale.md`, and a `stale/` directory. `agent-docs/specs/` and `agent-docs/spec-logs/` are workflow state and run records, and `agent-docs/progress/` and `agent-docs/progress-logs/` are session records, so they are exempt. `agent-docs/adr/` and `agent-docs/rejections/` from harness versions before 0.29.0, and `agent-docs/handoff/` from versions before 0.33.0, are no longer managed or checked.
2. File Naming: `<16-char-hex-id>-<kebab-case-name>.md` (e.g., `3f8a9c12b0e45d67-auth-flow.md`).
3. `index.md` Format: entries separated by `---`:
   ````
   File: <file-name>
   Summary: <one-line summary>
   Related Files: <comma-separated repo paths>
   Related Symbols: <comma-separated function/class/module names>
   ````
4. Mark a document stale with `python3 .harness/bin/records.py stale <path>`: it removes the document's entry from `index.md`, appends that index block verbatim to `stale.md`, and moves the document to `stale/`. It refuses, changing nothing, when the path is not a managed document, its entry is missing or listed twice, or the destination exists.
