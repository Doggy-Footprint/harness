"""O1: equivalence partitioning over selfcheck.bashparse.classify (spec 2974883932c47b32 v1, F1-F7, C1-C11).

Expected values are written from the spec's rules and Cases. Lists compare sorted unless an order is part of the
rule. A field a partition does not name is not asserted, except `unknown` where a partition says it is true/false.
"""
import threading
import unittest

from selfcheck import bashparse

KEYS = {"writes", "reads", "test_runs", "mentions", "unknown"}


def cls(command):
    return bashparse.classify(command)


class ClassifyCase(unittest.TestCase):
    def check(self, command, *, writes=None, reads=None, test_runs=None, mentions=None, unknown=None):
        got = cls(command)
        self.assertEqual(set(got), KEYS, command)
        if writes is not None:
            self.assertEqual(sorted(got["writes"]), sorted(writes), "writes of %r" % command)
        if reads is not None:
            self.assertEqual(sorted(got["reads"]), sorted(reads), "reads of %r" % command)
        if test_runs is not None:
            self.assertEqual(got["test_runs"], test_runs, "test_runs of %r" % command)
        if mentions is not None:
            self.assertEqual(sorted(got["mentions"]), sorted(mentions), "mentions of %r" % command)
        if unknown is not None:
            self.assertIs(got["unknown"], unknown, "unknown of %r" % command)
        return got


class SplitAndHeredocTests(ClassifyCase):
    def test_o1_p_split_every_separator_outside_quotes(self):
        cmd = "cat > a.py; cat > b.py && cat > c.py || cat > d.py\ncat > e.py & cat > f.py"
        self.check(cmd, writes=["%s.py" % c for c in "abcdef"])

    def test_o1_p_split_pipe_separates_segments(self):
        self.check("echo x | tee out.txt | cat > z.py", writes=["out.txt", "z.py"])

    def test_o1_p_split_separators_inside_quotes_do_not_split(self):
        self.check('grep "x;y && z" t/f.py', reads=["t/f.py"], writes=[])
        self.check("grep 'x | y' t/f.py", reads=["t/f.py"], writes=[])
        self.check("cat > 'a;b.py'", writes=["a;b.py"])

    def test_o1_p_heredoc_four_quote_forms_attach_body_and_never_parse_it(self):
        forms = (
            ("bare", "cat > f.py <<WORD\ncat > bad.py\nWORD\ncat > after.py"),
            ("single", "cat > f.py <<'WORD'\ncat > bad.py\nWORD\ncat > after.py"),
            ("double", 'cat > f.py <<"WORD"\ncat > bad.py\nWORD\ncat > after.py'),
            ("dash", "cat > f.py <<-WORD\ncat > bad.py\n\tWORD\ncat > after.py"),
        )
        for label, cmd in forms:
            with self.subTest(label):
                self.check(cmd, writes=["f.py", "after.py"], unknown=False)

    def test_o1_p_heredoc_body_with_separators_and_quotes_is_not_split(self):
        cmd = "cat > f.py <<'EOF'\nprint(\"unbalanced\nx; y && z | w\nEOF"
        self.check(cmd, writes=["f.py"], mentions=[], unknown=False)


class AssignmentAndVariableTests(ClassifyCase):
    def test_o1_p_assign_own_segment_and_prefix_are_expanded_later(self):
        self.check("X=a/b.py; cat > $X", writes=["a/b.py"])
        self.check("X=a/b.py true; cat > $X", writes=["a/b.py"])
        self.check("D=src; cat > ${D}/m.py", writes=["src/m.py"])
        self.check("D=src; cat > $D/m.py", writes=["src/m.py"])

    def test_o1_p_assign_c1_spec_write_with_unrecorded_variable_stays_literal(self):
        cmd = "cd /testbed; F=agent-docs/specs/$RID-x.md; cat > $F <<EOF\n---\nstatus: x\nEOF"
        self.check(cmd, writes=["agent-docs/specs/$RID-x.md"], mentions=[], unknown=False)

    def test_o1_p_var_unresolved_stays_literal_text(self):
        self.check("cat > $UNSET/x.py", writes=["$UNSET/x.py"])
        self.check("cat > $(pwd)/x.py", writes=["$(pwd)/x.py"])
        self.check("cat > ${UNSET2}/y.py", writes=["${UNSET2}/y.py"])


class CwdAndNormalizeTests(ClassifyCase):
    def test_o1_p_cd_sets_cwd_for_later_segments_only(self):
        self.check("cd src; cat > m.py", writes=["src/m.py"])
        self.check("cd /testbed/tests; cat > a.py", writes=["tests/a.py"])
        self.check("cat > before.py; cd src; cat > after.py", writes=["before.py", "src/after.py"])

    def test_o1_p_cd_each_command_starts_at_testbed(self):
        self.check("cd src; cat > m.py", writes=["src/m.py"])
        self.check("cat > m.py", writes=["m.py"])

    def test_o1_p_cd_relative_chain_accumulates(self):
        self.check("cd src && cd pkg; cat > m.py", writes=["src/pkg/m.py"])

    def test_o1_p_normalize_abs_testbed_becomes_relative(self):
        self.check("cat > /testbed/x.py", writes=["x.py"])
        self.check("cat /testbed/a/b.py", reads=["a/b.py"])

    def test_o1_p_normalize_abs_other_is_dropped(self):
        self.check("cat /etc/passwd", reads=[])
        self.check("cat > /tmp/e", writes=[])

    def test_o1_p_normalize_escape_is_dropped(self):
        self.check("cd ..; cat x", reads=[])
        self.check("cat ../x", reads=[])
        self.check("cd /testbed/..; cat > y.py", writes=[])

    def test_o1_p_normalize_dot_segments_collapse(self):
        self.check("cat ./a/../b.py", reads=["b.py"])
        self.check("cat ./a.py", reads=["a.py"])
        self.check("cd /testbed/tests; cat ../src/m.py", reads=["src/m.py"])

    def test_o1_p_normalize_returned_paths_are_str_without_leading_slash(self):
        got = cls("cat /testbed/a.py /etc/x ./b.py > /testbed/c.py")
        for key in ("writes", "reads", "mentions"):
            for path in got[key]:
                self.assertIsInstance(path, str)
                self.assertFalse(path.startswith("/"), path)


class RedirectionTests(ClassifyCase):
    def test_o1_p_redir_each_operator_is_a_write(self):
        for label, cmd in (("gt", "echo hi > a.py"), ("gtgt", "echo hi >> a.py"), ("amp", "echo hi &> a.py"),
                           ("clobber", "echo hi >| a.py"), ("nospace", "echo hi >a.py")):
            with self.subTest(label):
                self.check(cmd, writes=["a.py"])

    def test_o1_p_redir_excluded_fd_dup_dev_null_and_outside_testbed(self):
        self.check("echo hi > /dev/null; ls 2>&1; cmd 2>/tmp/e", writes=[])
        self.check("echo hi > /dev/null", writes=[])
        self.check("ls 2>&1", writes=[])


class WriteCommandTests(ClassifyCase):
    def test_o1_p_tee_every_file_argument_with_or_without_append(self):
        self.check("echo x | tee a.py b.py", writes=["a.py", "b.py"])
        self.check("echo x | tee -a c.py", writes=["c.py"])
        self.check("echo x | tee -a c.py d.py", writes=["c.py", "d.py"])

    def test_o1_p_sed_i_writes_the_files_after_the_script(self):
        for label, cmd, files in (
            ("plain", "sed -i 's/a/b/' src/m.py tests/t.py", ["src/m.py", "tests/t.py"]),
            ("suffix", "sed -i.bak 's/a/b/' f.py", ["f.py"]),
            ("long", "sed --in-place 's/a/b/' f.py", ["f.py"]),
            ("c2", "sed -i 's/x/y/' astropy/io/ascii/qdp.py", ["astropy/io/ascii/qdp.py"]),
        ):
            with self.subTest(label):
                self.check(cmd, writes=files, reads=[])

    def test_o1_p_sed_e_all_non_option_arguments_are_files(self):
        self.check("sed -i -e 's/a/b/' -e 's/c/d/' f.py g.py", writes=["f.py", "g.py"])
        self.check("sed -i -f script.sed f.py", writes=["f.py"])

    def test_o1_p_cp_mv_install_write_only_the_last_argument(self):
        self.check("cp a.py b/c.py", writes=["b/c.py"])
        self.check("mv a.py b.py", writes=["b.py"])
        self.check("install -m 644 a.py dest/b.py", writes=["dest/b.py"])


class PythonTests(ClassifyCase):
    C3 = "cd /testbed/tests; python - <<'EOF'\np='_core/test_plot.py'\ns=open(p).read()\nopen(p,'w').write(s)\nEOF"

    def test_o1_p_python_heredoc_write_c3(self):
        self.check(self.C3, writes=["tests/_core/test_plot.py"])

    def test_o1_p_python_heredoc_write_calls(self):
        for label, body, path in (
            ("open-w", "open('out/x.txt','w').write('hi')", "out/x.txt"),
            ("open-a", "open('out/y.txt', 'a').write('hi')", "out/y.txt"),
            ("open-x", "open('out/z.txt', 'x').write('hi')", "out/z.txt"),
            ("open-plus", "open('out/p.txt', 'r+').write('hi')", "out/p.txt"),
            ("write_text", "from pathlib import Path\nPath('a/b.py').write_text('x')", "a/b.py"),
            ("write_bytes", "from pathlib import Path\nPath('a/c.bin').write_bytes(b'x')", "a/c.bin"),
        ):
            with self.subTest(label):
                self.check("python3 - <<'EOF'\n%s\nEOF" % body, writes=[path], unknown=False)

    def test_o1_p_python_c_write(self):
        self.check('python -c "open(\'a/b.txt\',\'w\').write(\'x\')"', writes=["a/b.txt"])
        self.check("python3 -c 'open(\"a/b.txt\",\"a\").write(\"x\")'", writes=["a/b.txt"])

    def test_o1_p_python_argv_positional_arguments_after_dash_or_code(self):
        c10 = "F=agent-docs/specs/r-x.md; python3 - \"$F\" <<'EOF'\nimport sys;p=sys.argv[1];open(p,'w').write('x')\nEOF"
        got = cls(c10)
        self.assertIn("agent-docs/specs/r-x.md", got["writes"])
        self.check("python3 - a.txt b/c.txt <<'EOF'\nimport sys;open(sys.argv[1],'w')\nEOF",
                   writes=["a.txt", "b/c.txt"])
        self.check("python -c \"import sys;open(sys.argv[1],'w')\" out/f.txt", writes=["out/f.txt"])

    def test_o1_p_python_write_nopath_is_unknown(self):
        self.check("python -c \"import os; open(os.environ['X'],'w')\"", writes=[], unknown=True)
        self.check("python - <<'EOF'\nopen(p,'w')\nEOF", writes=[], unknown=True)

    def test_o1_p_python_read(self):
        self.check("python3 - <<'EOF'\nprint(open('src/a.py').read())\nEOF", reads=["src/a.py"], writes=[])
        self.check("python3 - <<'EOF'\nfrom pathlib import Path\nprint(Path('a/b.py').read_text())\nEOF",
                   reads=["a/b.py"], writes=[])
        self.check("python3 - <<'EOF'\nopen('src/r.py', 'r').read()\nEOF", reads=["src/r.py"], writes=[])

    def test_o1_p_python_without_file_access_has_no_paths(self):
        self.check("python -c \"print(1)\"", writes=[], reads=[], unknown=False)


class ReadCommandTests(ClassifyCase):
    def test_o1_p_read_cmds_each_command(self):
        cases = (
            ("cat", "cat tests/test_x.py", ["tests/test_x.py"]),
            ("head", "head -5 a/h.py", ["a/h.py"]),
            ("tail", "tail -5 a/t.py", ["a/t.py"]),
            ("less", "less a/l.py", ["a/l.py"]),
            ("more", "more a/m.py", ["a/m.py"]),
            ("nl", "nl a/n.py", ["a/n.py"]),
            ("grep", "grep -n foo tests/test_y.py", ["tests/test_y.py"]),
            ("egrep", "egrep -n 'foo|bar' a/e.py", ["a/e.py"]),
            ("rg", "rg foo a/r.py", ["a/r.py"]),
            ("awk", "awk '{print}' a/w.txt", ["a/w.txt"]),
            ("sed-no-i", "sed -n 1,5p src/impl.py", ["src/impl.py"]),
            ("diff", "diff a/x.py b/y.py", ["a/x.py", "b/y.py"]),
            ("wc", "wc -l a/c.py", ["a/c.py"]),
        )
        for label, cmd, files in cases:
            with self.subTest(label):
                self.check(cmd, reads=files, writes=[], test_runs=0)

    def test_o1_p_read_cmds_c6_both_files(self):
        self.check("cat tests/test_x.py; grep -n foo tests/test_y.py", reads=["tests/test_x.py", "tests/test_y.py"])

    def test_o1_p_read_cmds_with_redirect_target_is_write_not_read(self):
        self.check("cat a.py > b.py", reads=["a.py"], writes=["b.py"])


class TestRunTests(ClassifyCase):
    def test_o1_p_testrun_each_runner_counts_one(self):
        cases = (
            ("pytest", "pytest tests/a.py"),
            ("py.test", "py.test -q"),
            ("tox", "tox -e py"),
            ("nox", "nox -s tests"),
            ("python -m pytest", "python -m pytest -q tests/a.py"),
            ("python3 -m pytest", "python3 -m pytest tests/a.py"),
            ("python -m unittest", "python -m unittest -q"),
            ("python -m tox", "python -m tox"),
            ("python -W", "python -W ignore -m pytest tests/a.py"),
        )
        for label, cmd in cases:
            with self.subTest(label):
                self.check(cmd, test_runs=1, reads=[], writes=[])

    def test_o1_p_testrun_c4_pipeline(self):
        self.check("python -m pytest -q tests/test_x.py 2>&1 | tail -1", test_runs=1, reads=[], writes=[])

    def test_o1_p_testrun_prefixes_timeout_env_assignment(self):
        self.check("timeout 600 pytest tests/a.py", test_runs=1, reads=[], writes=[])
        self.check("env pytest tests/a.py", test_runs=1, reads=[], writes=[])
        self.check("FOO=1 pytest tests/a.py", test_runs=1, reads=[], writes=[])
        self.check("timeout 600 python -m pytest tests/a.py", test_runs=1, reads=[], writes=[])

    def test_o1_eg1_timeout_option_forms(self):
        cases = (
            ("-k DUR", "timeout -k 5 600 pytest tests/a.py"),
            ("--foreground", "timeout --foreground 600 python -m pytest tests/a.py"),
            ("-s SIG", "timeout -s KILL 10 pytest tests/a.py"),
            ("long value forms", "timeout --kill-after=5 --signal=TERM 600 pytest tests/a.py"),
            ("--preserve-status -v", "timeout --preserve-status -v 60 tox tests/a.py"),
        )
        for label, cmd in cases:
            with self.subTest(label):
                got = self.check(cmd, test_runs=1, reads=[], writes=[])
                self.assertNotIn("tests/a.py", got["mentions"])
                self.assertNotIn("600", got["mentions"] + got["reads"])

    def test_o1_p_testrun_variable_expanded_c5(self):
        cmd = 'T="timeout 600 python -m pytest tests/a.py -q"; $T 2>&1 | tail -1'
        self.check(cmd, test_runs=1, reads=[], writes=[])

    def test_o1_p_testrun_each_segment_counts(self):
        self.check("pytest a.py; pytest b.py && python -m unittest", test_runs=3)

    def test_o1_p_testrun_non_runner_counts_zero(self):
        self.check("cat tests/a.py", test_runs=0)
        self.check("python -c \"print(1)\"", test_runs=0)
        self.check("echo pytest", test_runs=0)


class UnknownAndMentionTests(ClassifyCase):
    def test_o1_p_unknown_forms_set_unknown_true(self):
        for label, cmd in (
            ("git apply", "git apply p.diff"),
            ("patch", "patch -p1 < x.diff"),
            ("git checkout --", "git checkout -- src/a.py"),
            ("git restore", "git restore src/a.py"),
            ("unbalanced quote", "cat 'unterminated"),
            ("unbalanced double quote", 'cat "unterminated'),
            ("unterminated heredoc", "cat <<EOF\nno end"),
        ):
            with self.subTest(label):
                self.check(cmd, unknown=True)

    def test_o1_p_unknown_git_apply_has_no_writes(self):
        self.check("git apply p.diff", writes=[], unknown=True)

    def test_o1_p_unknown_false_for_ordinary_commands(self):
        for cmd in ("cat a.py", "ls", "git status", "git checkout main", "echo hi > a.py", "pytest a.py"):
            with self.subTest(cmd):
                self.check(cmd, unknown=False)

    def test_o1_mentions_unclassified_segment_arguments(self):
        self.check("./custom_tool tests/t.py", mentions=["tests/t.py"], reads=[], writes=[], test_runs=0)
        self.check("ls src/pkg", mentions=["src/pkg"], reads=[], writes=[])

    def test_o1_mentions_exclude_classified_segments(self):
        self.check("cat tests/a.py > b.py; pytest tests/c.py", mentions=[])


class EmptyAndMalformedTests(ClassifyCase):
    def test_o1_p_empty_string_gives_an_empty_result(self):
        got = self.check("", writes=[], reads=[], mentions=[], test_runs=0)
        self.assertIs(got["unknown"], False)

    def test_o1_p_empty_quotes_do_not_raise_and_give_no_paths(self):
        self.check('""', writes=[], reads=[], test_runs=0)

    def test_o1_p_non_string_does_not_raise_and_gives_no_paths(self):
        for value in (None, 5, b"cat a.py", ["cat", "a.py"], {"command": "cat a.py"}):
            with self.subTest(repr(value)):
                got = cls(value)
                self.assertEqual(got["writes"], [])
                self.assertEqual(got["reads"], [])


class LexerConventionTests(ClassifyCase):
    """O13 / C29: one test per F20 item (a)-(l)."""

    def guarded(self, command, seconds=5):
        box = {}

        def work():
            box["result"] = cls(command)

        thread = threading.Thread(target=work, daemon=True)
        thread.start()
        thread.join(seconds)
        self.assertFalse(thread.is_alive(), "classify did not terminate for %r" % (command,))
        return box["result"]

    def test_o13_l_a_always_terminates(self):
        for command in ("cat <<<x", "cat <&3", "cat \\a", '"a\\"', "echo \\`abc", "cat <<'EOF", "cat <<", "cat $(",
                        "cat 'a", 'cat "a', "echo `", "cat \\", "$'a", "cat <<-", "cat >", "cat >&", "cd"):
            with self.subTest(command):
                got = self.guarded(command)
                self.assertEqual(set(got), KEYS)

    def test_o13_l_b_backslash_conventions(self):
        self.check("cat \\tests/a.py", reads=["tests/a.py"])
        self.check("cat tests/\\a.py", reads=["tests/a.py"])
        self.check("cat tests/a.py \\\ntests/b.py", reads=["tests/a.py", "tests/b.py"])
        self.check('cat "tests/a\\"b.py"', reads=['tests/a"b.py'])

    def test_o13_l_c_substitution_spans_and_ansi_quotes_stay_one_word(self):
        self.check("cat `date` tests/a.py", reads=["`date`", "tests/a.py"])
        self.check("cat `echo a b`", reads=["`echo a b`"])
        self.check("cat $(date) tests/a.py", reads=["$(date)", "tests/a.py"], unknown=False)
        self.check("cat $(echo $(date) x) tests/a.py", reads=["$(echo $(date) x)", "tests/a.py"])
        self.check("cat $'tests/a b.py'", reads=["tests/a b.py"])

    def test_o13_l_d_comment_at_word_start(self):
        self.check("cat tests/a.py # tests/b.py > c.py", reads=["tests/a.py"], writes=[])
        self.check("# cat > x.py\ncat > y.py", writes=["y.py"])
        self.check("cat tests/a#b.py", reads=["tests/a#b.py"])

    def test_o13_l_e_double_dash_ends_options(self):
        self.check("cat -- -x.py tests/a.py", reads=["-x.py", "tests/a.py"])

    def test_o13_l_f_redirection_forms(self):
        for label, cmd in (("herestring", "cat <<<x"), ("herestring path", "cat <<< tests/a.py"),
                           ("dup input", "cat <&3")):
            with self.subTest(label):
                self.check(cmd, reads=[], writes=[], mentions=[])
        self.check("cat < tests/a.py", reads=[], writes=[], mentions=["tests/a.py"])
        self.check("echo hi >&out.txt", writes=["out.txt"])
        self.check("echo hi &>>out.txt", writes=["out.txt"])
        self.check("cat 12>tests/a.py", reads=[], writes=["tests/a.py"])
        self.check("echo hi 2> agent-docs/x.md", writes=["agent-docs/x.md"])
        self.check("cat << EOF\ncat tests/x.py\nEOF", reads=[], unknown=False)

    def test_o13_l_g_export_local_declare_readonly_record_the_name(self):
        for word in ("export", "local", "declare", "readonly"):
            with self.subTest(word):
                self.check("%s F=a/b.py; cat > $F" % word, writes=["a/b.py"])

    def test_o13_l_h_cd_options_and_unresolvable_targets(self):
        self.check("cd -P src; cat > a.py", writes=["src/a.py"])
        self.check("cd -L src; cat > a.py", writes=["src/a.py"])
        for label, cmd in (("tilde", "cd ~; cat > a.py"), ("unresolved variable", "cd $X; cat > a.py")):
            with self.subTest(label):
                self.check(cmd, writes=[], unknown=True)

    def test_o13_l_i_value_taking_options_are_not_arguments(self):
        cases = []
        for tool in ("head", "tail"):
            cases += [("%s -n" % tool, "%s -n 5 tests/t.py" % tool), ("%s -c" % tool, "%s -c 5 tests/t.py" % tool)]
        for tool in ("grep", "egrep", "rg"):
            cases += [("%s -e" % tool, "%s -e foo tests/t.py" % tool),
                      ("%s -f" % tool, "%s -f pats.txt tests/t.py" % tool),
                      ("%s -A" % tool, "%s -A 2 foo tests/t.py" % tool),
                      ("%s -B" % tool, "%s -B 2 foo tests/t.py" % tool),
                      ("%s -C" % tool, "%s -C 2 foo tests/t.py" % tool),
                      ("%s -m" % tool, "%s -m 1 foo tests/t.py" % tool)]
        cases += [("rg -g", "rg -g '*.py' foo tests/t.py"), ("rg -T", "rg -T py foo tests/t.py"),
                  ("rg -t", "rg -t py foo tests/t.py"),
                  ("awk -F", "awk -F : '{print}' tests/t.py"), ("awk -v", "awk -v x=1 '{print}' tests/t.py"),
                  ("awk -f", "awk -f prog.awk tests/t.py"),
                  ("sed -e", "sed -e 's/a/b/' tests/t.py"), ("sed -f", "sed -f script.sed tests/t.py")]
        for label, cmd in cases:
            with self.subTest(label):
                self.check(cmd, reads=["tests/t.py"], writes=[], unknown=False)

    def test_o13_l_i_python_env_and_git_option_values(self):
        for label, cmd in (("python -W", "python -W ignore src/x.py"), ("python -X", "python -X dev src/x.py")):
            with self.subTest(label):
                self.check(cmd, mentions=["src/x.py"], reads=[], writes=[])
        self.check("env -u FOO pytest tests/t.py", test_runs=1, reads=[], mentions=[])
        self.check("env -i python -m pytest tests/t.py", test_runs=1)
        self.check("env -i pytest tests/t.py", test_runs=1)
        for label, cmd in (("git -C", "git -C src apply p.diff"), ("git -c", "git -c color.ui=off apply p.diff"),
                           ("git --no-pager", "git --no-pager apply p.diff")):
            with self.subTest(label):
                self.check(cmd, unknown=True)
        self.check("git -C src status", unknown=False, mentions=[])
        self.check("cat tests/a.py; git --version", reads=["tests/a.py"], unknown=False)

    def test_o13_l_j_long_option_values_contribute_to_mentions(self):
        self.check("ls --file=src/a.py", mentions=["src/a.py"], unknown=False)
        self.check("ls --color=auto src/a.py", mentions=["src/a.py"], unknown=False)
        self.check("ls src/a.py tests/b.py", mentions=["src/a.py", "tests/b.py"])

    def test_o13_l_k_empty_and_unterminated_arguments_count_for_last_argument_rules(self):
        self.check("cp src/a.py dst/b.py ''", writes=[])
        self.check('cp src/a.py dst/b.py ""', writes=[])
        self.check("cp src/a.py dst/b.py 'x", writes=[])

    def test_o13_l_l_python_unknown_single_dash_flags_are_skipped(self):
        self.check("python -u src/x.py", mentions=["src/x.py"], writes=[], reads=[])
        self.check("python3 -O -u src/x.py", mentions=["src/x.py"])


class LexerEvidenceGapTests(ClassifyCase):
    """Mutation-triage gaps: observable behaviours with exact fields."""

    def test_o13_reads_with_value_taking_options(self):
        for cmd in ("head -n 5 tests/t.py", "tail -n 5 tests/t.py", "grep -A 2 foo tests/t.py",
                    "grep -e foo tests/t.py", "egrep -C 2 foo tests/t.py", "egrep -m 1 foo tests/t.py",
                    "egrep -e foo tests/t.py", "egrep -f pats.txt tests/t.py", "rg -A 2 foo tests/t.py",
                    "rg -e foo tests/t.py", "rg -T py foo tests/t.py", "awk -F : '{print}' tests/t.py",
                    "awk -f prog.awk tests/t.py"):
            with self.subTest(cmd):
                self.check(cmd, reads=["tests/t.py"])

    def test_o13_unrecorded_variable_with_command_substitution_value_stays_literal(self):
        self.check("F=$(pwd)/a.md; cat > $F", writes=["$F"])

    def test_o13_unknown_flags_are_real_booleans(self):
        self.assertIs(cls("cat $(tests/a.py")["unknown"], True)
        self.assertIs(cls("cat <<")["unknown"], True)
        self.assertIs(cls("cat tests/a.py")["unknown"], False)

    def test_o13_heredoc_with_space_after_operator_does_not_parse_body(self):
        self.check("cat << EOF\ncat tests/x.py\nEOF", reads=[])

    def test_o13_python_c_write_and_read_distinctions(self):
        self.check("python -c \"open('out.txt','w').write('x')\"", writes=["out.txt"])
        self.check("python -c \"open(p).read(); print('wa')\"", writes=[], unknown=False)
        self.check("python -c \"open(f(p), 'w').write('a/b.py')\"", writes=["a/b.py"])
        self.check("python -c \"open('x', 'r').read()\"", writes=[], unknown=False)


if __name__ == "__main__":
    unittest.main()
