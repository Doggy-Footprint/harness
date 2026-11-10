## Shared Comment & Docstring Synchronization Rules

Apply when an identical comment or docstring must be maintained across multiple locations:

1. Synced ID: a random 48-bit hex ID (12 hex characters, e.g., a1b2c3d4e5f6).
2. Tracking file: `agent-docs/synced-comments/<synced_id>.md`. `code_hash` hashes the lines of every code block of the id: a block starts at a tag line and ends at the first later line of the same file containing `synced end: <synced_id>`; the hashed lines are those strictly between, without tag lines, end lines, and comment-only lines (by file extension; `.md` and unknown extensions strip nothing). Blocks are taken in path, then line order. Files under `agent-docs/` are not scanned.
   ````
   ---
   version: 1
   count: <number of associated code locations>
   code_hash: <hash of the lines between each tag and its end marker>
   ---

   # Content
   <Write the shared comment or docstring here>

   # Version Log
   ## v1 Log
   - Initial creation.
   ````
3. Code tag and end marker: every associated code location includes `synced id: <synced_id>, version: <n>, count: <n>` where the shared code starts and `synced end: <synced_id>` on a later line where it ends, in the same file. A tag without an end marker, or an end marker without a tag before it, blocks the commit.
4. Update: when the shared text is edited, or a code change inside a block alters `code_hash`, run `python3 .harness/bin/records.py synced-refresh <synced_id> [--reason <text>]`. It increments the version, sets `count` and `code_hash`, rewrites every tag of the id, and appends a `## v<n> Log` entry; it refuses, changing nothing, when the tracking file is missing or obsolete or a block has no end marker. Edits outside every block need no refresh.
5. Removal: when removing the shared content entirely,
   - remove it from every referenced code location;
   - increment the version, record the removal reason in the version log, and add `obsolete: true` to the frontmatter.
