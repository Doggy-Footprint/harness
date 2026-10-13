MOD = (
    "diff --git a/pkg/mod.py b/pkg/mod.py\n"
    "index 1111111..2222222 100644\n"
    "--- a/pkg/mod.py\n"
    "+++ b/pkg/mod.py\n"
    "@@ -1,4 +1,5 @@\n"
    " line1\n"
    "-line2\n"
    "+line2 changed\n"
    "+diff --git a/fake b/fake\n"
    " line3\n"
    " line4\n"
)
MOD_BASE = "line1\nline2\nline3\nline4\n"
MOD_POST = "line1\nline2 changed\ndiff --git a/fake b/fake\nline3\nline4\n"

NEW = (
    "diff --git a/pkg/new.py b/pkg/new.py\n"
    "new file mode 100644\n"
    "index 0000000..3333333\n"
    "--- /dev/null\n"
    "+++ b/pkg/new.py\n"
    "@@ -0,0 +1,3 @@\n"
    "+a\n"
    "+b\n"
    "+c\n"
)
NEW_POST = "a\nb\nc\n"

DEL = (
    "diff --git a/pkg/old.py b/pkg/old.py\n"
    "deleted file mode 100644\n"
    "index 4444444..0000000\n"
    "--- a/pkg/old.py\n"
    "+++ /dev/null\n"
    "@@ -1,2 +0,0 @@\n"
    "-x\n"
    "-y\n"
)
DEL_BASE = "x\ny\n"

RENAME_EDIT = (
    "diff --git a/pkg/before.py b/pkg/after.py\n"
    "similarity index 80%\n"
    "rename from pkg/before.py\n"
    "rename to pkg/after.py\n"
    "index 5555555..6666666 100644\n"
    "--- a/pkg/before.py\n"
    "+++ b/pkg/after.py\n"
    "@@ -1,3 +1,3 @@\n"
    " p\n"
    "-q\n"
    "+Q\n"
    " r\n"
)
RENAME_EDIT_BASE = "p\nq\nr\n"
RENAME_EDIT_POST = "p\nQ\nr\n"

RENAME_PURE = (
    "diff --git a/old_name.py b/new_name.py\n"
    "similarity index 100%\n"
    "rename from old_name.py\n"
    "rename to new_name.py\n"
)

MULTI = (
    "diff --git a/pkg/multi.py b/pkg/multi.py\n"
    "index 7777777..8888888 100644\n"
    "--- a/pkg/multi.py\n"
    "+++ b/pkg/multi.py\n"
    "@@ -1,3 +1,4 @@\n"
    " a\n"
    "+a2\n"
    " b\n"
    " c\n"
    "@@ -10,3 +11,3 @@\n"
    " j\n"
    "-k\n"
    "+K\n"
    " l\n"
)

NOEOL = (
    "diff --git a/pkg/noeol.py b/pkg/noeol.py\n"
    "index 9999999..aaaaaaa 100644\n"
    "--- a/pkg/noeol.py\n"
    "+++ b/pkg/noeol.py\n"
    "@@ -1,2 +1,2 @@\n"
    " first\n"
    "-last\n"
    "\\ No newline at end of file\n"
    "+LAST\n"
    "\\ No newline at end of file\n"
)
NOEOL_BASE = "first\nlast"
NOEOL_POST = "first\nLAST"

CRLF_NEW = (
    "diff --git a/pkg/b.py b/pkg/b.py\n"
    "new file mode 100644\n"
    "index 0000000..bbbbbbb\n"
    "--- /dev/null\n"
    "+++ b/pkg/b.py\n"
    "@@ -0,0 +1,3 @@\n"
    "+x = 1  \r\n"
    "+\ty = 2\n"
    "+z = 3\n"
)
CRLF_POST = "x = 1  \r\n\ty = 2\nz = 3\n"

SRC_A = (
    "diff --git a/pkg/a.py b/pkg/a.py\n"
    "index 1010101..2020202 100644\n"
    "--- a/pkg/a.py\n"
    "+++ b/pkg/a.py\n"
    "@@ -1 +1 @@\n"
    "-old\n"
    "+new\n"
)
TEST_A = (
    "diff --git a/tests/test_a.py b/tests/test_a.py\n"
    "index 3030303..4040404 100644\n"
    "--- a/tests/test_a.py\n"
    "+++ b/tests/test_a.py\n"
    "@@ -1 +1 @@\n"
    "-t_old\n"
    "+t_new\n"
)
EXCLUDED_GITIGNORE = (
    "diff --git a/.gitignore b/.gitignore\n"
    "index 5050505..6060606 100644\n"
    "--- a/.gitignore\n"
    "+++ b/.gitignore\n"
    "@@ -1 +1,2 @@\n"
    " build\n"
    "+dist\n"
)
EXCLUDED_NOTES = (
    "diff --git a/agent-docs/notes.md b/agent-docs/notes.md\n"
    "new file mode 100644\n"
    "index 0000000..7070707\n"
    "--- /dev/null\n"
    "+++ b/agent-docs/notes.md\n"
    "@@ -0,0 +1 @@\n"
    "+note\n"
)
SCRATCH = (
    "diff --git a/repro.py b/repro.py\n"
    "new file mode 100644\n"
    "index 0000000..8080808\n"
    "--- /dev/null\n"
    "+++ b/repro.py\n"
    "@@ -0,0 +1 @@\n"
    "+print(1)\n"
)
DJANGO_TEST_UTILS = (
    "diff --git a/django/test/utils.py b/django/test/utils.py\n"
    "index 9090909..a0a0a0a 100644\n"
    "--- a/django/test/utils.py\n"
    "+++ b/django/test/utils.py\n"
    "@@ -1 +1 @@\n"
    "-u_old\n"
    "+u_new\n"
)
TEST_B_NOEOL = (
    "diff --git a/tests/test_b.py b/tests/test_b.py\n"
    "index b0b0b0b..c0c0c0c 100644\n"
    "--- a/tests/test_b.py\n"
    "+++ b/tests/test_b.py\n"
    "@@ -1 +1 @@\n"
    "-b_old\n"
    "\\ No newline at end of file\n"
    "+b_new\n"
    "\\ No newline at end of file\n"
)
SETUP_MODIFIED = (
    "diff --git a/setup.py b/setup.py\n"
    "index d0d0d0d..e0e0e0e 100644\n"
    "--- a/setup.py\n"
    "+++ b/setup.py\n"
    "@@ -1 +1 @@\n"
    "-s_old\n"
    "+s_new\n"
)

EMPTY_NEW = (
    "diff --git a/pkg/empty.py b/pkg/empty.py\n"
    "new file mode 100644\n"
    "index 0000000..e69de29\n"
)
EMPTY_NEW_ROOT = (
    "diff --git a/empty_root.py b/empty_root.py\n"
    "new file mode 100644\n"
    "index 0000000..e69de29\n"
)
EMPTY_DELETED_TEST = (
    "diff --git a/tests/test_empty.py b/tests/test_empty.py\n"
    "deleted file mode 100644\n"
    "index e69de29..0000000\n"
)
MODE_ONLY = (
    "diff --git a/pkg/run.sh b/pkg/run.sh\n"
    "old mode 100644\n"
    "new mode 100755\n"
)
SPACE_PATH_NEW = (
    "diff --git a/dir b/x.py b/dir b/x.py\n"
    "new file mode 100644\n"
    "index 0000000..e69de29\n"
)
