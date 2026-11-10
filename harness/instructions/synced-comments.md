## Shared Comment & Docstring Synchronization Rules

Apply when an identical comment or docstring must be maintained across multiple locations:

1. Synced ID: a random 48-bit hex ID (12 hex characters, e.g., a1b2c3d4e5f6).
2. Tracking file: `agent-docs/synced-comments/<synced_id>.md`. `code_hash` hashes the participating files' contents with comments stripped, concatenated in alphanumeric filename order:
   ````
   ---
   version: 1
   count: <number of associated code locations>
   code_hash: <hash of participating files' non-comment content>
   ---

   # Content
   <Write the shared comment or docstring here>

   # Version Log
   ## v1 Log
   - Initial creation.
   ````
3. Code tag: every associated code location includes `synced id: <synced_id>, version: <n>, count: <n>`.
4. Update: when the shared text is edited, or a code change alters the recomputed `code_hash`, increment the version in the frontmatter and every code tag, recompute `code_hash`, and add a `# Version Log` entry.
5. Removal: when removing the shared content entirely,
   - remove it from every referenced code location;
   - increment the version, record the removal reason in the version log, and add `obsolete: true` to the frontmatter.
