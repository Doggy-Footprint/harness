"""Independent oracle for spec f0e1103f974f1301 v2 (VO1-VO8, VO10).

Expected values are hand-written from the spec's FR/rule tables/Cases; the
scanner is only driven through its CLI (python3 harness/bin/test_scan.py PATH).
VO9 lives in tests/test_installer.py; VO11 is a review procedure.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCANNER = REPO_ROOT / "harness" / "bin" / "test_scan.py"


def run_scan(root, env=None):
    return subprocess.run(
        [sys.executable, str(SCANNER), str(root)],
        capture_output=True,
        text=True,
        env=env,
    )


class ScanTestCase(unittest.TestCase):
    def tmp(self):
        handle = tempfile.TemporaryDirectory()
        self.addCleanup(handle.cleanup)
        return Path(handle.name).resolve()

    def write(self, root, rel, content=""):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    def scan(self, root):
        result = run_scan(root)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        return json.loads(result.stdout)

    def file_entry(self, data, path):
        matches = [f for f in data["files"] if f["path"] == path]
        self.assertEqual(len(matches), 1, f"{path} in {[f['path'] for f in data['files']]}")
        return matches[0]

    def entry_tests(self, data, path):
        return sorted(self.file_entry(data, path)["tests"], key=lambda t: t["line"])

    def name_lines(self, data, path):
        return sorted((t["name"], t["line"]) for t in self.entry_tests(data, path))


def line_of(lines, needle):
    """1-based line of the single fixture line equal to needle."""
    assert lines.count(needle) == 1, needle
    return lines.index(needle) + 1


FILES = {
    "python": "test_x.py",
    "javascript": "x.test.js",
    "typescript": "x.spec.ts",
    "go": "x_test.go",
    "rust": "lib.rs",
    "java": "FooTest.java",
    "kotlin": "FooTest.kt",
    "csharp": "FooTests.cs",
    "swift": "FooTests.swift",
    "php": "FooTest.php",
    "ruby": "foo_spec.rb",
    "cpp": "foo_test.cpp",
}
BRACE_LANGS = ["javascript", "typescript", "go", "rust", "java", "kotlin", "csharp", "swift", "php", "cpp"]
NEW_LANGS = ["kotlin", "csharp", "swift", "php", "ruby", "cpp"]


def test_name(lang, ident):
    cap = ident[0].upper() + ident[1:]
    return {
        "python": f"test_{ident}", "javascript": ident, "typescript": ident,
        "go": f"Test{cap}", "rust": ident, "java": ident, "kotlin": ident,
        "csharp": cap, "swift": f"test{cap}", "php": f"test{cap}", "ruby": ident,
        "cpp": f"Suite.{cap}",
    }[lang]


class T:
    """One test to render. Lines in prefix/body/after carry no indentation."""

    def __init__(self, ident, body=(), start=None, prefix=(), after=(), unclosed=False,
                 inline=False, chain=None, balance=True):
        self.ident = ident
        self.body = list(body)
        self.start = start
        self.prefix = list(prefix)
        self.after = list(after)
        self.unclosed = unclosed
        self.inline = inline
        self.chain = chain
        self.balance = balance


CFG = {
    "go": dict(header=[], base="", body="\t", starts=[], decl="func Test{I}(t *testing.T)", next_line=False, footer=[]),
    "rust": dict(header=[], base="", body="    ", starts=["#[test]"], decl="fn {i}()", next_line=False, footer=[]),
    "java": dict(header=["class FooTest {"], base="    ", body="        ", starts=["@Test"], decl="void {i}()", next_line=False, footer=["}"]),
    "kotlin": dict(header=["class FooTest {"], base="    ", body="        ", starts=["@Test"], decl="fun {i}()", next_line=False, footer=["}"]),
    "csharp": dict(header=["public class FooTests", "{"], base="    ", body="        ", starts=["[Fact]"], decl="public void {I}()", next_line=True, footer=["}"]),
    "swift": dict(header=["import XCTest", "final class FooTests: XCTestCase {"], base="    ", body="        ", starts=[], decl="func test{I}()", next_line=False, footer=["}"]),
    "php": dict(header=["<?php", "class FooTest extends TestCase", "{"], base="    ", body="        ", starts=[], decl="public function test{I}()", next_line=True, footer=["}"]),
    "cpp": dict(header=[], base="", body="  ", starts=[], decl="TEST(Suite, {I})", next_line=False, footer=[]),
}


def body_lines(snips, indent, lang, balance=True):
    out = []
    for sn in snips:
        parts = sn.split("\n")
        out.append(indent + parts[0])
        out.extend(parts[1:])
        if lang == "ruby":
            if sn.rstrip().endswith(" do"):
                out.append(indent + "end")
        elif balance:
            for _ in range(max(sn.count("{") - sn.count("}"), 0)):
                out.append(indent + "}")
    return out


def cap(ident):
    return ident[0].upper() + ident[1:]


def render_python(tests, header=()):
    out = list(header)
    for t in tests:
        out += t.prefix
        out.append(f"def test_{t.ident}():")
        b = []
        for sn in t.body:
            parts = sn.split("\n")
            if parts[0].startswith("except"):
                b += ["    try:", "        f()", "    " + parts[0]] + parts[1:]
            elif sn.startswith("with ") and sn.rstrip().endswith(":"):
                b += ["    " + sn, "        f()"]
            else:
                b += ["    " + parts[0]] + parts[1:]
        out += b or ["    pass"]
        out += t.after
        out.append("")
    return "\n".join(out) + "\n"


def render_js(tests, header=(), sep=("",)):
    out = list(header)
    for n, t in enumerate(tests):
        if n:
            out += list(sep)
        out += t.prefix
        if t.start is not None:
            out.append(t.start)
            if t.start.endswith("{"):
                out += body_lines(t.body, "  ", "javascript", t.balance)
                out.append("});")
        elif t.inline:
            out.append(f"it('{t.ident}', () => {{}});")
        else:
            out.append(f"it('{t.ident}', () => {{")
            out += body_lines(t.body, "  ", "javascript", t.balance)
            if not t.unclosed:
                out.append("});")
        out += t.after
    return "\n".join(out) + "\n"


def render_ruby(tests, header=(), sep=("",)):
    out = ["RSpec.describe Foo do"] + list(header)
    for n, t in enumerate(tests):
        if n:
            out += list(sep)
        out += ["  " + p for p in t.prefix]
        line = t.start if t.start is not None else f'it "{t.ident}" do'
        out.append("  " + line)
        if line.endswith("do") or line.endswith("|"):
            sn = t.body
            lines = []
            for s in sn:
                parts = s.split("\n")
                if parts[0].startswith("rescue"):
                    lines += ["    begin", "      f"]
                lines.append("    " + parts[0])
                lines += parts[1:]
                if parts[0].startswith("rescue") and not any(p.strip().startswith("end") for p in parts[1:]):
                    lines.append("    end")
                if s.rstrip().endswith(" do"):
                    lines.append("    end")
            out += lines
            if not t.unclosed:
                out.append("  end")
        out += ["  " + a for a in t.after]
    out.append("end")
    return "\n".join(out) + "\n"


def render_brace(lang, tests, sep=("",)):
    c = CFG[lang]
    b = c["base"]
    out = list(c["header"])
    for n, t in enumerate(tests):
        if n:
            out += list(sep)
        prefix = t.prefix
        if lang == "php" and t.chain is not None:
            out.append(f"{b}it('{t.ident}', fn () => expect(1)->toBe(1)){t.chain};")
            continue
        if lang == "php" and prefix and prefix[0].startswith("@"):
            prefix = ["/**", f" * {prefix[0]}", " */"] + prefix[1:]
        out += [b + p for p in prefix]
        if t.start is not None:
            starts = [t.start] if isinstance(t.start, str) else list(t.start)
        else:
            starts = c["starts"]
        if lang == "cpp":
            decl = t.start if t.start is not None else c["decl"].format(i=t.ident, I=cap(t.ident))
            starts = []
        else:
            decl = c["decl"].format(i=t.ident, I=cap(t.ident))
        out += [b + s for s in starts]
        if t.inline:
            out.append(f"{b}{decl} {{}}")
        else:
            if c["next_line"]:
                out += [b + decl, b + "{"]
            else:
                out.append(f"{b}{decl} {{")
            out += body_lines(t.body, c["body"], lang, t.balance)
            if not t.unclosed:
                out.append(b + "}")
        out += [b + a for a in t.after]
    out += c["footer"]
    return "\n".join(out) + "\n"


def render(lang, tests, header=(), sep=("",)):
    if lang == "python":
        return render_python(tests, header)
    if lang in ("javascript", "typescript"):
        return render_js(tests, header, sep)
    if lang == "ruby":
        return render_ruby(tests, header, sep)
    return render_brace(lang, tests, sep)


NEUTRAL = {
    "python": "assert x == 1",
    "javascript": "expect(x).toEqual(1);",
    "typescript": "expect(x).toEqual(1);",
    "go": "assert.Equal(t, 1, got)",
    "rust": "assert_eq!(a, 1);",
    "java": "assertEquals(1, x);",
    "kotlin": "assertEquals(1, x)",
    "csharp": "Assert.Equal(1, x);",
    "swift": "XCTAssertEqual(a, b)",
    "php": "$this->assertSame(1, $x);",
    "ruby": "expect(x).to eq(1)",
    "cpp": "EXPECT_EQ(1, x);",
}
NO_ASSERT_STMT = {
    "kotlin": "f()", "csharp": "F();", "swift": "f()", "php": "f();", "ruby": "f", "cpp": "f();",
    "python": "f()", "javascript": "f();", "typescript": "f();", "go": "f()", "rust": "f();", "java": "f();",
}
CODE_LINE = {
    "rust": "const X: u32 = 1;", "java": "int sep = 1;", "kotlin": "val sep = 1",
    "csharp": "const int Sep = 1;", "swift": "let sep = 1", "php": "public $sep = 1;",
}


def S(text):
    return ("S", text)


def P(text):
    return ("P", text)


def C(text):
    return ("C", text)


def make_test(lang, ident, item, neutral):
    kind, text = item if isinstance(item, tuple) else ("B", item)
    t = T(ident)
    if kind == "B":
        t.body = [text]
    elif kind == "P":
        t.prefix = [text]
    elif kind == "S":
        t.start = text
    elif kind == "C":
        t.chain = text
    if neutral and kind != "B":
        t.body = [NEUTRAL[lang]]
    elif neutral and kind == "B":
        t.body = [NEUTRAL[lang], text]
    return t


class RuleScanCase(ScanTestCase):
    def scan_text(self, lang, text, extra=None):
        root = self.tmp()
        self.write(root, FILES[lang], text)
        for rel, content in (extra or {}).items():
            self.write(root, rel, content)
        data = self.scan(root)
        return data, self.entry_tests(data, FILES[lang])

    def batch(self, lang, items, neutral=True):
        """One scan per (language, flag): one test per item, in item order."""
        tests = [make_test(lang, f"t{n}", item, neutral) for n, item in enumerate(items)]
        text = render(lang, tests)
        _, found = self.scan_text(lang, text)
        self.assertEqual(len(found), len(items), text)
        return found

    def assert_flag_items(self, lang, flag, triggers, non_triggers, neutral=True):
        items = list(triggers) + list(non_triggers)
        found = self.batch(lang, items, neutral)
        for n, item in enumerate(items):
            expected = n < len(triggers)
            with self.subTest(lang=lang, flag=flag, snippet=item, trigger=expected):
                if expected:
                    self.assertIn(flag, found[n]["flags"])
                else:
                    self.assertNotIn(flag, found[n]["flags"])


ND_PY = ["random.randint(1, 6)", "datetime.now()", "datetime.utcnow()", "date.today()", "time.time()", "uuid.uuid4()"]
RULES = {
    "python": [
        ("trivial_assert", ["assert True", "assert (x == 1, \"msg\")", "self.assertTrue(True)"],
         ["assert 1", "assert x == 1", "assert (x == 1)"]),
        ("mock", ["m.assert_called_once_with(1)", "m.assert_called()", "m.assert_not_called()",
                  "m.assert_has_calls([])", "m.assert_awaited_once()"], ["assert m.value == 1"]),
        ("snap", ["assert result == snapshot", "snapshot.assert_match(result, \"name\")"], ["assert result == expected"]),
        ("broad_exception", ["with pytest.raises(Exception):", "with pytest.raises(BaseException):",
                             "with self.assertRaises(Exception):"],
         ["with pytest.raises(ValueError):", "with pytest.raises(Exception, match=\"boom\"):"]),
        ("swallowed_error", ["except ValueError:\n        pass", "except Exception:\n        ...", "except:\n        pass"],
         ["except ValueError:\n        raise"]),
        ("nondeterministic", ND_PY, ["datetime(2020, 1, 1)"]),
        ("retry", [P("@pytest.mark.flaky(reruns=3)"), P("@flaky")], [P("@pytest.mark.slow")]),
        ("incomplete", ["raise NotImplementedError"], ["raise ValueError(\"x\")"]),
    ],
    "javascript": [
        ("trivial_assert", ["expect(true).toBe(true);", "expect(true).toBeTruthy();", "expect(false).toBe(false);",
                            "assert.ok(true);", "assert(true);"], ["expect(x).toBe(true);"]),
        ("mock", ["expect(fn).toHaveBeenCalled();", "expect(fn).toHaveBeenCalledWith(1);",
                  "expect(fn).toHaveBeenCalledTimes(2);", "expect(fn).not.toHaveBeenCalled();",
                  "expect(fn).toBeCalled();", "sinon.assert.calledOnce(fn);"], ["expect(fn()).toBe(1);"]),
        ("snap", ["expect(tree).toMatchSnapshot();", "expect(tree).toMatchInlineSnapshot();",
                  "expect(() => f()).toThrowErrorMatchingSnapshot();"], ["expect(tree).toEqual(x);"]),
        ("broad_exception", ["expect(() => f()).toThrow();", "expect(() => f()).toThrowError();",
                             "await expect(p).rejects.toThrow();"],
         ["expect(() => f()).toThrow(TypeError);", "expect(() => f()).toThrow('boom');"]),
        ("swallowed_error", ["try { f(); } catch (e) {}", "try { f(); } catch {}", "p.catch(() => {});"],
         ["try { f(); } catch (e) { throw e; }"]),
        ("nondeterministic", ["Math.random()", "Date.now()", "new Date()", "crypto.randomUUID()"], ["new Date(2020, 0, 1)"]),
        ("retry", ["jest.retryTimes(3);", "this.retries(2);", S("it('x', { retry: 3 }, () => {")], ["const retries = 3;"]),
        ("incomplete", [S("it.todo('later');"), S("test.todo('later');")], [S("it('now', () => {")]),
    ],
    "go": [
        ("skip", ["if testing.Short() {", "f.Skip(\"x\")"], ["t.Log(\"x\")"]),
        ("trivial_assert", ["assert.True(t, true)", "require.True(t, true)", "assert.False(t, false)"], ["assert.True(t, ok)"]),
        ("mock", ["m.AssertExpectations(t)", "m.AssertCalled(t, \"Get\")", "m.AssertNumberOfCalls(t, \"Get\", 1)",
                  "m.AssertNotCalled(t, \"Get\")", "m.EXPECT().Get().Return(1)"], ["assert.Equal(t, 1, got)"]),
        ("snap", ["snaps.MatchSnapshot(t, got)", "snaps.MatchJSON(t, got)", "cupaloy.SnapshotT(t, got)"],
         ["assert.JSONEq(t, want, got)"]),
        ("broad_exception", ["assert.Error(t, err)", "require.Error(t, err)"],
         ["assert.ErrorIs(t, err, ErrNotFound)", "require.EqualError(t, err, \"x\")", "assert.NoError(t, err)"]),
        ("swallowed_error", ["_ = f()", "_ = obj.Close()", "v, _ := parse(s)", "v, _ = parse(s)"],
         ["for _, v := range xs {", "v, err := parse(s)"]),
        ("nondeterministic", ["time.Now()", "rand.Intn(10)", "rand.Float64()", "rand.Shuffle(n, swap)", "uuid.New()"],
         ["time.Date(2020, 1, 1, 0, 0, 0, 0, time.UTC)", "r.Intn(10)"]),
    ],
    "rust": [
        ("trivial_assert", ["assert!(true);", "assert!(!false);"], ["assert!(ok);"]),
        ("mock", ["mock.expect_get().returning(|| 1);"], ["let v = opt.expect(\"value\");"]),
        ("snap", ["insta::assert_snapshot!(out);", "assert_debug_snapshot!(out);", "assert_json_snapshot!(out);"],
         ["assert_eq!(out, \"x\");"]),
        ("broad_exception", [P("#[should_panic]"), "assert!(result.is_err());"],
         [P("#[should_panic(expected = \"boom\")]"), "assert!(matches!(result, Err(Error::NotFound)));"]),
        ("swallowed_error", ["let _ = fs::remove_file(p);", "fs::remove_file(p).ok();"],
         ["let _guard = lock();", "let v = f().ok().unwrap();"]),
        ("nondeterministic", ["rand::random::<u8>()", "rand::thread_rng()", "rand::rng()", "SystemTime::now()",
                              "Utc::now()", "Local::now()", "Uuid::new_v4()"], ["Duration::from_secs(1)"]),
        ("incomplete", ["todo!()", "unimplemented!()"], ["unreachable!()"]),
    ],
    "java": [
        ("trivial_assert", ["assertTrue(true);", "assertFalse(false);", "Assertions.assertTrue(true);",
                            "assertThat(true).isTrue();"], ["assertTrue(ok);"]),
        ("mock", ["verify(repo).save(x);", "verify(repo, times(2)).save(x);", "verifyNoMoreInteractions(repo);",
                  "then(repo).should().save(x);"], ["assertEquals(1, x);"]),
        ("snap", ["Approvals.verify(out);", "expect.toMatchSnapshot(out);"], ["assertEquals(out, x);"]),
        ("broad_exception", [S("@Test(expected = Exception.class)"), "assertThrows(Exception.class, () -> f());",
                             "assertThrows(RuntimeException.class, () -> f());", "assertThrows(Throwable.class, () -> f());"],
         ["assertThrows(IllegalArgumentException.class, () -> f());", S("@Test(expected = IllegalStateException.class)")]),
        ("swallowed_error", ["catch (Exception e) {}", "catch (IOException e) {\n    }"],
         ["catch (Exception e) { throw new AssertionError(e); }"]),
        ("nondeterministic", ["Math.random()", "new Random()", "System.currentTimeMillis()", "LocalDateTime.now()",
                              "Instant.now()", "UUID.randomUUID()"], ["new Random(42)", "Instant.now(clock)"]),
        ("retry", [S("@RetryingTest(3)"), S("@RepeatedIfExceptionsTest(repeats = 3)")], [S("@RepeatedTest(3)")]),
        ("incomplete", ["throw new UnsupportedOperationException(\"todo\");", "fail(\"Not implemented\");", "fail(\"TODO\");"],
         ["fail(\"unexpected value\");"]),
    ],
    "kotlin": [
        ("skip", [P("@Disabled"), P("@Ignore")], [S("@Test")]),
        ("assert", ["assertEquals(1, x)", "assertTrue(ok)", "assertThrows<IllegalStateException> { f() }",
                    "assertFailsWith<IllegalStateException> { f() }", "assertThat(x).isEqualTo(1)", "x shouldBe 1",
                    "fail(\"x\")", "expectThat(x).isEqualTo(1)"], []),
        ("trivial_assert", ["assertTrue(true)", "assertFalse(false)", "true shouldBe true"], ["ok shouldBe true"]),
        ("mock", ["verify { repo.save(x) }", "verify(exactly = 1) { repo.save(x) }", "coVerify { repo.save(x) }",
                  "confirmVerified(repo)", "verify(repo).save(x)"], ["assertEquals(1, x)"]),
        ("broad_exception", ["assertThrows<Exception> { f() }", "assertFailsWith<Exception> { f() }",
                             "shouldThrow<Exception> { f() }", "shouldThrowAny { f() }",
                             "assertThrows(Exception::class.java) { f() }", "assertThrows<RuntimeException> { f() }",
                             "assertThrows<Throwable> { f() }"], ["assertThrows<IllegalStateException> { f() }"]),
        ("swallowed_error", ["catch (e: Exception) {}"], ["catch (e: Exception) { throw e }"]),
        ("nondeterministic", ["Random.nextInt()", "System.currentTimeMillis()", "LocalDateTime.now()", "Instant.now()",
                              "UUID.randomUUID()", "Clock.System.now()"], ["Random(42).nextInt()"]),
        ("retry", [S("@RetryingTest(3)")], [S("@RepeatedTest(3)")]),
        ("incomplete", ["TODO()", "TODO(\"later\")"], ["// TODO later"]),
        ("sleep", ["Thread.sleep(100)", "delay(100)"], []),
        ("heavy", ["mockk<Repo>()", "spyk(obj)", "every { repo.get() } returns 1", "coEvery { repo.load() } returns 1",
                   "mock<Repo>()", "whenever(repo.get()).thenReturn(1)"], []),
    ],
    "csharp": [
        ("skip", [S("[Fact(Skip = \"flaky\")]"), P("[Ignore(\"x\")]"), P("[Explicit]"), "Skip.If(cond);",
                  "Assert.Ignore(\"x\");"], [S("[Fact]")]),
        ("assert", ["Assert.Equal(1, x);", "Assert.That(x, Is.EqualTo(1));", "Assert.Throws<ArgumentException>(() => F());",
                    "CollectionAssert.AreEqual(a, b);", "x.Should().Be(1);", "x.ShouldBe(1);"], []),
        ("trivial_assert", ["Assert.True(true);", "Assert.IsTrue(true);", "Assert.False(false);", "true.Should().BeTrue();"],
         ["Assert.True(ok);"]),
        ("mock", ["repo.Verify(r => r.Save(x), Times.Once());", "repo.VerifyAll();", "repo.Received().Save(x);",
                  "repo.DidNotReceive().Save(x);", "A.CallTo(() => repo.Save(x)).MustHaveHappened();"],
         ["Assert.Equal(1, x);"]),
        ("snap", ["await Verify(result);", "result.ShouldMatchSnapshot();", "result.MatchSnapshot();"],
         ["result.ShouldBe(expected);"]),
        ("broad_exception", ["Assert.Throws<Exception>(() => F());", "await Assert.ThrowsAsync<Exception>(() => F());",
                             "Assert.ThrowsAny<Exception>(() => F());", P("[ExpectedException(typeof(Exception))]"),
                             "act.Should().Throw<Exception>();"], ["Assert.Throws<ArgumentException>(() => F());"]),
        ("swallowed_error", ["catch {}", "catch (Exception) {}", "catch (Exception ex) { }"],
         ["catch (Exception ex) { throw; }"]),
        ("nondeterministic", ["DateTime.Now", "DateTime.UtcNow", "DateTimeOffset.UtcNow", "Guid.NewGuid()",
                              "new Random()", "Random.Shared.Next()"], ["new Random(42)", "new DateTime(2020, 1, 1)"]),
        ("retry", [P("[Retry(3)]"), S("[RetryFact]")], [P("[Repeat(3)]")]),
        ("incomplete", ["Assert.Inconclusive(\"todo\");", "throw new NotImplementedException();"],
         ["throw new InvalidOperationException();"]),
        ("sleep", ["Thread.Sleep(100);", "await Task.Delay(100);"], []),
        ("heavy", ["new Mock<IRepo>()", "Mock.Of<IRepo>()", "Substitute.For<IRepo>()", "A.Fake<IRepo>()",
                   "repo.Setup(r => r.Get())"], []),
    ],
    "swift": [
        ("skip", ["throw XCTSkip(\"x\")", "try XCTSkipIf(cond)", "try XCTSkipUnless(cond)", S("@Test(.disabled(\"x\"))"),
                  S("@Test(.enabled(if: flag))")], [S("@Test(.tags(.fast))")]),
        ("xfail", ["XCTExpectFailure(\"x\")", "withKnownIssue {"], []),
        ("assert", ["XCTAssertEqual(a, b)", "XCTFail(\"x\")", "try XCTUnwrap(v)", "#expect(a == b)", "try #require(v)"], []),
        ("trivial_assert", ["XCTAssert(true)", "XCTAssertTrue(true)", "XCTAssertFalse(false)", "#expect(true)"],
         ["XCTAssertTrue(ok)"]),
        ("mock", ["verify(mock).save(any())"], ["XCTAssertEqual(a, b)"]),
        ("snap", ["assertSnapshot(of: view, as: .image)", "assertSnapshots(of: view, as: [.image])",
                  "assertInlineSnapshot(of: v, as: .json)"], ["XCTAssertEqual(v, w)"]),
        ("broad_exception", ["XCTAssertThrowsError(try f())", "#expect(throws: Error.self) { try f() }",
                             "#expect(throws: (any Error).self) { try f() }"],
         ["XCTAssertThrowsError(try f()) { error in", "#expect(throws: ParseError.self) { try f() }"]),
        ("swallowed_error", ["try? f()", "catch {}"], ["try f()", "catch { XCTFail(\"\\(error)\") }"]),
        ("nondeterministic", ["Date()", "Date.now", "UUID()", "Int.random(in: 0..<10)", "items.randomElement()",
                              "items.shuffled()"], ["Date(timeIntervalSince1970: 0)"]),
        ("sleep", ["sleep(1)", "usleep(10)", "try await Task.sleep(nanoseconds: 1)", "Thread.sleep(forTimeInterval: 1)"], []),
        ("heavy", ["MockRepo()", "stub(mock) { s in }", "given(mock.get()).willReturn(1)"], []),
    ],
    "php": [
        ("skip", ["$this->markTestSkipped('x');", C("->skip()")], []),
        ("focused", [C("->only()")], []),
        ("incomplete", ["$this->markTestIncomplete('x');", C("->todo()")], []),
        ("assert", ["$this->assertSame(1, $x);", "self::assertEquals(1, $x);", "expect($x)->toBe(1);",
                    "$this->expectException(InvalidArgumentException::class);", "$this->fail('x');"], []),
        ("trivial_assert", ["$this->assertTrue(true);", "$this->assertFalse(false);", "self::assertTrue(true);",
                            "expect(true)->toBeTrue();"], ["$this->assertTrue($ok);"]),
        ("mock", ["$mock->expects($this->once())->method('save');", "$mock->shouldReceive('save')->once();",
                  "$spy->shouldHaveReceived('save');"], ["$this->assertSame(1, $x);"]),
        ("snap", ["$this->assertMatchesSnapshot($out);", "$this->assertMatchesJsonSnapshot($out);",
                  "expect($out)->toMatchSnapshot();"], ["$this->assertSame($out, $x);"]),
        ("broad_exception", ["$this->expectException(Exception::class);", "$this->expectException(\\Exception::class);",
                             "$this->expectException(\\Throwable::class);",
                             "expect(fn () => f())->toThrow(Exception::class);"],
         ["$this->expectException(InvalidArgumentException::class);"]),
        ("swallowed_error", ["catch (Exception $e) {}", "catch (\\Throwable) {}"], ["catch (Exception $e) { throw $e; }"]),
        ("nondeterministic", ["time()", "rand(1, 6)", "mt_rand()", "random_int(1, 6)", "uniqid()", "new DateTime()",
                              "new \\DateTimeImmutable()", "Carbon::now()"],
         ["new DateTime('2020-01-01')", "strtotime('2020-01-01')"]),
        ("retry", [P("@retry 3"), P("#[Retry(3)]")], [P("@group slow")]),
        ("sleep", ["sleep(1);", "usleep(10);"], []),
        ("heavy", ["$this->createMock(Repo::class)", "$this->createStub(Repo::class)", "$this->getMockBuilder(Repo::class)",
                   "$this->prophesize(Repo::class)", "Mockery::mock(Repo::class)"], []),
    ],
    "ruby": [
        ("skip", [S("xit \"x\" do"), "skip \"later\"", S("it \"x\", skip: \"later\" do")], [S("it \"can skip\" do")]),
        ("xfail", ["pending \"flaky\"", S("it \"x\", pending: \"y\" do")], []),
        ("focused", [S("fit \"x\" do"), S("it \"x\", focus: true do"), S("it \"x\", :focus do")], []),
        ("incomplete", [S("it \"later\""), "raise NotImplementedError"], [S("it \"now\" do")]),
        ("assert", ["expect(x).to eq(1)", "expect { f }.to change { y }", "is_expected.to eq(1)", "x.should eq(1)",
                    "assert_equal 1, x", "refute x", "x.must_equal 1", "x.wont_be_nil", "flunk \"x\""], []),
        ("trivial_assert", ["expect(true).to be(true)", "expect(true).to be_truthy", "expect(true).to eq(true)",
                            "assert true", "assert(true)"], ["expect(ok).to be(true)", "assert ok"]),
        ("mock", ["expect(repo).to receive(:save)", "expect(repo).to have_received(:save)",
                  "expect(repo).not_to receive(:save)", "mock.verify"], ["expect(x).to eq(1)"]),
        ("snap", ["expect(out).to match_snapshot(\"name\")", "assert_matches_snapshot(out)"], ["expect(out).to eq(x)"]),
        ("broad_exception", ["expect { f }.to raise_error", "expect { f }.to raise_error(StandardError)",
                             "expect { f }.to raise_error(Exception)", "assert_raises { f }", "assert_raises do",
                             "assert_raises(StandardError) { f }"],
         ["expect { f }.to raise_error(ArgumentError)", "assert_raises(ArgumentError) { f }"]),
        ("swallowed_error", ["rescue StandardError\n    end", "f rescue nil"], ["rescue StandardError => e\n      raise"]),
        ("nondeterministic", ["Time.now", "Date.today", "DateTime.now", "rand(10)", "SecureRandom.uuid", "[1, 2].sample",
                              "[1, 2].shuffle"], ["Time.at(0)"]),
        ("retry", [S("it \"x\", retry: 3 do"), ":retry => 3"], ["retries = 3"]),
        ("sleep", ["sleep 1"], []),
        ("heavy", ["double(\"repo\")", "instance_double(Repo)", "class_double(Repo)", "spy(\"repo\")",
                   "allow(repo).to receive(:get)", "Minitest::Mock.new"], []),
    ],
    "cpp": [
        ("skip", [S("TEST(MathTest, DISABLED_Adds)"), S("TEST(DISABLED_MathTest, Adds)"), "GTEST_SKIP() << \"x\";",
                  S("TEST_CASE(\"x\", \"[.]\")"), S("TEST_CASE(\"x\", \"[.integration]\")"),
                  S("TEST_CASE(\"x\", \"[!hide]\")"), S("TEST_CASE(\"x\" * doctest::skip())")],
         [S("TEST_CASE(\"x\", \"[math]\")")]),
        ("xfail", [S("TEST_CASE(\"x\", \"[!shouldfail]\")"), S("TEST_CASE(\"x\", \"[!mayfail]\")"),
                   S("TEST_CASE(\"x\" * doctest::should_fail())"), S("TEST_CASE(\"x\" * doctest::may_fail())")], []),
        ("assert", ["EXPECT_EQ(1, x);", "ASSERT_NE(p, nullptr);", "REQUIRE(x == 1);", "CHECK_FALSE(x);", "FAIL(\"x\");",
                    "ADD_FAILURE();"], []),
        ("trivial_assert", ["EXPECT_TRUE(true);", "ASSERT_TRUE(true);", "EXPECT_FALSE(false);", "REQUIRE(true);",
                            "CHECK(true);", "SUCCEED();"], ["EXPECT_TRUE(ok);"]),
        ("mock", ["EXPECT_CALL(mock, Save(_)).Times(1);"], ["EXPECT_EQ(1, x);"]),
        ("snap", ["Approvals::verify(out);"], ["EXPECT_EQ(out, x);"]),
        ("broad_exception", ["EXPECT_ANY_THROW(f());", "ASSERT_ANY_THROW(f());", "REQUIRE_THROWS(f());",
                             "CHECK_THROWS(f());", "EXPECT_THROW(f(), std::exception);"],
         ["EXPECT_THROW(f(), std::invalid_argument);", "REQUIRE_THROWS_AS(f(), std::invalid_argument);"]),
        ("swallowed_error", ["catch (...) {}", "catch (const std::exception&) {}"], ["catch (...) { FAIL(); }"]),
        ("nondeterministic", ["rand()", "std::random_device rd;", "time(nullptr)", "time(NULL)",
                              "std::chrono::system_clock::now()"], ["std::mt19937 gen(42);"]),
        ("sleep", ["std::this_thread::sleep_for(1ms);", "sleep(1);", "usleep(10);"], []),
        ("heavy", ["MOCK_METHOD(int, Get, (), (override));", "EXPECT_CALL(m, Get());", "ON_CALL(m, Get());",
                   "NiceMock<MockRepo> m;", "StrictMock<MockRepo> m;"], []),
    ],
}
RULES["typescript"] = RULES["javascript"]

DIRECT_FLAGS = {
    "trivial_assert", "broad_exception", "swallowed_error", "nondeterministic", "retry", "incomplete",
    "skip", "xfail", "focused", "sleep",
}


class TestVO4RuleTables(RuleScanCase):
    # VO4 (FR7, FR8, N2): decision table, every trigger/non-trigger snippet
    def test_vo4_direct_flag_rows(self):
        for lang, rows in RULES.items():
            for flag, triggers, non_triggers in rows:
                if flag not in DIRECT_FLAGS:
                    continue
                neutral = flag != "trivial_assert"
                self.assert_flag_items(lang, flag, triggers, non_triggers, neutral=neutral)

    def test_vo4_mock_assert_rows_set_mock_only_assert_when_sole_assertion(self):
        for lang, rows in RULES.items():
            for flag, triggers, non_triggers in rows:
                if flag == "mock":
                    self.assert_flag_items(lang, "mock_only_assert", triggers, non_triggers, neutral=False)

    def test_vo4_snapshot_rows_set_snapshot_only_when_sole_assertion(self):
        for lang, rows in RULES.items():
            for flag, triggers, non_triggers in rows:
                if flag == "snap":
                    self.assert_flag_items(lang, "snapshot_only", triggers, non_triggers, neutral=False)

    def test_vo4_assert_rows_of_new_languages_suppress_no_assert(self):
        for lang in NEW_LANGS:
            for flag, triggers, _ in RULES[lang]:
                if flag != "assert":
                    continue
                items = list(triggers)
                tests = [make_test(lang, f"t{n}", item, False) for n, item in enumerate(items)]
                tests = [t for t in tests]
                tests.append(make_test(lang, "none", "x", False))
                tests[-1].body = [NO_ASSERT_STMT[lang]]
                _, found = self.scan_text(lang, render(lang, tests))
                self.assertEqual(len(found), len(items) + 1)
                for n, item in enumerate(items):
                    with self.subTest(lang=lang, assert_snippet=item):
                        self.assertNotIn("no_assert", found[n]["flags"])
                with self.subTest(lang=lang, body="no assertion"):
                    self.assertIn("no_assert", found[-1]["flags"])

    def test_vo4_heavy_mock_threshold_five_for_each_new_language_snippet(self):
        for lang, rows in RULES.items():
            for flag, snippets, _ in rows:
                if flag != "heavy":
                    continue
                tests = []
                expected = []
                for n, sn in enumerate(snippets):
                    tests.append(T(f"five{n}", body=[NEUTRAL[lang]] + [sn] * 5))
                    expected.append(True)
                    tests.append(T(f"four{n}", body=[NEUTRAL[lang]] + [sn] * 4))
                    expected.append(False)
                mix = [snippets[i % len(snippets)] for i in range(5)]
                tests.append(T("mixfive", body=[NEUTRAL[lang]] + mix))
                expected.append(True)
                tests.append(T("mixfour", body=[NEUTRAL[lang]] + mix[:4]))
                expected.append(False)
                _, found = self.scan_text(lang, render(lang, tests))
                self.assertEqual(len(found), len(tests))
                for t, got, want in zip(tests, found, expected):
                    with self.subTest(lang=lang, test=t.ident, heavy_mock=want):
                        if want:
                            self.assertIn("heavy_mock", got["flags"])
                        else:
                            self.assertNotIn("heavy_mock", got["flags"])


class TestVO6AssertionClassification(RuleScanCase):
    # VO6 (FR5, G1): decision table over S, M, A
    COMBOS = {
        "python": {"A": "assert x == 1", "M": "m.assert_called()", "S": "assert result == snapshot", "none": "x = 1"},
        "javascript": {"A": "expect(x).toEqual(1);", "M": "expect(fn).toHaveBeenCalled();",
                       "S": "expect(tree).toMatchSnapshot();", "none": "const x = 1;"},
    }
    EXPECTED = {
        (): {"no_assert"},
        ("A",): set(),
        ("M",): {"mock_only_assert"},
        ("S",): {"snapshot_only"},
        ("A", "M"): set(),
        ("A", "S"): set(),
        ("M", "S"): set(),
    }
    CLASS_FLAGS = {"no_assert", "mock_only_assert", "snapshot_only"}

    def test_vo6_python_and_javascript_seven_combinations(self):
        for lang, snippets in self.COMBOS.items():
            combos = list(self.EXPECTED)
            tests = []
            for n, combo in enumerate(combos):
                body = [snippets[k] for k in combo] or [snippets["none"]]
                tests.append(T(f"c{n}", body=body))
            _, found = self.scan_text(lang, render(lang, tests))
            self.assertEqual(len(found), len(combos))
            for combo, got in zip(combos, found):
                with self.subTest(lang=lang, combo="+".join(combo) or "none"):
                    self.assertEqual(set(got["flags"]) & self.CLASS_FLAGS, self.EXPECTED[combo])

    def test_vo6_other_languages_mock_only_and_snapshot_only_rows(self):
        for lang, rows in RULES.items():
            if lang in ("python", "javascript"):
                continue
            for flag, triggers, _ in rows:
                if flag not in ("mock", "snap"):
                    continue
                found = self.batch(lang, triggers, neutral=False)
                for sn, got in zip(triggers, found):
                    with self.subTest(lang=lang, rule=flag, snippet=sn):
                        flags = set(got["flags"])
                        self.assertNotIn("no_assert", flags)
                        if flag == "mock":
                            self.assertIn("mock_only_assert", flags)
                            self.assertNotIn("snapshot_only", flags)
                        else:
                            self.assertIn("snapshot_only", flags)
                            self.assertNotIn("mock_only_assert", flags)


GUARDS = {
    "python": ["@freeze_time(\"2020-01-01\")", "import freezegun", "random.seed(0)", "import time_machine"],
    "javascript": ["jest.useFakeTimers()", "vi.useFakeTimers()", "vi.setSystemTime(0)", "MockDate.set(0)", "faker.seed(1)"],
    "go": ["rand.New(rand.NewSource(1))", "rand.Seed(1)", "clockwork.NewFakeClock()"],
    "rust": ["StdRng::seed_from_u64(1)", "StdRng::from_seed([0; 32])"],
    "java": ["Clock.fixed(Instant.EPOCH, ZoneOffset.UTC)"],
    "kotlin": ["Clock.fixed(Instant.EPOCH, ZoneOffset.UTC)"],
    "csharp": ["new FakeTimeProvider()"],
    "php": ["Carbon::setTestNow('2020-01-01');", "mt_srand(1);", "ClockMock::register(self::class);"],
    "ruby": ["travel_to(Time.at(0))", "freeze_time", "Timecop.freeze(Time.at(0))", "srand(1)"],
    "cpp": ["srand(42);"],
}
GUARD_ND = {
    "python": "time.time()", "javascript": "Math.random()", "go": "time.Now()", "rust": "Uuid::new_v4()",
    "java": "Math.random()", "kotlin": "Random.nextInt()", "csharp": "Guid.NewGuid()", "php": "uniqid()",
    "ruby": "Time.now", "cpp": "time(nullptr)",
}


class TestVO7Guards(RuleScanCase):
    # VO7 (FR9, B5): guard anywhere in the file suppresses nondeterministic
    def test_vo7_each_guard_suppresses_and_absence_sets_the_flag(self):
        for lang, guards in GUARDS.items():
            def build(guard):
                a = T("a", body=[NEUTRAL[lang], GUARD_ND[lang]])
                tests = [a]
                if guard is not None:
                    if lang == "python" and guard.startswith("@"):
                        tests.append(T("b", prefix=[guard], body=[NEUTRAL[lang]]))
                    else:
                        tests.append(T("b", body=[NEUTRAL[lang], guard]))
                else:
                    tests.append(T("b", body=[NEUTRAL[lang]]))
                return render(lang, tests)

            _, found = self.scan_text(lang, build(None))
            with self.subTest(lang=lang, guard="absent"):
                self.assertIn("nondeterministic", found[0]["flags"])
            for guard in guards:
                _, found = self.scan_text(lang, build(guard))
                with self.subTest(lang=lang, guard=guard):
                    self.assertNotIn("nondeterministic", found[0]["flags"])
                    self.assertNotIn("nondeterministic", found[1]["flags"])

    def test_vo7_guard_in_other_language_file_does_not_suppress(self):
        root = self.tmp()
        self.write(root, "test_g.py", "import freezegun\n\ndef test_g():\n    assert x == 1\n")
        self.write(root, "x.test.js", "it('a', () => {\n  expect(x).toEqual(1);\n  Math.random();\n});\n")
        data = self.scan(root)
        self.assertIn("nondeterministic", self.entry_tests(data, "x.test.js")[0]["flags"])


class TestVO1FileDetection(ScanTestCase):
    # VO1 (FR1, E2): equivalence partitioning, 19 globs + 6 content-requirement items
    GLOBS = {
        "src/FooTest.kt": ("kotlin", "class FooTest {\n    @Test\n    fun a() {\n    }\n}\n"),
        "src/FooTests.kt": ("kotlin", "class FooTests {\n    @Test\n    fun a() {\n    }\n}\n"),
        "src/FooTest.cs": ("csharp", "public class FooTest\n{\n    [Fact]\n    public void A()\n    {\n    }\n}\n"),
        "src/FooTests.cs": ("csharp", "public class FooTests\n{\n    [Fact]\n    public void A()\n    {\n    }\n}\n"),
        "src/FooTests.swift": ("swift", "import XCTest\nfinal class FooTests: XCTestCase {\n    func testA() {\n    }\n}\n"),
        "src/FooTest.swift": ("swift", "import XCTest\nfinal class FooTest: XCTestCase {\n    func testA() {\n    }\n}\n"),
        "src/FooTest.php": ("php", "<?php\nclass FooTest extends TestCase\n{\n    public function testA()\n    {\n    }\n}\n"),
        "src/foo_spec.rb": ("ruby", "RSpec.describe Foo do\n  it \"a\" do\n  end\nend\n"),
        "src/test_foo.rb": ("ruby", "class FooTest\n  def test_a\n  end\nend\n"),
        "src/foo_test.rb": ("ruby", "class FooTest\n  def test_a\n  end\nend\n"),
        "src/foo_test.cc": ("cpp", "TEST(Suite, A) {\n}\n"),
        "src/foo_test.cpp": ("cpp", "TEST(Suite, A) {\n}\n"),
        "src/foo_test.cxx": ("cpp", "TEST(Suite, A) {\n}\n"),
        "src/foo_unittest.cc": ("cpp", "TEST(Suite, A) {\n}\n"),
        "src/foo_unittest.cpp": ("cpp", "TEST(Suite, A) {\n}\n"),
        "src/test_foo.cc": ("cpp", "TEST(Suite, A) {\n}\n"),
        "src/test_foo.cpp": ("cpp", "TEST(Suite, A) {\n}\n"),
        "src/FooTest.cpp": ("cpp", "TEST(Suite, A) {\n}\n"),
        "src/FooTests.cpp": ("cpp", "TEST(Suite, A) {\n}\n"),
    }

    def test_vo1_each_of_19_globs_is_detected_with_its_language(self):
        root = self.tmp()
        for rel, (_, content) in self.GLOBS.items():
            self.write(root, rel, content)
        self.write(root, "src/Helper.cs", "class Helper {}\n")
        self.write(root, "src/helper.rb", "def helper; end\n")
        self.write(root, "src/foo.cc", "int main() { return 0; }\n")
        self.write(root, "src/Plain.kt", "class Plain\n")
        data = self.scan(root)
        by_path = {f["path"]: f for f in data["files"]}
        self.assertEqual(len(self.GLOBS), 19)
        for rel, (lang, _) in self.GLOBS.items():
            with self.subTest(glob=rel):
                self.assertIn(rel, by_path)
                self.assertEqual(by_path[rel]["language"], lang)
        self.assertEqual(sorted(by_path), sorted(self.GLOBS))

    def test_vo1_swift_content_requirement(self):
        root = self.tmp()
        body = "final class BarTests {\n    func testA() {\n    }\n}\n"
        self.write(root, "a/XcBarTests.swift", "import XCTest\n" + body)
        self.write(root, "b/TgBarTests.swift", "import Testing\n" + body)
        self.write(root, "tests/NoImportTests.swift", "import Foundation\n" + body)
        data = self.scan(root)
        paths = {f["path"] for f in data["files"]}
        with self.subTest(item="swift import XCTest"):
            self.assertIn("a/XcBarTests.swift", paths)
        with self.subTest(item="swift import Testing"):
            self.assertIn("b/TgBarTests.swift", paths)
        with self.subTest(item="swift without test import"):
            self.assertNotIn("tests/NoImportTests.swift", paths)
            self.assertIn("tests/NoImportTests.swift", data["inventory"])

    def test_vo1_cpp_content_requirement(self):
        root = self.tmp()
        self.write(root, "a/with_macro_test.cpp", "TEST(Suite, A) {\n}\n")
        self.write(root, "test/no_macro_test.cpp", "int helper() { return 1; }\n")
        data = self.scan(root)
        paths = {f["path"] for f in data["files"]}
        with self.subTest(item="cpp with test macro"):
            self.assertIn("a/with_macro_test.cpp", paths)
        with self.subTest(item="cpp without test macro"):
            self.assertNotIn("test/no_macro_test.cpp", paths)
            self.assertIn("test/no_macro_test.cpp", data["inventory"])

    def test_vo1_cpp_each_macro_qualifies_a_file(self):
        macros = ["TEST(", "TEST_F(", "TEST_P(", "TYPED_TEST(", "TYPED_TEST_P(", "TEST_CASE(", "TEST_CASE_METHOD(", "SCENARIO("]
        root = self.tmp()
        for n, macro in enumerate(macros):
            self.write(root, f"m{n}_test.cpp", f"{macro}S, A) {{\n}}\n")
        data = self.scan(root)
        paths = {f["path"] for f in data["files"]}
        for n, macro in enumerate(macros):
            with self.subTest(macro=macro):
                self.assertIn(f"m{n}_test.cpp", paths)

    def test_vo1_rust_content_requirement(self):
        root = self.tmp()
        self.write(root, "a/tokio_only.rs", "#[tokio::test]\nasync fn t() {\n}\n")
        self.write(root, "tests/cfg_only.rs", "#[cfg(test)]\nmod tests {\n    fn helper() {}\n}\n")
        self.write(root, "src/unit.rs", "#[cfg(test)]\nmod tests {\n}\n")
        data = self.scan(root)
        paths = {f["path"]: f for f in data["files"]}
        with self.subTest(item="rust tokio::test only"):
            self.assertIn("a/tokio_only.rs", paths)
            self.assertEqual(paths["a/tokio_only.rs"]["language"], "rust")
        with self.subTest(item="rust cfg(test) only under tests/"):
            self.assertNotIn("tests/cfg_only.rs", paths)
            self.assertIn("tests/cfg_only.rs", data["inventory"])
        with self.subTest(item="rust cfg(test) only elsewhere"):
            self.assertNotIn("src/unit.rs", paths)

    def test_vo1_rust_every_fr2_attribute_qualifies_a_file(self):
        attrs = ["#[test]", "#[tokio::test]", "#[tokio::test(flavor = \"multi_thread\")]", "#[async_std::test]",
                 "#[rstest]", "#[test_case(1)]"]
        root = self.tmp()
        for n, attr in enumerate(attrs):
            self.write(root, f"r{n}.rs", f"{attr}\nfn t() {{\n}}\n")
        data = self.scan(root)
        paths = {f["path"]: f for f in data["files"]}
        for n, attr in enumerate(attrs):
            with self.subTest(attr=attr):
                self.assertIn(f"r{n}.rs", paths)
                self.assertEqual([t["name"] for t in paths[f"r{n}.rs"]["tests"]], ["t"])


class TestVO2StartForms(ScanTestCase):
    # VO2 (FR2, N1, G2, G3): equivalence partitioning over every start form

    def check(self, path, lines, expected, text=None):
        root = self.tmp()
        self.write(root, path, "\n".join(lines) + "\n")
        data = self.scan(root)
        got = self.name_lines(data, path)
        want = sorted((name, line_of(lines, decl)) for name, decl in expected)
        for item in want:
            with self.subTest(path=path, name=item[0]):
                self.assertIn(item, got)
        self.assertEqual(got, want)
        return data

    def test_rust_attribute_forms(self):
        lines = [
            "#[test]", "fn t_plain() {", "}", "",
            "#[tokio::test]", "async fn t_tokio() {", "}", "",
            "#[tokio::test(flavor = \"multi_thread\")]", "async fn t_flavor() {", "}", "",
            "#[async_std::test]", "async fn t_async_std() {", "}", "",
            "#[rstest]", "fn t_rstest() {", "}", "",
            "#[test_case(1)]", "fn t_case_one(x: u32) {", "}", "",
            "#[test_case(1)]", "#[test_case(2)]", "fn t_case_two(x: u32) {", "}", "",
            "#[cfg(test)]", "fn not_a_test() {", "}",
        ]
        self.check("lib.rs", lines, [
            ("t_plain", "fn t_plain() {"), ("t_tokio", "async fn t_tokio() {"),
            ("t_flavor", "async fn t_flavor() {"), ("t_async_std", "async fn t_async_std() {"),
            ("t_rstest", "fn t_rstest() {"), ("t_case_one", "fn t_case_one(x: u32) {"),
            ("t_case_two", "fn t_case_two(x: u32) {"),
        ])

    def test_java_annotation_and_return_type_forms(self):
        lines = [
            "class FooTest {",
            "    @Test", "    void plain() {", "    }", "",
            "    @ParameterizedTest", "    public void param() {", "    }", "",
            "    @RepeatedTest(3)", "    void repeated() {", "    }", "",
            "    @TestFactory", "    Stream<DynamicTest> factory() {", "        return null;", "    }", "",
            "    @TestTemplate", "    void template() {", "    }", "",
            "    @Property", "    boolean prop() {", "        return true;", "    }", "",
            "    @RetryingTest(3)", "    void retrying() {", "    }", "",
            "    @RepeatedIfExceptionsTest(repeats = 3)", "    void riexc() {", "    }", "",
            "    @Test", "    List<String> generic() {", "        return null;", "    }", "",
            "    void helper() {", "    }",
            "}",
        ]
        self.check("FooTest.java", lines, [
            ("plain", "    void plain() {"), ("param", "    public void param() {"),
            ("repeated", "    void repeated() {"), ("factory", "    Stream<DynamicTest> factory() {"),
            ("template", "    void template() {"), ("prop", "    boolean prop() {"),
            ("retrying", "    void retrying() {"), ("riexc", "    void riexc() {"),
            ("generic", "    List<String> generic() {"),
        ])

    def test_go_test_and_fuzz_functions(self):
        lines = [
            "package x", "",
            "func TestAlpha(t *testing.T) {", "}", "",
            "func FuzzBeta(f *testing.F) {", "}", "",
            "func helper() {", "}",
        ]
        self.check("x_test.go", lines, [
            ("TestAlpha", "func TestAlpha(t *testing.T) {"), ("FuzzBeta", "func FuzzBeta(f *testing.F) {"),
        ])

    def test_kotlin_annotation_forms_and_backtick_name(self):
        lines = [
            "class FooTest {",
            "    @Test", "    fun plain() {", "    }", "",
            "    @ParameterizedTest", "    fun param() {", "    }", "",
            "    @RepeatedTest(3)", "    fun repeated() {", "    }", "",
            "    @TestFactory", "    fun factory() {", "    }", "",
            "    @TestTemplate", "    fun template() {", "    }", "",
            "    @Property", "    fun prop() {", "    }", "",
            "    @RetryingTest(3)", "    fun retrying() {", "    }", "",
            "    @Test", "    fun `adds two numbers`() {", "    }", "",
            "    fun helper() {", "    }",
            "}",
        ]
        self.check("FooTest.kt", lines, [
            ("plain", "    fun plain() {"), ("param", "    fun param() {"), ("repeated", "    fun repeated() {"),
            ("factory", "    fun factory() {"), ("template", "    fun template() {"), ("prop", "    fun prop() {"),
            ("retrying", "    fun retrying() {"),
            ("adds two numbers", "    fun `adds two numbers`() {"),
        ])

    def test_csharp_attribute_forms_and_non_starts(self):
        lines = [
            "[TestFixture]", "public class FooTests", "{",
            "    [SetUp]", "    public void Init()", "    {", "    }", "",
            "    [Fact]", "    public void FactCase()", "    {", "    }", "",
            "    [Theory]", "    public void TheoryCase(int x)", "    {", "    }", "",
            "    [Test]", "    public void NunitCase()", "    {", "    }", "",
            "    [TestCase(1)]", "    public void TestCaseCase(int x)", "    {", "    }", "",
            "    [TestCaseSource(nameof(Cases))]", "    public void SourceCase(int x)", "    {", "    }", "",
            "    [TestMethod]", "    public void MsCase()", "    {", "    }", "",
            "    [DataTestMethod]", "    public void DataCase()", "    {", "    }", "",
            "    [SkippableFact]", "    public void SkippableCase()", "    {", "    }", "",
            "    [RetryFact]", "    public void RetryCase()", "    {", "    }", "",
            "    [Test, Category(\"x\")]", "    public void CombinedCase()", "    {", "    }", "",
            "    [Fact(Skip = \"x\")]", "    public void ArgCase()", "    {", "    }", "",
            "    [Fact]", "    public async Task AsyncCase()", "    {", "    }", "",
            "    [Fact]", "    public async ValueTask ValueTaskCase()", "    {", "    }", "",
            "    [Fact]", "    void BareCase()", "    {", "    }",
            "}", "",
            "[TestClass]", "public class OtherTests", "{", "    public void NotATest()", "    {", "    }", "}",
        ]
        names = [
            "FactCase", "TheoryCase", "NunitCase", "TestCaseCase", "SourceCase", "MsCase", "DataCase",
            "SkippableCase", "RetryCase", "CombinedCase", "ArgCase", "AsyncCase", "ValueTaskCase", "BareCase",
        ]
        expected = []
        for name in names:
            decl = [l for l in lines if f" {name}(" in l or f" {name}()" in l][0]
            expected.append((name, decl))
        self.check("FooTests.cs", lines, expected)

    def test_swift_func_and_test_macro_forms(self):
        lines = [
            "import XCTest",
            "final class FooTests: XCTestCase {",
            "    func testAlpha() {", "    }", "",
            "    public func testBeta() async throws {", "    }", "",
            "    @MainActor func testGamma() {", "    }", "",
            "    @Test func testFoo() {", "    }", "",
            "    @Test(\"display name\")", "    func labelled() {", "    }", "",
            "    @Test", "    func plainMacro() {", "    }", "",
            "    func helperNotTest() {", "    }",
            "}",
        ]
        self.check("FooTests.swift", lines, [
            ("testAlpha", "    func testAlpha() {"), ("testBeta", "    public func testBeta() async throws {"),
            ("testGamma", "    @MainActor func testGamma() {"), ("testFoo", "    @Test func testFoo() {"),
            ("labelled", "    func labelled() {"), ("plainMacro", "    func plainMacro() {"),
        ])

    def test_php_function_attribute_docblock_and_pest_forms(self):
        lines = [
            "<?php",
            "class FooTest extends TestCase",
            "{",
            "    public function testAlpha()", "    {", "    }", "",
            "    protected function testBeta()", "    {", "    }", "",
            "    private function testGamma()", "    {", "    }", "",
            "    static function testDelta()", "    {", "    }", "",
            "    final public function testEpsilon()", "    {", "    }", "",
            "    function testZeta()", "    {", "    }", "",
            "    #[Test]", "    public function addsNumbers()", "    {", "    }", "",
            "    /** @test */", "    public function docblockInline()", "    {", "    }", "",
            "    /**", "     * Adds numbers.", "     *", "     * @test", "     */",
            "    public function docblockMulti()", "    {", "    }", "",
            "    #[Test]", "    public function testAdds()", "    {", "    }", "",
            "    public function helper()", "    {", "    }",
            "}", "",
            "it('adds numbers', function () {", "});", "",
            "test('subtracts numbers', function () {", "});",
        ]
        self.check("FooTest.php", lines, [
            ("testAlpha", "    public function testAlpha()"), ("testBeta", "    protected function testBeta()"),
            ("testGamma", "    private function testGamma()"), ("testDelta", "    static function testDelta()"),
            ("testEpsilon", "    final public function testEpsilon()"), ("testZeta", "    function testZeta()"),
            ("addsNumbers", "    public function addsNumbers()"),
            ("docblockInline", "    public function docblockInline()"),
            ("docblockMulti", "    public function docblockMulti()"),
            ("testAdds", "    public function testAdds()"),
            ("adds numbers", "it('adds numbers', function () {"),
            ("subtracts numbers", "test('subtracts numbers', function () {"),
        ])

    def test_ruby_example_group_and_minitest_forms(self):
        lines = [
            "RSpec.describe Foo do",
            "  it \"alpha\" do", "  end", "",
            "  it('beta') do", "  end", "",
            "  it(\"gamma\") { 1 }", "",
            "  it 'single quoted' do", "  end", "",
            "  specify \"delta\" do", "  end", "",
            "  example \"eps\" do", "  end", "",
            "  scenario \"zeta\" do", "  end", "",
            "  xit \"eta\" do", "  end", "",
            "  fit \"theta\" do", "  end", "",
            "  xspecify \"iota\" do", "  end", "",
            "  fexample \"kappa\" do", "  end", "",
            "  xscenario \"lambda\" do", "  end",
            "end", "",
            "class FooTest < Minitest::Test",
            "  test \"mu\" do", "  end", "",
            "  def test_nu", "  end", "",
            "  def helper", "  end",
            "end",
        ]
        self.check("foo_spec.rb", lines, [
            ("alpha", "  it \"alpha\" do"), ("beta", "  it('beta') do"), ("gamma", "  it(\"gamma\") { 1 }"),
            ("single quoted", "  it 'single quoted' do"), ("delta", "  specify \"delta\" do"),
            ("eps", "  example \"eps\" do"), ("zeta", "  scenario \"zeta\" do"), ("eta", "  xit \"eta\" do"),
            ("theta", "  fit \"theta\" do"), ("iota", "  xspecify \"iota\" do"),
            ("kappa", "  fexample \"kappa\" do"), ("lambda", "  xscenario \"lambda\" do"),
            ("mu", "  test \"mu\" do"), ("test_nu", "  def test_nu"),
        ])

    def test_cpp_macro_forms(self):
        lines = [
            "TEST(MathTest, Adds) {", "}", "",
            "TEST_F(Fixture, Works) {", "}", "",
            "TEST_P(ParamSuite, Param) {", "}", "",
            "TYPED_TEST(TypedSuite, Typed) {", "}", "",
            "TYPED_TEST_P(TypedPSuite, TypedP) {", "}", "",
            "TEST_CASE(\"catch case\") {", "}", "",
            "TEST_CASE(\"tagged case\", \"[x]\") {", "}", "",
            "SCENARIO(\"a scenario\") {", "}", "",
            "TEST_CASE_METHOD(Fixture, \"method case\") {", "}",
        ]
        self.check("foo_test.cpp", lines, [
            ("MathTest.Adds", "TEST(MathTest, Adds) {"), ("Fixture.Works", "TEST_F(Fixture, Works) {"),
            ("ParamSuite.Param", "TEST_P(ParamSuite, Param) {"),
            ("TypedSuite.Typed", "TYPED_TEST(TypedSuite, Typed) {"),
            ("TypedPSuite.TypedP", "TYPED_TEST_P(TypedPSuite, TypedP) {"),
            ("catch case", "TEST_CASE(\"catch case\") {"), ("tagged case", "TEST_CASE(\"tagged case\", \"[x]\") {"),
            ("a scenario", "SCENARIO(\"a scenario\") {"),
            ("method case", "TEST_CASE_METHOD(Fixture, \"method case\") {"),
        ])

    def test_g3_gtest_same_test_name_in_two_suites_is_not_duplicate(self):
        lines = ["TEST(A, X) {", "}", "", "TEST(B, X) {", "}"]
        data = self.check("foo_test.cpp", lines, [("A.X", "TEST(A, X) {"), ("B.X", "TEST(B, X) {")])
        for test in self.entry_tests(data, "foo_test.cpp"):
            with self.subTest(name=test["name"]):
                self.assertNotIn("duplicate_name", test["flags"])


ND_BOUNDARY = {
    "javascript": "Math.random()", "typescript": "Math.random()", "go": "time.Now()", "rust": "rand::rng()",
    "java": "Math.random()", "kotlin": "Random.nextInt()", "csharp": "Guid.NewGuid()", "swift": "UUID()",
    "php": "uniqid()", "cpp": "rand()", "ruby": "rand(10)",
}


class TestVO3BodyModel(RuleScanCase):
    # VO3 (FR3, FR4, B3, B4, G4): 2-value boundary analysis

    def flags(self, lang, tests, **kw):
        _, found = self.scan_text(lang, render(lang, tests, **kw))
        return found

    def test_vo3_merge_of_several_starts_on_one_name_is_one_test(self):
        cases = {
            "rust": (["#[test_case(1)]"], ["#[test_case(1)]", "#[test_case(2)]"]),
            "java": (["@Test"], ["@Test", "@RetryingTest(3)"]),
            "kotlin": (["@Test"], ["@Test", "@RetryingTest(3)"]),
            "csharp": (["[TestCase(1)]"], ["[TestCase(1)]", "[TestCase(2)]"]),
            "swift": ([], ["@Test"]),
            "php": ([], ["#[Test]"]),
        }
        for lang, (one, two) in cases.items():
            for label, starts in (("N=1", one), ("N=2", two)):
                with self.subTest(lang=lang, starts=label):
                    if lang == "swift":
                        t = T("a", start=starts, body=[NEUTRAL[lang]])
                    elif lang == "php":
                        t = T("a", prefix=starts, body=[NEUTRAL[lang]])
                        t.prefix = list(starts)
                    else:
                        t = T("a", start=starts, body=[NEUTRAL[lang]])
                    found = self.flags(lang, [t])
                    self.assertEqual(len(found), 1)
                    self.assertEqual(found[0]["name"], test_name(lang, "a"))
                    self.assertNotIn("duplicate_name", found[0]["flags"])

    def test_b3_csharp_two_testcase_attributes_one_test_named_a(self):
        lines = [
            "public class FooTests", "{",
            "    [TestCase(1)]", "    [TestCase(2)]", "    public void A(int x)", "    {", "    }", "}",
        ]
        root = self.tmp()
        self.write(root, "FooTests.cs", "\n".join(lines) + "\n")
        tests = self.entry_tests(self.scan(root), "FooTests.cs")
        self.assertEqual([(t["name"], t["line"]) for t in tests], [("A", 5)])
        self.assertNotIn("duplicate_name", tests[0]["flags"])

    PREFIX_FORMS = {
        "rust": [("#[should_panic]", "broad_exception")],
        "java": [("@Disabled", "skip")],
        "kotlin": [("@Disabled", "skip")],
        "csharp": [("[Retry(3)]", "retry")],
        # Separated case omitted for swift: every flag-bearing swift H snippet is itself a start form,
        # so an orphaned start above a code line cannot isolate the prefix boundary (spec challenge).
        "swift": [("@Test(.disabled(\"x\"))", "skip")],
        "php": [("#[Retry(3)]", "retry"), ("@retry 3", "retry")],
    }

    def test_vo3_prefix_line_directly_above_vs_separated_by_a_code_line(self):
        for lang, forms in self.PREFIX_FORMS.items():
            for text, flag in forms:
                for separated in ((False,) if lang == "swift" else (False, True)):
                    with self.subTest(lang=lang, prefix=text, separated=separated):
                        prefix = [text] + ([CODE_LINE[lang]] if separated else [])
                        if lang == "php" and text.startswith("@") and separated:
                            prefix = [text, CODE_LINE[lang]]
                        found = self.flags(lang, [T("a", prefix=prefix, body=[NEUTRAL[lang]])])
                        named = [t for t in found if t["name"] == test_name(lang, "a")]
                        self.assertEqual(len(named), 1, found)
                        if separated:
                            self.assertNotIn(flag, named[0]["flags"])
                        else:
                            self.assertIn(flag, named[0]["flags"])

    def test_vo3_brace_end_last_body_line_vs_first_line_after_closer(self):
        for lang in BRACE_LANGS:
            nd = ND_BOUNDARY[lang]
            with self.subTest(lang=lang, position="last body line"):
                t = T("a", body=[NEUTRAL[lang], nd])
                self.assertIn("nondeterministic", self.flags(lang, [t])[0]["flags"])
            with self.subTest(lang=lang, position="first line after closer"):
                t = T("a", body=[NEUTRAL[lang]], after=[nd])
                self.assertNotIn("nondeterministic", self.flags(lang, [t])[0]["flags"])

    def test_vo3_clamp_unbalanced_body_ends_before_next_start(self):
        for lang in BRACE_LANGS:
            nd = ND_BOUNDARY[lang]
            with self.subTest(lang=lang, snippet="in unbalanced test"):
                found = self.flags(lang, [T("a", body=[NEUTRAL[lang], nd], unclosed=True), T("b", body=[NEUTRAL[lang]])])
                self.assertEqual(len(found), 2)
                self.assertIn("nondeterministic", found[0]["flags"])
                self.assertNotIn("nondeterministic", found[1]["flags"])
            with self.subTest(lang=lang, snippet="in next test"):
                found = self.flags(lang, [T("a", body=[NEUTRAL[lang]], unclosed=True), T("b", body=[NEUTRAL[lang], nd])])
                self.assertEqual(len(found), 2)
                self.assertNotIn("nondeterministic", found[0]["flags"])
                self.assertIn("nondeterministic", found[1]["flags"])

    def test_vo3_ruby_indent_end_deeper_vs_equal_indent(self):
        nd = "rand(10)"
        cases = {
            "deeper by two": ("RSpec.describe Foo do\n  it \"a\" do\n    expect(x).to eq(1)\n    rand(10)\n  end\nend\n", True),
            "deeper by one": ("RSpec.describe Foo do\n  it \"a\" do\n    expect(x).to eq(1)\n   rand(10)\n  end\nend\n", True),
            "equal after end": ("RSpec.describe Foo do\n  it \"a\" do\n    expect(x).to eq(1)\n  end\n  rand(10)\nend\n", False),
            "equal without end": ("RSpec.describe Foo do\n  it \"a\" do\n    expect(x).to eq(1)\n  rand(10)\nend\n", False),
            "end line included": ("RSpec.describe Foo do\n  it \"a\" do\n    expect(x).to eq(1)\n  end; rand(10)\nend\n", True),
            "brace line included": ("RSpec.describe Foo do\n  it(\"a\") {\n    expect(x).to eq(1)\n  }; rand(10)\nend\n", True),
        }
        self.assertTrue(nd)
        for label, (text, expected) in cases.items():
            with self.subTest(case=label):
                _, found = self.scan_text("ruby", text)
                self.assertEqual(len(found), 1)
                if expected:
                    self.assertIn("nondeterministic", found[0]["flags"])
                else:
                    self.assertNotIn("nondeterministic", found[0]["flags"])

    def test_vo3_ruby_clamp_missing_end_stops_at_next_start(self):
        text = (
            "RSpec.describe Foo do\n  it \"a\" do\n    expect(x).to eq(1)\n    rand(10)\n"
            "  it \"b\" do\n    expect(x).to eq(1)\n  end\nend\n"
        )
        _, found = self.scan_text("ruby", text)
        self.assertEqual([t["name"] for t in found], ["a", "b"])
        self.assertIn("nondeterministic", found[0]["flags"])
        self.assertNotIn("nondeterministic", found[1]["flags"])
        text = text.replace("    rand(10)\n", "").replace("  it \"b\" do\n    expect(x).to eq(1)\n", "  it \"b\" do\n    rand(10)\n")
        _, found = self.scan_text("ruby", text)
        self.assertNotIn("nondeterministic", found[0]["flags"])
        self.assertIn("nondeterministic", found[1]["flags"])

    def test_vo3_empty_true_and_false_for_brace_languages(self):
        for lang in BRACE_LANGS:
            with self.subTest(lang=lang):
                tests = [
                    T("a"),
                    T("b", inline=True),
                    T("c", body=[NO_ASSERT_STMT[lang]]),
                ]
                found = self.flags(lang, tests)
                self.assertEqual(len(found), 3)
                self.assertIn("empty", found[0]["flags"])
                self.assertIn("empty", found[1]["flags"])
                self.assertNotIn("empty", found[2]["flags"])

    def test_vo3_empty_for_ruby_do_def_and_bodiless_it(self):
        cases = {
            "it do empty": ("RSpec.describe Foo do\n  it \"a\" do\n  end\nend\n", True),
            "it do with args empty": ("RSpec.describe Foo do\n  it \"a\" do |x|\n  end\nend\n", True),
            "def empty": ("class FooTest\n  def test_a\n  end\nend\n", True),
            "it do non-empty": ("RSpec.describe Foo do\n  it \"a\" do\n    expect(x).to eq(1)\n  end\nend\n", False),
            "def non-empty": ("class FooTest\n  def test_a\n    assert true\n  end\nend\n", False),
            "bodiless it before lower-indent end": ("RSpec.describe Foo do\n  it \"a\"\nend\n", False),
        }
        for label, (text, expected) in cases.items():
            with self.subTest(case=label):
                _, found = self.scan_text("ruby", text)
                self.assertEqual(len(found), 1)
                if expected:
                    self.assertIn("empty", found[0]["flags"])
                else:
                    self.assertNotIn("empty", found[0]["flags"])

    def test_vo3_prefix_extension_does_not_cross_into_one_line_test_above(self):
        lines = [
            "#[test] fn a() { assert!(true); }",
            "#[test]",
            "fn b() {",
            "    let x = 1;",
            "}",
        ]
        _, found = self.scan_text("rust", "\n".join(lines) + "\n")
        by_name = {t["name"]: t["flags"] for t in found}
        self.assertEqual(sorted(by_name), ["a", "b"])
        self.assertIn("no_assert", by_name["b"])
        self.assertNotIn("no_assert", by_name["a"])
        self.assertNotIn("trivial_assert", by_name["b"])

    def test_b4_rust_ignore_directly_above_second_test_flags_only_second(self):
        lines = [
            "#[test]", "fn first() {", "    assert_eq!(1, 1);", "}",
            "#[ignore]", "#[test]", "fn second() {", "    assert_eq!(1, 1);", "}",
        ]
        _, found = self.scan_text("rust", "\n".join(lines) + "\n")
        by_name = {t["name"]: t["flags"] for t in found}
        self.assertEqual(sorted(by_name), ["first", "second"])
        self.assertNotIn("skip", by_name["first"])
        self.assertIn("skip", by_name["second"])

    def test_g4_js_describe_skip_after_test_closer_does_not_skip_earlier_test(self):
        lines = [
            "it('before', () => {", "  expect(1).toBe(1);", "});",
            "describe.skip('G', () => {", "  it('inside', () => {", "    expect(1).toBe(1);", "  });", "});",
        ]
        _, found = self.scan_text("javascript", "\n".join(lines) + "\n")
        by_name = {t["name"]: t["flags"] for t in found}
        self.assertNotIn("skip", by_name["before"])
        self.assertIn("skip", by_name["inside"])


class TestVO5GroupPropagation(RuleScanCase):
    # VO5 (FR6, B1, B2): inside the group -> flag, outside -> none

    def flags_by_name(self, lang, text):
        _, found = self.scan_text(lang, text)
        return {t["name"]: t["flags"] for t in found}

    def assert_in_out(self, label, flags, inside, outside, flag):
        with self.subTest(group=label, flag=flag):
            for name in inside:
                self.assertIn(flag, flags[name], name)
            for name in outside:
                self.assertNotIn(flag, flags[name], name)

    def test_vo5_python_class_decorators_including_nested_class(self):
        for deco, flag in (("@unittest.skip('later')", "skip"), ("@pytest.mark.xfail", "xfail")):
            text = "\n".join([
                "import unittest", "import pytest", "",
                deco, "class TestOuter(unittest.TestCase):",
                "    class TestInner(unittest.TestCase):", "        def test_nested(self):", "            assert 1", "",
                "    def test_direct(self):", "        assert 1", "",
                "class TestPlain(unittest.TestCase):", "    def test_outside(self):", "        assert 1", "",
                "def test_module_level():", "    assert 1",
            ]) + "\n"
            flags = self.flags_by_name("python", text)
            self.assert_in_out(deco, flags, ["test_nested", "test_direct"], ["test_outside", "test_module_level"], flag)

    def test_vo5_python_module_level_pytestmark_both_forms(self):
        forms = {
            "pytestmark = pytest.mark.skip(reason=\"x\")": "skip",
            "pytestmark = [pytest.mark.xfail]": "xfail",
        }
        for mark, flag in forms.items():
            text = "\n".join([
                "import pytest", mark, "",
                "def test_top():", "    assert 1", "",
                "class TestK:", "    def test_method(self):", "        assert 1",
            ]) + "\n"
            flags = self.flags_by_name("python", text)
            self.assert_in_out(mark, flags, ["test_top", "test_method"], [], flag)
        plain = self.flags_by_name("python", "import pytest\n\ndef test_top():\n    assert 1\n")
        self.assertNotIn("skip", plain["test_top"])
        self.assertNotIn("xfail", plain["test_top"])

    def test_vo5_javascript_group_triggers(self):
        groups = [
            ("xdescribe(", "skip"), ("describe.skip(", "skip"), ("context.skip(", "skip"), ("xcontext(", "skip"),
            ("fdescribe(", "focused"), ("describe.only(", "focused"), ("context.only(", "focused"),
        ]
        for trigger, flag in groups:
            text = "\n".join([
                f"{trigger}'S', () => {{",
                "  it('inside', () => {", "    expect(1).toEqual(1);", "  });",
                "});",
                "it('outside', () => {", "  expect(1).toEqual(1);", "});",
            ]) + "\n"
            flags = self.flags_by_name("javascript", text)
            self.assert_in_out(trigger, flags, ["inside"], ["outside"], flag)

    def test_vo5_java_and_kotlin_class_annotations(self):
        for lang, decl, start in (("java", "void {n}() {{", "@Test"), ("kotlin", "fun {n}() {{", "@Test")):
            kw = "class"
            forms = {
                "@Disabled": ["@Disabled", f"{kw} FooTest {{"],
                "@Ignore(...)": ["@Ignore(\"x\")", f"{kw} FooTest {{"],
                "@Disabled @Nested": ["@Disabled", "@Nested", f"{kw} FooTest {{"],
            }
            for label, head in forms.items():
                lines = head + [f"    {start}", "    " + decl.format(n="inside"), "    }", "}", "",
                                f"{kw} OtherTest {{", f"    {start}", "    " + decl.format(n="outside"), "    }", "}"]
                flags = self.flags_by_name(lang, "\n".join(lines) + "\n")
                self.assert_in_out(f"{lang} {label}", flags, ["inside"], ["outside"], "skip")

    def test_vo5_java_kotlin_nested_class_with_disabled_leaves_sibling_test(self):
        for lang, decl in (("java", "void {n}() {{"), ("kotlin", "fun {n}() {{")):
            lines = [
                "class OuterTest {",
                "    @Disabled", "    @Nested", "    class Inner {",
                "        @Test", "        " + decl.format(n="inner"), "        }", "    }",
                "    @Test", "    " + decl.format(n="direct"), "    }",
                "}",
            ]
            flags = self.flags_by_name(lang, "\n".join(lines) + "\n")
            self.assert_in_out(f"{lang} nested", flags, ["inner"], ["direct"], "skip")

    def test_vo5_csharp_class_attributes(self):
        for attr in ('[Ignore("x")]', "[Explicit]"):
            lines = [
                attr, "public class FooTests", "{",
                "    [Fact]", "    public void Inside()", "    {", "    }", "}", "",
                "public class OtherTests", "{",
                "    [Fact]", "    public void Outside()", "    {", "    }", "}",
            ]
            flags = self.flags_by_name("csharp", "\n".join(lines) + "\n")
            self.assert_in_out(attr, flags, ["Inside"], ["Outside"], "skip")

    def test_vo5_swift_suite_disabled_on_struct_and_class(self):
        for kind in ("struct", "class"):
            lines = [
                "import Testing", "",
                "@Suite(.disabled(\"x\"))", f"{kind} FooTests {{",
                "    @Test func inside() {", "    }", "}", "",
                f"{kind} OtherTests {{", "    @Test func outside() {", "    }", "}",
            ]
            flags = self.flags_by_name("swift", "\n".join(lines) + "\n")
            self.assert_in_out(f"@Suite {kind}", flags, ["inside"], ["outside"], "skip")

    def test_vo5_ruby_group_triggers_and_outside_at_describe_indentation(self):
        groups = [
            ("xdescribe \"G\" do", "skip"), ("xcontext \"G\" do", "skip"),
            ("describe \"G\", skip: \"x\" do", "skip"),
            ("fdescribe \"G\" do", "focused"), ("fcontext \"G\" do", "focused"),
            ("describe \"G\", focus: true do", "focused"), ("context \"G\", :focus do", "focused"),
        ]
        for head, flag in groups:
            text = "\n".join([
                head, "  it \"inside\" do", "    expect(1).to eq(1)", "  end", "end",
                "it \"outside\" do", "  expect(1).to eq(1)", "end",
            ]) + "\n"
            flags = self.flags_by_name("ruby", text)
            self.assert_in_out(head, flags, ["inside"], ["outside"], flag)

    def test_vo5_method_level_disabled_or_ignore_affects_only_its_own_test(self):
        cases = [
            ("java", ["class FooTest {", "    @Disabled", "    @Test", "    void own() {", "    }", "",
                      "    @Test", "    void neighbor() {", "    }", "}"]),
            ("kotlin", ["class FooTest {", "    @Disabled", "    @Test", "    fun own() {", "    }", "",
                        "    @Test", "    fun neighbor() {", "    }", "}"]),
            ("csharp", ["public class FooTests", "{", "    [Ignore(\"x\")]", "    [Fact]", "    public void Own()",
                        "    {", "    }", "", "    [Fact]", "    public void Neighbor()", "    {", "    }", "}"]),
        ]
        for lang, lines in cases:
            flags = self.flags_by_name(lang, "\n".join(lines) + "\n")
            own, neighbor = (("Own", "Neighbor") if lang == "csharp" else ("own", "neighbor"))
            self.assert_in_out(f"{lang} method-level", flags, [own], [neighbor], "skip")

    def test_b1_js_test_after_describe_skip_block_is_not_skipped(self):
        text = "\n".join([
            "describe.skip('G', () => {", "  it('inside', () => {", "    expect(1).toEqual(1);", "  });", "});",
            "it('after', () => {", "  expect(1).toEqual(1);", "});",
        ]) + "\n"
        flags = self.flags_by_name("javascript", text)
        self.assert_in_out("B1", flags, ["inside"], ["after"], "skip")


NEW_RUNNERS = ["dotnet", "rspec", "rake", "swift", "phpunit", "composer", "ctest"]


class TestVO8Runners(ScanTestCase):
    # VO8 (FR10, N3): equivalence partitioning over the 7 new runner candidates
    def entries(self, root):
        return self.scan(root)["runner_candidates"]

    def new_entries(self, root):
        return [e for e in self.entries(root) if e["runner"] in NEW_RUNNERS]

    def entry(self, runner, command, evidence):
        return {"runner": runner, "command": command, "evidence": evidence}

    def test_vo8_dotnet_evidence_is_first_sorted_root_sln_or_csproj(self):
        cases = {
            "single sln": (["a.sln"], "a.sln"),
            "single csproj": (["a.csproj"], "a.csproj"),
            "two sln": (["b.sln", "a.sln"], "a.sln"),
            "two csproj": (["b.csproj", "a.csproj"], "a.csproj"),
            "sln then csproj": (["b.csproj", "a.sln"], "a.sln"),
            "sorted together, csproj first": (["b.sln", "a.csproj"], "a.csproj"),
        }
        for label, (files, evidence) in cases.items():
            with self.subTest(case=label):
                root = self.tmp()
                for name in files:
                    self.write(root, name, "x\n")
                self.assertEqual(self.new_entries(root), [self.entry("dotnet", "dotnet test", evidence)])

    def test_vo8_dotnet_ignores_subdirectory_projects(self):
        root = self.tmp()
        self.write(root, "sub/a.sln", "x\n")
        self.write(root, "sub/a.csproj", "x\n")
        self.assertEqual(self.new_entries(root), [])

    def test_vo8_rspec_dot_rspec_vs_gemfile_and_spec_dir(self):
        cmd = "bundle exec rspec"
        with self.subTest(case=".rspec"):
            root = self.tmp()
            self.write(root, ".rspec", "--format doc\n")
            self.assertEqual(self.new_entries(root), [self.entry("rspec", cmd, ".rspec")])
        with self.subTest(case=".rspec wins over Gemfile+spec"):
            root = self.tmp()
            self.write(root, ".rspec", "x\n")
            self.write(root, "Gemfile", "x\n")
            (root / "spec").mkdir()
            self.assertEqual(self.new_entries(root), [self.entry("rspec", cmd, ".rspec")])
        with self.subTest(case="Gemfile and spec/"):
            root = self.tmp()
            self.write(root, "Gemfile", "x\n")
            (root / "spec").mkdir()
            self.assertEqual(self.new_entries(root), [self.entry("rspec", cmd, "Gemfile, spec/")])
        with self.subTest(case="Gemfile only"):
            root = self.tmp()
            self.write(root, "Gemfile", "x\n")
            self.assertEqual(self.new_entries(root), [])
        with self.subTest(case="spec/ only"):
            root = self.tmp()
            (root / "spec").mkdir()
            self.assertEqual(self.new_entries(root), [])

    def test_vo8_rake_needs_rakefile_and_test_dir(self):
        cmd = "bundle exec rake test"
        with self.subTest(case="Rakefile and test/"):
            root = self.tmp()
            self.write(root, "Rakefile", "x\n")
            (root / "test").mkdir()
            self.assertEqual(self.new_entries(root), [self.entry("rake", cmd, "Rakefile, test/")])
        with self.subTest(case="Rakefile only"):
            root = self.tmp()
            self.write(root, "Rakefile", "x\n")
            self.assertEqual(self.new_entries(root), [])
        with self.subTest(case="test/ only"):
            root = self.tmp()
            (root / "test").mkdir()
            self.assertEqual(self.new_entries(root), [])

    def test_vo8_swift_and_ctest_markers(self):
        root = self.tmp()
        self.write(root, "Package.swift", "// swift-tools-version:5.9\n")
        self.assertEqual(self.new_entries(root), [self.entry("swift", "swift test", "Package.swift")])
        root = self.tmp()
        self.write(root, "CMakeLists.txt", "project(x)\n")
        self.assertEqual(self.new_entries(root), [self.entry("ctest", "ctest --test-dir build", "CMakeLists.txt")])

    def test_vo8_phpunit_xml_vs_xml_dist(self):
        cmd = "vendor/bin/phpunit"
        with self.subTest(case="phpunit.xml"):
            root = self.tmp()
            self.write(root, "phpunit.xml", "<phpunit/>\n")
            self.assertEqual(self.new_entries(root), [self.entry("phpunit", cmd, "phpunit.xml")])
        with self.subTest(case="phpunit.xml.dist"):
            root = self.tmp()
            self.write(root, "phpunit.xml.dist", "<phpunit/>\n")
            self.assertEqual(self.new_entries(root), [self.entry("phpunit", cmd, "phpunit.xml.dist")])
        with self.subTest(case="both prefers phpunit.xml"):
            root = self.tmp()
            self.write(root, "phpunit.xml", "<phpunit/>\n")
            self.write(root, "phpunit.xml.dist", "<phpunit/>\n")
            self.assertEqual(self.new_entries(root), [self.entry("phpunit", cmd, "phpunit.xml")])

    def test_vo8_composer_requires_scripts_test(self):
        with self.subTest(case="scripts.test"):
            root = self.tmp()
            self.write(root, "composer.json", json.dumps({"scripts": {"test": "phpunit"}}))
            self.assertEqual(
                self.new_entries(root),
                [self.entry("composer", "composer test", "composer.json scripts.test")],
            )
        for label, content in (
            ("scripts without test", {"scripts": {"lint": "x"}}),
            ("no scripts", {"name": "a/b"}),
        ):
            with self.subTest(case=label):
                root = self.tmp()
                self.write(root, "composer.json", json.dumps(content))
                self.assertEqual(self.new_entries(root), [])

    def test_vo8_markers_only_in_subdirectory_yield_no_candidates(self):
        root = self.tmp()
        self.write(root, "sub/Package.swift", "x\n")
        self.write(root, "sub/.rspec", "x\n")
        self.write(root, "sub/Gemfile", "x\n")
        self.write(root, "sub/spec/a.txt", "x\n")
        self.write(root, "sub/Rakefile", "x\n")
        self.write(root, "sub/test/a.txt", "x\n")
        self.write(root, "sub/phpunit.xml", "x\n")
        self.write(root, "sub/composer.json", json.dumps({"scripts": {"test": "x"}}))
        self.write(root, "sub/CMakeLists.txt", "x\n")
        self.write(root, "sub/a.sln", "x\n")
        self.assertEqual(self.new_entries(root), [])

    def test_vo8_new_candidates_follow_existing_ones_in_fr10_order(self):
        root = self.tmp()
        self.write(root, "go.mod", "module x\n")
        self.write(root, "pom.xml", "x\n")
        self.write(root, "package.json", json.dumps({"scripts": {"test": "jest"}}))
        self.write(root, "a.sln", "x\n")
        self.write(root, ".rspec", "x\n")
        self.write(root, "Rakefile", "x\n")
        (root / "test").mkdir()
        self.write(root, "Package.swift", "x\n")
        self.write(root, "phpunit.xml", "x\n")
        self.write(root, "composer.json", json.dumps({"scripts": {"test": "phpunit"}}))
        self.write(root, "CMakeLists.txt", "x\n")
        names = [e["runner"] for e in self.entries(root)]
        self.assertEqual([n for n in names if n in NEW_RUNNERS], NEW_RUNNERS)
        old = [i for i, n in enumerate(names) if n not in NEW_RUNNERS]
        new = [i for i, n in enumerate(names) if n in NEW_RUNNERS]
        self.assertEqual({"go", "maven", "npm"} - set(names), set())
        self.assertLess(max(old), min(new))


class TestVO10Robustness(ScanTestCase):
    # VO10 (Errors, E1, E2, QR2, QR3): error guessing; no coverage target
    OTHER = "def test_ok():\n    assert 1\n"

    def snapshot(self, root):
        entries = {}
        for path in [root, *root.rglob("*")]:
            stat = path.lstat()
            entries[str(path.relative_to(root))] = (stat.st_mtime_ns, stat.st_size)
        return entries

    def scan_with_sibling(self, rel, text):
        root = self.tmp()
        self.write(root, rel, text)
        self.write(root, "test_ok.py", self.OTHER)
        result = run_scan(root)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual([t["name"] for t in self.entry_tests(data, "test_ok.py")], ["test_ok"])
        return data

    def test_e1_unbalanced_brace_in_each_brace_language(self):
        for lang in BRACE_LANGS:
            with self.subTest(lang=lang):
                tests = [T("a", body=[NEUTRAL[lang]], unclosed=True), T("b", body=[NEUTRAL[lang]])]
                data = self.scan_with_sibling(FILES[lang], render(lang, tests))
                names = [t["name"] for t in self.entry_tests(data, FILES[lang])]
                self.assertEqual(names, [test_name(lang, "a"), test_name(lang, "b")])

    def test_e1_unbalanced_brace_without_a_following_test(self):
        for lang in BRACE_LANGS:
            with self.subTest(lang=lang):
                data = self.scan_with_sibling(FILES[lang], render(lang, [T("a", body=[NEUTRAL[lang], "{"], unclosed=True, balance=False)]))
                names = [t["name"] for t in self.entry_tests(data, FILES[lang])]
                self.assertEqual(names, [test_name(lang, "a")])

    def test_e1_ruby_missing_end(self):
        text = "RSpec.describe Foo do\n  it \"a\" do\n    expect(x).to eq(1)\n  it \"b\" do\n    expect(x).to eq(1)\n"
        data = self.scan_with_sibling("foo_spec.rb", text)
        self.assertEqual([t["name"] for t in self.entry_tests(data, "foo_spec.rb")], ["a", "b"])

    def test_e1_brace_inside_string_literal_and_unterminated_string(self):
        for lang in BRACE_LANGS:
            for label, literal in (("brace in string", "\"{\""), ("unterminated string", "\"unterminated")):
                with self.subTest(lang=lang, case=label):
                    sn = {
                        "javascript": "const s = ", "typescript": "const s = ", "go": "s := ", "rust": "let s = ",
                        "java": "String s = ", "kotlin": "val s = ", "csharp": "string s = ", "swift": "let s = ",
                        "php": "$s = ", "cpp": "auto s = ",
                    }[lang] + literal
                    tests = [T("a", body=[sn, NEUTRAL[lang]], balance=False), T("b", body=[NEUTRAL[lang]])]
                    data = self.scan_with_sibling(FILES[lang], render(lang, tests))
                    names = [t["name"] for t in self.entry_tests(data, FILES[lang])]
                    self.assertEqual(names, [test_name(lang, "a"), test_name(lang, "b")])
        for label, literal in (("brace in string", "\"{\""), ("unterminated string", "\"unterminated")):
            with self.subTest(lang="ruby", case=label):
                text = f"RSpec.describe Foo do\n  it \"a\" do\n    s = {literal}\n  end\n\n  it \"b\" do\n  end\nend\n"
                data = self.scan_with_sibling("foo_spec.rb", text)
                self.assertEqual([t["name"] for t in self.entry_tests(data, "foo_spec.rb")], ["a", "b"])

    def test_e2_glob_without_content_is_clean_and_other_files_are_scanned(self):
        root = self.tmp()
        self.write(root, "tests/NoImportTests.swift", "final class NoImportTests {}\n")
        self.write(root, "test/no_macro_test.cpp", "int helper() { return 1; }\n")
        self.write(root, "tests/cfg_only.rs", "#[cfg(test)]\nmod tests {\n")
        self.write(root, "test_ok.py", self.OTHER)
        data = self.scan(root)
        self.assertEqual([f["path"] for f in data["files"]], ["test_ok.py"])
        for rel in ("tests/NoImportTests.swift", "test/no_macro_test.cpp", "tests/cfg_only.rs"):
            self.assertIn(rel, data["inventory"])

    def test_qr3_scan_never_writes_or_executes_new_language_trees(self):
        root = self.tmp()
        marker = root / "EXECUTED"
        script = f"touch {marker}"
        for lang in NEW_LANGS:
            tests = [T("a", body=[NEUTRAL[lang]]), T("b", body=[NEUTRAL[lang]])]
            self.write(root, f"src/{FILES[lang]}", render(lang, tests))
        self.write(root, "Gemfile", f"system('{script}')\n")
        self.write(root, "Package.swift", f"// {script}\n")
        self.write(root, "CMakeLists.txt", f"execute_process(COMMAND {script})\n")
        self.write(root, "Rakefile", f"system('{script}')\n")
        self.write(root, ".rspec", "--require spec_helper\n")
        self.write(root, "phpunit.xml", "<phpunit/>\n")
        self.write(root, "foo.sln", "x\n")
        self.write(root, "composer.json", json.dumps({"scripts": {"test": script}}))
        (root / "spec").mkdir()
        (root / "test").mkdir()
        before = self.snapshot(root)
        first = self.scan(root)
        self.scan(root)
        self.assertEqual(self.snapshot(root), before)
        self.assertFalse(marker.exists())
        self.assertEqual(
            sorted(f["language"] for f in first["files"]),
            sorted(["kotlin", "csharp", "swift", "php", "ruby", "cpp"]),
        )


NESTED = {
    "go": "if x {\n\t\tf()\n\t}", "rust": "if x {\n        f();\n    }", "swift": "if x {\n            f()\n        }",
    "php": "if ($x) {\n            f();\n        }", "cpp": "if (x) {\n    f();\n  }",
}
GENERIC_NESTED = "if (x) {\n            f();\n        }"


class TestBatch2BraceDepthAndGuards(RuleScanCase):
    # V2 (FR3(c), FR6): brace depth; V3 (FR9): guards outside any test; V4/V5/V6; A4
    def test_v2_nested_block_inside_body_then_trigger_vs_trigger_after_closer(self):
        for lang in BRACE_LANGS:
            nested = NESTED.get(lang, GENERIC_NESTED)
            nd = ND_BOUNDARY[lang]
            with self.subTest(lang=lang, position="after nested block, inside body"):
                _, found = self.scan_text(lang, render(lang, [T("a", body=[nested, nd]), T("b", body=[NEUTRAL[lang]])]))
                self.assertEqual(len(found), 2)
                self.assertIn("nondeterministic", found[0]["flags"])
                self.assertNotIn("nondeterministic", found[1]["flags"])
            with self.subTest(lang=lang, position="after closing brace"):
                _, found = self.scan_text(
                    lang, render(lang, [T("a", body=[nested], after=[nd]), T("b", body=[NEUTRAL[lang]])]))
                self.assertEqual(len(found), 2)
                self.assertNotIn("nondeterministic", found[0]["flags"])
                self.assertNotIn("nondeterministic", found[1]["flags"])

    def test_v2_js_describe_skip_group_with_nested_block_in_first_test(self):
        text = "\n".join([
            "describe.skip('G', () => {",
            "  it('first', () => {", "    if (x) {", "      f();", "    }", "  });",
            "  it('second', () => {", "    expect(1).toEqual(1);", "  });",
            "});",
            "it('after', () => {", "  expect(1).toEqual(1);", "});",
        ]) + "\n"
        _, found = self.scan_text("javascript", text)
        flags = {t["name"]: t["flags"] for t in found}
        self.assertIn("skip", flags["first"])
        self.assertIn("skip", flags["second"])
        self.assertNotIn("skip", flags["after"])

    def test_v2_java_disabled_class_with_nested_block_in_first_test(self):
        text = "\n".join([
            "@Disabled", "class FooTest {",
            "    @Test", "    void first() {", "        if (x) {", "            f();", "        }", "    }", "",
            "    @Test", "    void second() {", "    }",
            "}", "",
            "class OtherTest {", "    @Test", "    void after() {", "    }", "}",
        ]) + "\n"
        _, found = self.scan_text("java", text)
        flags = {t["name"]: t["flags"] for t in found}
        self.assertIn("skip", flags["first"])
        self.assertIn("skip", flags["second"])
        self.assertNotIn("skip", flags["after"])

    def test_v2_js_opener_after_options_object_still_puts_next_line_in_body(self):
        text = "it('x', { retry: 3 }, () => {\n  Math.random();\n});\n"
        _, found = self.scan_text("javascript", text)
        self.assertEqual(len(found), 1)
        self.assertIn("nondeterministic", found[0]["flags"])
        self.assertIn("retry", found[0]["flags"])

    def test_v3_guards_outside_any_test_body_suppress_nondeterministic(self):
        cases = {
            "python module-level import": (
                "python",
                "import freezegun\n\ndef test_a():\n    assert x == 1\n    time.time()\n"),
            "java field initializer": (
                "java",
                "class FooTest {\n    private final Clock clock = Clock.fixed(Instant.EPOCH, ZoneOffset.UTC);\n\n"
                "    @Test\n    void a() {\n        assertEquals(1, x);\n        Math.random();\n    }\n}\n"),
            "javascript beforeEach": (
                "javascript",
                "beforeEach(() => { jest.useFakeTimers(); });\n\nit('a', () => {\n  expect(x).toEqual(1);\n"
                "  Date.now();\n});\n"),
            "ruby before block": (
                "ruby",
                "RSpec.describe Foo do\n  before { travel_to(Time.at(0)) }\n\n  it \"a\" do\n"
                "    expect(x).to eq(1)\n    Time.now\n  end\nend\n"),
        }
        for label, (lang, text) in cases.items():
            with self.subTest(case=label):
                _, found = self.scan_text(lang, text)
                self.assertEqual(len(found), 1)
                self.assertNotIn("nondeterministic", found[0]["flags"])
                unguarded = text.replace("freezegun", "os").replace("Clock.fixed(Instant.EPOCH, ZoneOffset.UTC)", "null") \
                    .replace("jest.useFakeTimers()", "setup()").replace("travel_to(Time.at(0))", "setup")
                _, found = self.scan_text(lang, unguarded)
                self.assertIn("nondeterministic", found[0]["flags"])

    def test_v4_method_level_disabled_or_ignore_does_not_leak_into_later_class(self):
        def java_like(lang, nested):
            fn = "void {}() {{" if lang == "java" else "fun {}() {{"
            second = [
                "    class Inner {", "        @Test", "        " + fn.format("other"), "        }", "    }",
            ] if nested else []
            lines = ["class FooTest {", "    @Disabled", "    @Test", "    " + fn.format("own"), "    }"] + second + ["}"]
            if not nested:
                lines += ["", "class SecondTest {", "    @Test", "    " + fn.format("other"), "    }", "}"]
            return "\n".join(lines) + "\n"

        for lang in ("java", "kotlin"):
            for nested in (False, True):
                with self.subTest(lang=lang, nested=nested):
                    _, found = self.scan_text(lang, java_like(lang, nested))
                    flags = {t["name"]: t["flags"] for t in found}
                    self.assertIn("skip", flags["own"])
                    self.assertNotIn("skip", flags["other"])
        text = "\n".join([
            "public class FooTests", "{", "    [Ignore(\"x\")]", "    [Fact]", "    public void Own()", "    {", "    }",
            "}", "", "public class SecondTests", "{", "    [Fact]", "    public void Other()", "    {", "    }", "}",
        ]) + "\n"
        _, found = self.scan_text("csharp", text)
        flags = {t["name"]: t["flags"] for t in found}
        with self.subTest(lang="csharp"):
            self.assertIn("skip", flags["Own"])
            self.assertNotIn("skip", flags["Other"])

    DUPLICATES = {
        "kotlin": ("class AClassTest {\n    @Test\n    fun a() {\n    }\n}\n\nclass BClassTest {\n    @Test\n"
                   "    fun a() {\n    }\n\n    @Test\n    fun c() {\n    }\n}\n", "a", "c"),
        "csharp": ("public class OneTests\n{\n    [Fact]\n    public void A()\n    {\n    }\n}\n\n"
                   "public class TwoTests\n{\n    [Fact]\n    public void A()\n    {\n    }\n\n    [Fact]\n"
                   "    public void C()\n    {\n    }\n}\n", "A", "C"),
        "swift": ("import XCTest\nfinal class OneTests: XCTestCase {\n    func testA() {\n    }\n}\n\n"
                  "final class TwoTests: XCTestCase {\n    func testA() {\n    }\n\n    func testC() {\n    }\n}\n",
                  "testA", "testC"),
        "php": ("<?php\nclass OneTest extends TestCase\n{\n    public function testA()\n    {\n    }\n}\n\n"
                "class TwoTest extends TestCase\n{\n    public function testA()\n    {\n    }\n\n"
                "    public function testC()\n    {\n    }\n}\n", "testA", "testC"),
        "ruby": ("RSpec.describe One do\n  it \"a\" do\n  end\nend\n\nRSpec.describe Two do\n  it \"a\" do\n  end\n\n"
                 "  it \"c\" do\n  end\nend\n", "a", "c"),
        "cpp": ("TEST_CASE(\"a\") {\n}\n\nTEST_CASE(\"a\") {\n}\n\nTEST_CASE(\"c\") {\n}\n", "a", "c"),
    }

    def test_v5_duplicate_name_for_each_new_language(self):
        for lang, (text, dup, other) in self.DUPLICATES.items():
            with self.subTest(lang=lang):
                _, found = self.scan_text(lang, text)
                dups = [t for t in found if t["name"] == dup]
                self.assertEqual(len(dups), 2)
                for t in dups:
                    self.assertIn("duplicate_name", t["flags"])
                singles = [t for t in found if t["name"] == other]
                self.assertEqual(len(singles), 1)
                self.assertNotIn("duplicate_name", singles[0]["flags"])

    def test_v6_java_capitalized_and_primitive_return_types_are_tests(self):
        lines = [
            "class FooTest {",
            "    @Test", "    public String name() {", "        return null;", "    }", "",
            "    @Test", "    int count() {", "        return 1;", "    }",
            "}",
        ]
        root = self.tmp()
        self.write(root, "FooTest.java", "\n".join(lines) + "\n")
        data = self.scan(root)
        self.assertEqual(
            self.name_lines(data, "FooTest.java"),
            sorted([("name", line_of(lines, "    public String name() {")), ("count", line_of(lines, "    int count() {"))]),
        )

    def test_a4_comment_only_body_is_not_empty(self):
        for lang in BRACE_LANGS:
            with self.subTest(lang=lang):
                _, found = self.scan_text(lang, render(lang, [T("a", body=["// later"]), T("b")]))
                self.assertEqual(len(found), 2)
                self.assertNotIn("empty", found[0]["flags"])
                self.assertIn("empty", found[1]["flags"])


if __name__ == "__main__":
    unittest.main()
