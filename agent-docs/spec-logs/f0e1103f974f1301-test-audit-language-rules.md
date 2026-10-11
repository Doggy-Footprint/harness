---
version: 2
run_id: f0e1103f974f1301
status: complete
base_commit: 6ed9346f514dbfe8af390fb3ad6f1e740171d2e9
max_verifier_invocations: 2
handoff: none
---

# User Intent
| id | stakeholder | intention | observable goal |
| --- | --- | --- | --- |
| UI1 | harness user | Audit test suites in more languages with rule-based signals | `test_scan.py` detects and extracts tests for C#, Ruby, Kotlin, Swift, PHP, C/C++ in addition to the existing five |
| UI2 | harness user | Get deeper per-language rule-based auditing so the agent reads fewer files | 8 new per-test flags, test-group skip/focus propagation, fewer false `no_assert`, more runner candidates |
| UI3 | harness user | Know how to confirm each flag by reading | `test-audit` SKILL.md has a per-flag review table with known false positives |

# Scope
In scope: `harness/bin/test_scan.py` rules (languages, test forms, test body model, flags, group propagation, runners); `harness/skills/test-audit/SKILL.md` Scope and a new `# Flag review` section; 0.21.0 migration entry and VERSION; version-pinned tests.
Out of scope: Kotest, Spock/Groovy, Elixir, plain-C frameworks (Unity, CMocka); Go `t.Run` subtests as separate entries; RSpec anonymous one-liners (`it { ... }`) as tests; a `conditional_assert` flag; AST-level parsing for non-Python languages; running or modifying scanned code; changes to the JSON output shape.

# Paths
Implementation: harness/bin/test_scan.py, harness/skills/test-audit/SKILL.md, installer/harness.py, harness/VERSION
Tests: tests/test_test_scan_rules.py, tests/test_installer.py, tests/test_telemetry.py, tests/test_workflow_markers.py
Test command: python3 -m unittest discover -s tests
Review evidence: R1 — main checks SKILL.md `# Flag review` against FR11 (16 rows, each with a confirm-by-reading column and a false-positive column) and records the result in the execution ledger. R2 — main checks that every per-language regex lives in `LANGUAGES` and every entry has an identical key set (QR4). R3 — `git diff --stat 6ed9346f514dbfe8af390fb3ad6f1e740171d2e9 -- tests/test_test_scan.py` is empty (QR5).
Fuzzing: none — no fuzzing tool is installed; crash-freedom on malformed input is covered deterministically by VO10.
Mutation tool: none — mutmut/cosmic-ray are not installed and the user approved not installing tooling; 8–10 hand mutations replace it.

# Signatures
CLI: python3 .harness/bin/test_scan.py [PATH]   (unchanged)
Output JSON: unchanged shape. `files[].language` gains `kotlin`, `csharp`, `swift`, `php`, `ruby`, `cpp`. `tests[].flags` may additionally contain `trivial_assert`, `mock_only_assert`, `snapshot_only`, `broad_exception`, `swallowed_error`, `nondeterministic`, `retry`, `incomplete`. `runner_candidates[]` entries keep `{runner, command, evidence}`.

# Functional Requirements
Notation: snippets are literal source text, separated by ` · `. "H" = appears on a test's start or prefix line; otherwise it appears inside the test body. `⏎` is a newline. Each rule flags a test when any trigger snippet occurs in the test's body (FR3), unless stated otherwise.

| id | requirement | priority | source |
| --- | --- | --- | --- |
| FR1 | New language detection by file name (root-relative, excluded dirs unchanged): kotlin `*Test.kt`, `*Tests.kt`; csharp `*Test.cs`, `*Tests.cs`; swift `*Tests.swift`, `*Test.swift` and the file contains `import XCTest` or `import Testing`; php `*Test.php`; ruby `*_spec.rb`, `test_*.rb`, `*_test.rb`; cpp `*_test.cc`, `*_test.cpp`, `*_test.cxx`, `*_unittest.cc`, `*_unittest.cpp`, `test_*.cc`, `test_*.cpp`, `*Test.cpp`, `*Tests.cpp` and the file contains one of `TEST(`, `TEST_F(`, `TEST_P(`, `TYPED_TEST(`, `TYPED_TEST_P(`, `TEST_CASE(`, `TEST_CASE_METHOD(`, `SCENARIO(`. Rust detection accepts any test attribute of FR2 (not only `#[test]`); `#[cfg(test)]` alone does not qualify. A file failing a content requirement is not in `files` (it is in `inventory` if under a FR6 directory). | must | user |
| FR2 | Test start forms and names (`line` = the line holding the name, as today). **rust**: `#[test]`, `#[tokio::test]`, `#[tokio::test(flavor = "multi_thread")]`, `#[async_std::test]`, `#[rstest]`, `#[test_case(1)]`, then `fn <name>`. **java**: `@Test`, `@ParameterizedTest`, `@RepeatedTest(3)`, `@TestFactory`, `@TestTemplate`, `@Property`, `@RetryingTest(3)`, `@RepeatedIfExceptionsTest(repeats = 3)`, then a method whose return type is `void`, a primitive, or a capitalized (optionally generic) type, e.g. `void a()`, `public void a()`, `Stream<DynamicTest> a()`; the name is the method name. **go**: also `func Fuzz<X>(f *testing.F)`. **kotlin**: the Java annotations above (`@Test`…`@RetryingTest`), then `fun <name>` or ``fun `<words>`()`` whose name is the text between backticks. **csharp**: `[Fact]`, `[Theory]`, `[Test]`, `[TestCase(1)]`, `[TestCaseSource(nameof(Cases))]`, `[TestMethod]`, `[DataTestMethod]`, `[SkippableFact]`, `[RetryFact]` (also when combined, e.g. `[Test, Category("x")]`, or with arguments, e.g. `[Fact(Skip = "x")]`), then `void|Task|ValueTask <name>(` (modifiers such as `public async` allowed); `[TestFixture]`, `[TestClass]`, `[SetUp]` are not starts. **swift**: `func test<X>(` (any modifiers/`async throws`), and `@Test`, `@Test("display")` followed by `func <name>(`. **php**: `function test<X>(` with optional `public/protected/private/static/final`; `#[Test]` or a docblock line `/** @test */` / ` * @test` followed by `function <name>(`; Pest `it('<title>', …` and `test('<title>', …` (name = title). **ruby**: `it`, `specify`, `example`, `scenario`, with optional `x`/`f` prefix, followed by a quoted title, with or without parentheses (`it "a" do`, `it('a') do`, `it("a") { … }`); `test "<title>"`; `def test_<x>`. **cpp**: `TEST(S, N)`, `TEST_F(S, N)`, `TEST_P(S, N)`, `TYPED_TEST(S, N)`, `TYPED_TEST_P(S, N)` → name `S.N`; `TEST_CASE("<t>"…)`, `SCENARIO("<t>"…)`, `TEST_CASE_METHOD(F, "<t>"…)` → name `<t>`. All pre-existing start forms keep working. | must | user |
| FR3 | Test body (non-Python). (a) Several start matches resolving to the same name line form one test (e.g. `[TestCase(1)]⏎[TestCase(2)]⏎public void A(int x)` → one test `A`). (b) The body begins at the start line extended upward over contiguous prefix lines directly above it: rust/java/kotlin/swift lines beginning `#[` or `@` (per language: rust `#[`, java/kotlin/swift `@`), csharp lines beginning `[`, php lines beginning `#[`, `/**`, or `*`. The upward extension never crosses into the previous test's body (a one-line test directly above stays its own test). (c) Brace languages (all except ruby/python): the body ends at the line of the brace that closes the first block opened after the test name (javascript: the block after `=>` or `)`; others: the first `{`), clamped to the line before the next test's body start; when no opener or no matching closer exists within that clamp, the body ends at the clamp (or EOF). (d) ruby: the body ends before the first later non-blank line whose indentation is ≤ the start line's, and includes that line when it begins with `end` or `}`; clamped as in (c). (e) Python body is unchanged. | must | plan |
| FR4 | `empty`: brace languages as today (only whitespace between the test block's braces); ruby: the start line ends with `do` (optionally `\|args\|`) or is a `def`, and the next non-blank line is `end` at the start line's indentation. A bodiless ruby `it "x"` followed by an `end` at lower indentation is not `empty`. | must | plan |
| FR5 | Assertion classification on the body: S = snapshot rule matches; M = mock-assert rule matches after removing S matches; A = assert rule matches after removing S and M matches. `no_assert` iff S=M=A=0. `snapshot_only` iff S>0, M=0, A=0. `mock_only_assert` iff M>0, S=0, A=0. | must | plan |
| FR6 | Group propagation: a test whose start line lies inside a group block gets the group's flag. Brace-language block = the brace block following the group match; ruby block = indentation range (FR3 d); python groups via AST. Group rules: **python** class decorator text matching the python skip rule → `skip`, matching the xfail rule → `xfail` (applies to nested classes); module-level `pytestmark = pytest.mark.skip(reason="x")` / `pytestmark = [pytest.mark.xfail]` → all tests in the file. **javascript** skip: `xdescribe(` · `describe.skip(` · `context.skip(` · `xcontext(`; focused: `fdescribe(` · `describe.only(` · `context.only(`. **java**/**kotlin** skip: `@Disabled` or `@Ignore(...)` annotation before `class` with no `{`/`;` in between (e.g. `@Disabled⏎class FooTest {`, `@Disabled⏎@Nested⏎class Inner {`). **csharp** skip: `[Ignore(...)]`/`[Explicit]` before `class`. **swift** skip: `@Suite(.disabled("x"))` before `struct`/`class`. **ruby** skip: `xdescribe` · `xcontext` · `describe "G", skip: "x" do`; focused: `fdescribe` · `fcontext` · `describe "G", focus: true do` · `context "G", :focus do`. A method-level `@Disabled`/`[Ignore]` affects only its own test. | must | plan |
| FR7 | Per-language rules for existing languages (pre-existing rules unchanged). See table R-PY, R-JS, R-GO, R-RS, R-JV below. | must | plan |
| FR8 | Per-language rules for new languages. See tables R-KT, R-CS, R-SW, R-PHP, R-RB, R-CPP below. Each new language also gets `skip`/`xfail`/`focused`/`sleep`/assert/mock rules as listed; `heavy_mock` (≥5 mock matches) and `duplicate_name` apply as today. | must | plan |
| FR9 | `nondeterministic` is not set for any test when the language's guard snippet occurs anywhere in the file. | must | plan |
| FR10 | Runner candidates (scan root only), appended in this order after the existing ones: `dotnet`/`dotnet test` (evidence: first name when all root `*.sln` and `*.csproj` file names are sorted together); `rspec`/`bundle exec rspec` (evidence `.rspec` if present, else `Gemfile, spec/` when both exist); `rake`/`bundle exec rake test` (evidence `Rakefile, test/` when both exist); `swift`/`swift test` (`Package.swift`); `phpunit`/`vendor/bin/phpunit` (evidence `phpunit.xml`, else `phpunit.xml.dist`); `composer`/`composer test` (evidence `composer.json scripts.test`, only if scripts.test exists); `ctest`/`ctest --test-dir build` (`CMakeLists.txt`). | must | plan |
| FR11 | SKILL.md: the Scope paragraph names all 11 languages and all 16 flags; a new `# Flag review` section after Scope holds one table with exactly one row per flag (16 rows) and columns flag, confirm by reading, known false positives. Other sections unchanged. | must | user |
| FR12 | `harness/VERSION` = `0.21.0`; MIGRATIONS has a `0.21.0` entry labeled `expand test-audit scanner rules to more languages, flags, and runners` whose step lines say the scanner and skill are replaced and no existing project files change. | must | AGENTS.md |

## Rule tables
Columns: flag | triggers (must set the flag) | non-triggers (must not set the flag).

### R-PY (python)
| flag | triggers | non-triggers |
| --- | --- | --- |
| trivial_assert | `assert True` · `assert (x == 1, "msg")` · `self.assertTrue(True)` | `assert 1` · `assert x == 1` · `assert (x == 1)` |
| mock assert (FR5 M) | `m.assert_called_once_with(1)` · `m.assert_called()` · `m.assert_not_called()` · `m.assert_has_calls([])` · `m.assert_awaited_once()` | `assert m.value == 1` |
| snapshot (FR5 S) | `assert result == snapshot` · `snapshot.assert_match(result, "name")` | `assert result == expected` |
| broad_exception | `with pytest.raises(Exception):` · `with pytest.raises(BaseException):` · `with self.assertRaises(Exception):` | `with pytest.raises(ValueError):` · `with pytest.raises(Exception, match="boom"):` |
| swallowed_error | `except ValueError:⏎        pass` · `except Exception:⏎        ...` · `except:⏎        pass` | `except ValueError:⏎        raise` |
| nondeterministic | `random.randint(1, 6)` · `datetime.now()` · `datetime.utcnow()` · `date.today()` · `time.time()` · `uuid.uuid4()` | `datetime(2020, 1, 1)` |
| guard (FR9) | `@freeze_time("2020-01-01")` · `import freezegun` · `random.seed(0)` · `import time_machine` | |
| retry | `@pytest.mark.flaky(reruns=3)` · `@flaky` | `@pytest.mark.slow` |
| incomplete | `raise NotImplementedError` | `raise ValueError("x")` |

### R-JS (javascript/typescript)
| flag | triggers | non-triggers |
| --- | --- | --- |
| trivial_assert | `expect(true).toBe(true);` · `expect(true).toBeTruthy();` · `expect(false).toBe(false);` · `assert.ok(true);` · `assert(true);` | `expect(x).toBe(true);` |
| mock assert | `expect(fn).toHaveBeenCalled();` · `expect(fn).toHaveBeenCalledWith(1);` · `expect(fn).toHaveBeenCalledTimes(2);` · `expect(fn).not.toHaveBeenCalled();` · `expect(fn).toBeCalled();` · `sinon.assert.calledOnce(fn);` | `expect(fn()).toBe(1);` |
| snapshot | `expect(tree).toMatchSnapshot();` · `expect(tree).toMatchInlineSnapshot();` · `expect(() => f()).toThrowErrorMatchingSnapshot();` | `expect(tree).toEqual(x);` |
| broad_exception | `expect(() => f()).toThrow();` · `expect(() => f()).toThrowError();` · `await expect(p).rejects.toThrow();` | `expect(() => f()).toThrow(TypeError);` · `expect(() => f()).toThrow('boom');` |
| swallowed_error | `try { f(); } catch (e) {}` · `try { f(); } catch {}` · `p.catch(() => {});` | `try { f(); } catch (e) { throw e; }` |
| nondeterministic | `Math.random()` · `Date.now()` · `new Date()` · `crypto.randomUUID()` | `new Date(2020, 0, 1)` |
| guard | `jest.useFakeTimers()` · `vi.useFakeTimers()` · `vi.setSystemTime(0)` · `MockDate.set(0)` · `faker.seed(1)` | |
| retry | `jest.retryTimes(3);` · `this.retries(2);` · H `it('x', { retry: 3 }, () => {` | `const retries = 3;` |
| incomplete | H `it.todo('later');` · H `test.todo('later');` | H `it('now', () => {` |

### R-GO (go)
| flag | triggers | non-triggers |
| --- | --- | --- |
| skip (added) | `if testing.Short() {` · `f.Skip("x")` | `t.Log("x")` |
| trivial_assert | `assert.True(t, true)` · `require.True(t, true)` · `assert.False(t, false)` | `assert.True(t, ok)` |
| mock assert | `m.AssertExpectations(t)` · `m.AssertCalled(t, "Get")` · `m.AssertNumberOfCalls(t, "Get", 1)` · `m.AssertNotCalled(t, "Get")` · `m.EXPECT().Get().Return(1)` | `assert.Equal(t, 1, got)` |
| snapshot | `snaps.MatchSnapshot(t, got)` · `snaps.MatchJSON(t, got)` · `cupaloy.SnapshotT(t, got)` | `assert.JSONEq(t, want, got)` |
| broad_exception | `assert.Error(t, err)` · `require.Error(t, err)` | `assert.ErrorIs(t, err, ErrNotFound)` · `require.EqualError(t, err, "x")` · `assert.NoError(t, err)` |
| swallowed_error | `_ = f()` · `_ = obj.Close()` · `v, _ := parse(s)` · `v, _ = parse(s)` | `for _, v := range xs {` · `v, err := parse(s)` |
| nondeterministic | `time.Now()` · `rand.Intn(10)` · `rand.Float64()` · `rand.Shuffle(n, swap)` · `uuid.New()` | `time.Date(2020, 1, 1, 0, 0, 0, 0, time.UTC)` · `r.Intn(10)` |
| guard | `rand.New(rand.NewSource(1))` · `rand.Seed(1)` · `clockwork.NewFakeClock()` | |

### R-RS (rust)
| flag | triggers | non-triggers |
| --- | --- | --- |
| trivial_assert | `assert!(true);` · `assert!(!false);` | `assert!(ok);` |
| mock assert | `mock.expect_get().returning(\|\| 1);` | `let v = opt.expect("value");` |
| snapshot | `insta::assert_snapshot!(out);` · `assert_debug_snapshot!(out);` · `assert_json_snapshot!(out);` | `assert_eq!(out, "x");` |
| broad_exception | H `#[should_panic]` · `assert!(result.is_err());` | H `#[should_panic(expected = "boom")]` · `assert!(matches!(result, Err(Error::NotFound)));` |
| swallowed_error | `let _ = fs::remove_file(p);` · `fs::remove_file(p).ok();` | `let _guard = lock();` · `let v = f().ok().unwrap();` |
| nondeterministic | `rand::random::<u8>()` · `rand::thread_rng()` · `rand::rng()` · `SystemTime::now()` · `Utc::now()` · `Local::now()` · `Uuid::new_v4()` | `Duration::from_secs(1)` |
| guard | `StdRng::seed_from_u64(1)` · `StdRng::from_seed([0; 32])` | |
| incomplete | `todo!()` · `unimplemented!()` | `unreachable!()` |

### R-JV (java)
| flag | triggers | non-triggers |
| --- | --- | --- |
| trivial_assert | `assertTrue(true);` · `assertFalse(false);` · `Assertions.assertTrue(true);` · `assertThat(true).isTrue();` | `assertTrue(ok);` |
| mock assert | `verify(repo).save(x);` · `verify(repo, times(2)).save(x);` · `verifyNoMoreInteractions(repo);` · `then(repo).should().save(x);` | `assertEquals(1, x);` |
| snapshot | `Approvals.verify(out);` · `expect.toMatchSnapshot(out);` | `assertEquals(out, x);` |
| broad_exception | H `@Test(expected = Exception.class)` · `assertThrows(Exception.class, () -> f());` · `assertThrows(RuntimeException.class, () -> f());` · `assertThrows(Throwable.class, () -> f());` | `assertThrows(IllegalArgumentException.class, () -> f());` · H `@Test(expected = IllegalStateException.class)` |
| swallowed_error | `catch (Exception e) {}` · `catch (IOException e) {⏎    }` | `catch (Exception e) { throw new AssertionError(e); }` |
| nondeterministic | `Math.random()` · `new Random()` · `System.currentTimeMillis()` · `LocalDateTime.now()` · `Instant.now()` · `UUID.randomUUID()` | `new Random(42)` · `Instant.now(clock)` |
| guard | `Clock.fixed(Instant.EPOCH, ZoneOffset.UTC)` | |
| retry | H `@RetryingTest(3)` · H `@RepeatedIfExceptionsTest(repeats = 3)` | H `@RepeatedTest(3)` |
| incomplete | `throw new UnsupportedOperationException("todo");` · `fail("Not implemented");` · `fail("TODO");` | `fail("unexpected value");` |

### R-KT (kotlin)
| flag | triggers | non-triggers |
| --- | --- | --- |
| skip | H `@Disabled` · H `@Ignore` | H `@Test` |
| assert | `assertEquals(1, x)` · `assertTrue(ok)` · `assertThrows<IllegalStateException> { f() }` · `assertFailsWith<IllegalStateException> { f() }` · `assertThat(x).isEqualTo(1)` · `x shouldBe 1` · `fail("x")` · `expectThat(x).isEqualTo(1)` | (no_assert when none present) |
| trivial_assert | `assertTrue(true)` · `assertFalse(false)` · `true shouldBe true` | `ok shouldBe true` |
| mock assert | `verify { repo.save(x) }` · `verify(exactly = 1) { repo.save(x) }` · `coVerify { repo.save(x) }` · `confirmVerified(repo)` · `verify(repo).save(x)` | `assertEquals(1, x)` |
| broad_exception | `assertThrows<Exception> { f() }` · `assertFailsWith<Exception> { f() }` · `shouldThrow<Exception> { f() }` · `shouldThrowAny { f() }` · `assertThrows(Exception::class.java) { f() }` · `assertThrows<RuntimeException> { f() }` · `assertThrows<Throwable> { f() }` | `assertThrows<IllegalStateException> { f() }` |
| swallowed_error | `catch (e: Exception) {}` | `catch (e: Exception) { throw e }` |
| nondeterministic | `Random.nextInt()` · `System.currentTimeMillis()` · `LocalDateTime.now()` · `Instant.now()` · `UUID.randomUUID()` · `Clock.System.now()` | `Random(42).nextInt()` |
| guard | `Clock.fixed(Instant.EPOCH, ZoneOffset.UTC)` | |
| retry | H `@RetryingTest(3)` | H `@RepeatedTest(3)` |
| incomplete | `TODO()` · `TODO("later")` | `// TODO later` |
| sleep | `Thread.sleep(100)` · `delay(100)` | |
| mock (heavy_mock) | `mockk<Repo>()` · `spyk(obj)` · `every { repo.get() } returns 1` · `coEvery { repo.load() } returns 1` · `mock<Repo>()` · `whenever(repo.get()).thenReturn(1)` | |

### R-CS (csharp)
| flag | triggers | non-triggers |
| --- | --- | --- |
| skip | H `[Fact(Skip = "flaky")]` · H `[Ignore("x")]` · H `[Explicit]` · `Skip.If(cond);` · `Assert.Ignore("x");` | H `[Fact]` |
| assert | `Assert.Equal(1, x);` · `Assert.That(x, Is.EqualTo(1));` · `Assert.Throws<ArgumentException>(() => F());` · `CollectionAssert.AreEqual(a, b);` · `x.Should().Be(1);` · `x.ShouldBe(1);` | |
| trivial_assert | `Assert.True(true);` · `Assert.IsTrue(true);` · `Assert.False(false);` · `true.Should().BeTrue();` | `Assert.True(ok);` |
| mock assert | `repo.Verify(r => r.Save(x), Times.Once());` · `repo.VerifyAll();` · `repo.Received().Save(x);` · `repo.DidNotReceive().Save(x);` · `A.CallTo(() => repo.Save(x)).MustHaveHappened();` | `Assert.Equal(1, x);` |
| snapshot | `await Verify(result);` · `result.ShouldMatchSnapshot();` · `result.MatchSnapshot();` | `result.ShouldBe(expected);` |
| broad_exception | `Assert.Throws<Exception>(() => F());` · `await Assert.ThrowsAsync<Exception>(() => F());` · `Assert.ThrowsAny<Exception>(() => F());` · H `[ExpectedException(typeof(Exception))]` · `act.Should().Throw<Exception>();` | `Assert.Throws<ArgumentException>(() => F());` |
| swallowed_error | `catch {}` · `catch (Exception) {}` · `catch (Exception ex) { }` | `catch (Exception ex) { throw; }` |
| nondeterministic | `DateTime.Now` · `DateTime.UtcNow` · `DateTimeOffset.UtcNow` · `Guid.NewGuid()` · `new Random()` · `Random.Shared.Next()` | `new Random(42)` · `new DateTime(2020, 1, 1)` |
| guard | `new FakeTimeProvider()` | |
| retry | H `[Retry(3)]` · H `[RetryFact]` | H `[Repeat(3)]` |
| incomplete | `Assert.Inconclusive("todo");` · `throw new NotImplementedException();` | `throw new InvalidOperationException();` |
| sleep | `Thread.Sleep(100);` · `await Task.Delay(100);` | |
| mock (heavy_mock) | `new Mock<IRepo>()` · `Mock.Of<IRepo>()` · `Substitute.For<IRepo>()` · `A.Fake<IRepo>()` · `repo.Setup(r => r.Get())` | |

### R-SW (swift)
| flag | triggers | non-triggers |
| --- | --- | --- |
| skip | `throw XCTSkip("x")` · `try XCTSkipIf(cond)` · `try XCTSkipUnless(cond)` · H `@Test(.disabled("x"))` · H `@Test(.enabled(if: flag))` | H `@Test(.tags(.fast))` |
| xfail | `XCTExpectFailure("x")` · `withKnownIssue {` | |
| assert | `XCTAssertEqual(a, b)` · `XCTFail("x")` · `try XCTUnwrap(v)` · `#expect(a == b)` · `try #require(v)` | |
| trivial_assert | `XCTAssert(true)` · `XCTAssertTrue(true)` · `XCTAssertFalse(false)` · `#expect(true)` | `XCTAssertTrue(ok)` |
| mock assert | `verify(mock).save(any())` | `XCTAssertEqual(a, b)` |
| snapshot | `assertSnapshot(of: view, as: .image)` · `assertSnapshots(of: view, as: [.image])` · `assertInlineSnapshot(of: v, as: .json)` | `XCTAssertEqual(v, w)` |
| broad_exception | `XCTAssertThrowsError(try f())` (nothing after `)` on the line) · `#expect(throws: Error.self) { try f() }` · `#expect(throws: (any Error).self) { try f() }` | `XCTAssertThrowsError(try f()) { error in` · `#expect(throws: ParseError.self) { try f() }` |
| swallowed_error | `try? f()` · `catch {}` | `try f()` · `catch { XCTFail("\(error)") }` |
| nondeterministic | `Date()` · `Date.now` · `UUID()` · `Int.random(in: 0..<10)` · `items.randomElement()` · `items.shuffled()` | `Date(timeIntervalSince1970: 0)` |
| sleep | `sleep(1)` · `usleep(10)` · `try await Task.sleep(nanoseconds: 1)` · `Thread.sleep(forTimeInterval: 1)` | |
| mock (heavy_mock) | `MockRepo()` · `stub(mock) { s in }` · `given(mock.get()).willReturn(1)` | |

### R-PHP (php)
| flag | triggers | non-triggers |
| --- | --- | --- |
| skip | `$this->markTestSkipped('x');` · H `->skip()` (Pest) | |
| focused | H `->only()` (Pest) | |
| incomplete | `$this->markTestIncomplete('x');` · H `->todo()` (Pest) | |
| assert | `$this->assertSame(1, $x);` · `self::assertEquals(1, $x);` · `expect($x)->toBe(1);` · `$this->expectException(InvalidArgumentException::class);` · `$this->fail('x');` | |
| trivial_assert | `$this->assertTrue(true);` · `$this->assertFalse(false);` · `self::assertTrue(true);` · `expect(true)->toBeTrue();` | `$this->assertTrue($ok);` |
| mock assert | `$mock->expects($this->once())->method('save');` · `$mock->shouldReceive('save')->once();` · `$spy->shouldHaveReceived('save');` | `$this->assertSame(1, $x);` |
| snapshot | `$this->assertMatchesSnapshot($out);` · `$this->assertMatchesJsonSnapshot($out);` · `expect($out)->toMatchSnapshot();` | `$this->assertSame($out, $x);` |
| broad_exception | `$this->expectException(Exception::class);` · `$this->expectException(\Exception::class);` · `$this->expectException(\Throwable::class);` · `expect(fn () => f())->toThrow(Exception::class);` | `$this->expectException(InvalidArgumentException::class);` |
| swallowed_error | `catch (Exception $e) {}` · `catch (\Throwable) {}` | `catch (Exception $e) { throw $e; }` |
| nondeterministic | `time()` · `rand(1, 6)` · `mt_rand()` · `random_int(1, 6)` · `uniqid()` · `new DateTime()` · `new \DateTimeImmutable()` · `Carbon::now()` | `new DateTime('2020-01-01')` · `strtotime('2020-01-01')` |
| guard | `Carbon::setTestNow('2020-01-01');` · `mt_srand(1);` · `ClockMock::register(self::class);` | |
| retry | H `@retry 3` (docblock line) · H `#[Retry(3)]` | H `@group slow` |
| sleep | `sleep(1);` · `usleep(10);` | |
| mock (heavy_mock) | `$this->createMock(Repo::class)` · `$this->createStub(Repo::class)` · `$this->getMockBuilder(Repo::class)` · `$this->prophesize(Repo::class)` · `Mockery::mock(Repo::class)` | |

### R-RB (ruby)
| flag | triggers | non-triggers |
| --- | --- | --- |
| skip | H `xit "x" do` · `skip "later"` (own line) · H `it "x", skip: "later" do` | H `it "can skip" do` |
| xfail | `pending "flaky"` (own line) · H `it "x", pending: "y" do` | |
| focused | H `fit "x" do` · H `it "x", focus: true do` · H `it "x", :focus do` | |
| incomplete | H `it "later"` (no block on that line) · `raise NotImplementedError` | H `it "now" do` |
| assert | `expect(x).to eq(1)` · `expect { f }.to change { y }` · `is_expected.to eq(1)` · `x.should eq(1)` · `assert_equal 1, x` · `refute x` · `x.must_equal 1` · `x.wont_be_nil` · `flunk "x"` | |
| trivial_assert | `expect(true).to be(true)` · `expect(true).to be_truthy` · `expect(true).to eq(true)` · `assert true` · `assert(true)` | `expect(ok).to be(true)` · `assert ok` |
| mock assert | `expect(repo).to receive(:save)` · `expect(repo).to have_received(:save)` · `expect(repo).not_to receive(:save)` · `mock.verify` | `expect(x).to eq(1)` |
| snapshot | `expect(out).to match_snapshot("name")` · `assert_matches_snapshot(out)` | `expect(out).to eq(x)` |
| broad_exception | `expect { f }.to raise_error` · `expect { f }.to raise_error(StandardError)` · `expect { f }.to raise_error(Exception)` · `assert_raises { f }` · `assert_raises do` · `assert_raises(StandardError) { f }` | `expect { f }.to raise_error(ArgumentError)` · `assert_raises(ArgumentError) { f }` |
| swallowed_error | `rescue StandardError⏎    end` (rescue line directly followed by `end`) · `f rescue nil` | `rescue StandardError => e⏎      raise` |
| nondeterministic | `Time.now` · `Date.today` · `DateTime.now` · `rand(10)` · `SecureRandom.uuid` · `[1, 2].sample` · `[1, 2].shuffle` | `Time.at(0)` |
| guard | `travel_to(Time.at(0))` · `freeze_time` · `Timecop.freeze(Time.at(0))` · `srand(1)` | |
| retry | H `it "x", retry: 3 do` · `:retry => 3` | `retries = 3` |
| sleep | `sleep 1` | |
| mock (heavy_mock) | `double("repo")` · `instance_double(Repo)` · `class_double(Repo)` · `spy("repo")` · `allow(repo).to receive(:get)` · `Minitest::Mock.new` | |

### R-CPP (cpp)
| flag | triggers | non-triggers |
| --- | --- | --- |
| skip | H `TEST(MathTest, DISABLED_Adds)` · H `TEST(DISABLED_MathTest, Adds)` · `GTEST_SKIP() << "x";` · H `TEST_CASE("x", "[.]")` · H `TEST_CASE("x", "[.integration]")` · H `TEST_CASE("x", "[!hide]")` · H `TEST_CASE("x" * doctest::skip())` | H `TEST_CASE("x", "[math]")` |
| xfail | H `TEST_CASE("x", "[!shouldfail]")` · H `TEST_CASE("x", "[!mayfail]")` · H `TEST_CASE("x" * doctest::should_fail())` · H `TEST_CASE("x" * doctest::may_fail())` | |
| assert | `EXPECT_EQ(1, x);` · `ASSERT_NE(p, nullptr);` · `REQUIRE(x == 1);` · `CHECK_FALSE(x);` · `FAIL("x");` · `ADD_FAILURE();` | |
| trivial_assert | `EXPECT_TRUE(true);` · `ASSERT_TRUE(true);` · `EXPECT_FALSE(false);` · `REQUIRE(true);` · `CHECK(true);` · `SUCCEED();` | `EXPECT_TRUE(ok);` |
| mock assert | `EXPECT_CALL(mock, Save(_)).Times(1);` | `EXPECT_EQ(1, x);` |
| snapshot | `Approvals::verify(out);` | `EXPECT_EQ(out, x);` |
| broad_exception | `EXPECT_ANY_THROW(f());` · `ASSERT_ANY_THROW(f());` · `REQUIRE_THROWS(f());` · `CHECK_THROWS(f());` · `EXPECT_THROW(f(), std::exception);` | `EXPECT_THROW(f(), std::invalid_argument);` · `REQUIRE_THROWS_AS(f(), std::invalid_argument);` |
| swallowed_error | `catch (...) {}` · `catch (const std::exception&) {}` | `catch (...) { FAIL(); }` |
| nondeterministic | `rand()` · `std::random_device rd;` · `time(nullptr)` · `time(NULL)` · `std::chrono::system_clock::now()` | `std::mt19937 gen(42);` |
| guard | `srand(42);` | |
| sleep | `std::this_thread::sleep_for(1ms);` · `sleep(1);` · `usleep(10);` | |
| mock (heavy_mock) | `MOCK_METHOD(int, Get, (), (override));` · `EXPECT_CALL(m, Get());` · `ON_CALL(m, Get());` · `NiceMock<MockRepo> m;` · `StrictMock<MockRepo> m;` | |

Rules not listed for a language are absent for it (e.g. no `retry` for go/rust/swift/cpp, no `focused` for java/kotlin/csharp/swift/cpp/go/rust/python).

# Errors
- Unbalanced braces or missing `end` in any language — no traceback, exit 0; bodies clamp at the next test start or EOF (FR3); other files still scanned.
- Unterminated string or a brace inside a string literal — same as above (brace matching may be approximate; output stays valid JSON).
- File matching a glob but failing the content requirement (swift, cpp, rust) — not listed in `files`; listed in `inventory` when under a FR6 directory.
- Pre-existing error behaviors (missing PATH, Python syntax error, undecodable bytes, git unavailable) — unchanged.

# Cases
| id | level | input / state | expected result |
| --- | --- | --- | --- |
| N1 | normal | one test file per new language, each with two tests | language, names, lines per FR2 |
| N2 | normal | every rule-table trigger/non-trigger snippet in its own test | flag set / not set per table |
| N3 | normal | new runner markers at root | candidates per FR10 in order |
| B1 | boundary | JS `describe.skip` block followed by a test after its closing brace | inside test `skip`, following test not `skip` |
| B2 | boundary | Ruby `xdescribe` block; next test at the describe's indentation | inside `skip`, outside not |
| B3 | boundary | C# `[TestCase(1)]⏎[TestCase(2)]⏎public void A(int x)` | one test `A`, no `duplicate_name` |
| B4 | boundary | Rust `#[ignore]` directly above a `#[test]`, previous test ends on the line before | only the second test is `skip` |
| B5 | boundary | nondeterministic trigger with guard absent / guard elsewhere in file | set / not set |
| E1 | error | unbalanced `{` in each brace language, missing `end` in ruby | exit 0, no traceback, tests extracted, other files scanned |
| E2 | error | `FooTests.swift` without XCTest/Testing import, `foo_test.cpp` without test macros, `.rs` with only `#[cfg(test)]` under `tests/` | not in files; in inventory |
| G1 | edge | test with only mock assertions / only snapshot assertions | `mock_only_assert` / `snapshot_only`; no `no_assert` |
| G2 | edge | Kotlin backtick name | name is text between backticks |
| G3 | edge | gtest same test name in two suites | names `A.X`, `B.X`; no `duplicate_name` |
| G4 | edge | JS `describe.skip(` line placed after a test's closing brace | that earlier test is not `skip` |

# Quality Applicability
| ISO/IEC 25010:2023 characteristic | applicable | rationale |
| --- | --- | --- |
| Functional suitability | yes | core |
| Performance efficiency | no | occasional user-invoked one-shot tool (same as prior run) |
| Compatibility | yes | installed into any repo: stdlib only; existing output and tests stay compatible |
| Interaction capability | no | output is JSON read by an agent |
| Reliability | yes | must finish on malformed source in any language |
| Security | yes | must never write to or execute the scanned repo |
| Maintainability | yes | single pattern table remains the only extension point |
| Flexibility | no | covered by Maintainability |
| Safety | no | no physical harm |

# Quality Requirements
| id | characteristic / subcharacteristic | target and context | measure method / inputs / unit | threshold and direction | evidence: automated, review, mutation | source |
| --- | --- | --- | --- | --- | --- | --- |
| QR1 | Compatibility / co-existence | test_scan.py imports | non-stdlib import count (AST vs sys.stdlib_module_names) | = 0 | automated (existing VO8 test) | prior spec |
| QR2 | Reliability / fault tolerance | E1, E2 inputs for 11 languages | traceback count / non-zero exits | = 0 | automated VO10 | Errors |
| QR3 | Security / integrity | tree with new-language files and runner markers (Gemfile, Package.swift, CMakeLists.txt, composer.json with a writing test script) | changed files+mtimes before vs after two scans; marker file created | = 0; not created | automated VO10 | prior spec |
| QR4 | Maintainability / modifiability | per-language regexes | definition locations outside `LANGUAGES`; entries with differing key sets | = 0; = 0 | review R2 | plan |
| QR5 | Compatibility / interoperability | existing oracle `tests/test_test_scan.py` | changed lines vs base_commit; failing tests | = 0; = 0 | review R3 + Test command | plan D7 |

# Verification Obligations
| id | parent requirement/Case ids | variant and target surface | test layer and selection policy | ISO/IEC/IEEE 29119-4 technique | coverage items | coverage target | observation and expected result | evidence procedure |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| VO1 | FR1, E2 | CLI JSON files[]/language/inventory | integration, tmp dir | equivalence partitioning | each FR1 glob (19) + content-requirement pass/fail for swift, cpp, rust (6) | 100% | included with right language / excluded and in inventory | unittest |
| VO2 | FR2, N1, G2, G3 | tests[].name/line | integration | equivalence partitioning | every start form listed in FR2 per language | 100% | names and lines exact | unittest |
| VO3 | FR3, FR4, B3, B4, G4 | tests[] count, flags attributable to body | integration | boundary value analysis (2-value) | merge (N=1 vs 2 starts on one name), prefix line (directly above vs separated by a code line), brace end (last body line vs first line after closer), clamp (unbalanced → next start), ruby indent end (deeper vs equal indent), empty true/false for brace lang + ruby (def and do) + bodiless `it` | 100% | flag present only when the snippet is within the body | unittest |
| VO4 | FR7, FR8, N2 | tests[].flags | integration | decision table | every trigger snippet and every non-trigger snippet in tables R-PY…R-CPP | 100% | trigger sets flag; non-trigger does not | unittest |
| VO5 | FR6, B1, B2 | tests[].flags | integration | equivalence partitioning | each group trigger in FR6 (inside → flag) + one outside-the-group test per language with group rules | 100% | inside flagged, outside not | unittest |
| VO6 | FR5, G1 | no_assert/mock_only_assert/snapshot_only | integration | decision table | python and javascript: 7 combos {none, A, M, S, A+M, A+S, M+S}; every other language with a mock/snapshot rule: M-only and S-only | 100% | flags per FR5 | unittest |
| VO7 | FR9, B5 | nondeterministic | integration | equivalence partitioning | each language guard snippet (present → suppressed) | 100% | not set with guard; set without | unittest |
| VO8 | FR10, N3 | runner_candidates | integration | equivalence partitioning | 7 runners + rspec 2 evidence variants + phpunit 2 variants + composer without scripts.test + root-only + order | 100% | exact entries and order | unittest |
| VO9 | FR11, FR12 | installed SKILL.md, VERSION, migration output, version pins | integration (installer) | equivalence partitioning | 11 languages and 16 flag names in SKILL.md; `# Flag review` with 16 data rows; install/update migration 0.21.0 announced; manifest version 0.21.0 | 100% | present | unittest |
| VO10 | Errors, E1, QR2, QR3 | CLI exit/stderr, tree snapshot | integration (subprocess) | error guessing | unbalanced brace ×10 brace languages, missing end (ruby), brace in string, glob-but-no-content, write/execute attempt | none — experience-based | exit 0, no traceback, unchanged tree | unittest |
| VO11 | FR11, QR4, QR5 | SKILL.md table, test_scan.py, existing oracle | review | error guessing | R1, R2, R3 checklists | none — experience-based | checks pass | execution ledger |

# Assumptions and Defaults
| id | decision | evidence and uncertainty | brief v1 — approved / vetoed → answer / user answer |
| --- | --- | --- | --- |
| A1 | New languages C#, Ruby, Kotlin, Swift, PHP, C/C++ | same set as `harness/git/warn_new_comments.py` | user answer (plan) |
| A2 | 8 new flags as named in Signatures | user delegated flag choice | plan D2 approved |
| A3 | No `conditional_assert`; no Go subtests; no Kotest/Spock/Elixir/plain C; no RSpec anonymous one-liners | regex cannot see nesting; splitting subtests truncates parents | plan D3–D5 approved; brief v1 — approved |
| A4 | Guard suppresses `nondeterministic` file-wide | guards usually live in setup | plan D6 approved |
| A5 | Body model now ends at the test block's closing brace and includes attribute lines above (FR3) — changes flags for existing languages only where a snippet lay outside the test | improves accuracy; existing oracle must still pass | brief v1 — approved |
| A6 | Assertion precedence snapshot > mock > plain (FR5) | needed so one statement is not counted twice | brief v1 — approved |
| A7 | `trivial_assert` matches only literal true/false forms; `assert 1` is not trivial | existing oracle asserts `assert 1` tests have no flags | brief v1 — approved |
| A8 | `duplicate_name` stays per file name equality (RSpec same title in different `describe` blocks is flagged) | documented in SKILL.md false positives | brief v1 — approved |
| A9 | Hand mutations 8–10, no tool, no fuzzing; all coverage targets 100% for specification-based obligations | prior run precedent, no tools installed | user answer (understanding round) |

# Traceability
| requirement id | Case ids | obligation ids | evidence procedure |
| --- | --- | --- | --- |
| FR1 | E2 | VO1 | unittest |
| FR2 | N1, G2, G3 | VO2 | unittest |
| FR3 | B3, B4, G4 | VO3 | unittest |
| FR4 | — | VO3 | unittest |
| FR5 | G1 | VO6 | unittest |
| FR6 | B1, B2 | VO5 | unittest |
| FR7 | N2 | VO4 | unittest |
| FR8 | N2 | VO4 | unittest |
| FR9 | B5 | VO7 | unittest |
| FR10 | N3 | VO8 | unittest |
| FR11 | — | VO9, VO11 | unittest, R1 |
| FR12 | — | VO9 | unittest |
| QR1 | — | existing VO8 test in tests/test_test_scan.py | unittest |
| QR2, QR3 | E1, E2 | VO10 | unittest |
| QR4, QR5 | — | VO11 | R2, R3 |

# Workflow Control
| item | value |
| --- | --- |
| correction batches used | 2 |
| verifier invocations | 2 |
| open finding ids | none |

Audit state (one entry per obligation; retain prior decisions in the execution ledger):
| obligation id | spec version | evidence references and revision | accepted / open / invalidated / pending | rationale and mutation outcome | dependencies and reopening evidence |
| --- | --- | --- | --- | --- | --- |
| VO1 | 2 | test_scan_rules TestVO1 (corr. 1 rev.) | accepted | verifier #1; M10 killed | reopen if FR1 globs/require tests change |
| VO2 | 2 | TestVO2 | accepted | V6 java capitalized non-generic return type; M7, M8 killed | correction 2 evidence added; C1–C7 killed |
| VO3 | 2 | TestVO3 | accepted | V2 brace depth / JS opener; M1 (incidental kill), M2, M11 killed | correction 2 evidence added; C1–C7 killed |
| VO4 | 2 | TestVO4 | accepted | V5 duplicate_name positive for new languages; M4, M6 killed | correction 2 evidence added; C1–C7 killed |
| VO5 | 2 | TestVO5 | accepted | V2 group depth, V4 method-level @Disabled before later class; M3 killed | correction 2 evidence added; C1–C7 killed |
| VO6 | 2 | TestVO6 | accepted | verifier #1; M4, M6 killed | shared helpers unchanged by correction 2 → remains valid |
| VO7 | 2 | TestVO7 | accepted | V3 guard outside any test body; M5 killed | correction 2 evidence added; C1–C7 killed |
| VO8 | 2 | TestVO8 (corr. 1 rev.) | accepted | verifier #1; M9 killed | — |
| VO9 | 2 | test_installer test_vo9_* | accepted | V1 FR12 step-line content unasserted | correction 2 evidence added; C1–C7 killed |
| VO10 | 2 | TestVO10 | accepted | verifier #1 | — |
| VO11 | 2 | ledger R1–R3 | accepted | verifier #1 (A5: R2 procedure = import LANGUAGES, compare key sets; AST walk for `re.*` calls with constant pattern args) | — |

Execution ledger (append attempts; preserve failed approaches):
| attempt | finding / failure signature | cause hypothesis | changed approach / new evidence | result / disposition |
| --- | --- | --- | --- | --- |
| 1 | C1 implementer: literal FR3(b) lets a one-line test above be absorbed as the next test's prefix | verified: spec wording gap | v2 FR3(b): extension stops at previous test's body | contract-only amendment, implementation already conforms |
| 1 | C2 test-implementer: FR10 dotnet sort order ambiguous; orphaned H-start separated by code line unspecified for java/swift | verified: spec wording gap (dotnet); orphan case outside FR | v2 FR10 clarifies sorted-together; orphan start not required | contract-only |
| 1 | F1 Test command: 10 installer tests fail (EOFError on missing `y` answers for the extra 0.21.0 prompt; c9 expects 9 dry-run confirmations, now 10) | verified: test defect (version bump) | correction batch 1 to test-implementer; 31 input lines widened, c9 count 10; v2 VO3 one-line-above item and VO8 dotnet item added | resolved: Test command 329 OK |
| 2 | R1 SKILL.md Flag review: 16 rows, each with confirm + false-positive cells; Scope names 11 languages and 16 flags | — | review | pass |
| 2 | R2 LANGUAGES: 11 entries, 1 distinct key set (25 keys); no regex literal passed to `re.*` outside the table | — | review | pass |
| 2 | R3 `git diff --stat base -- tests/test_test_scan.py` empty | — | review | pass |
| 2 | Smoke: scanner on this repo → 21 files, 431 tests, valid JSON; new flags only on fixture strings / helper-assert tests (documented false positives) | — | — | pass |
| 3 | Verifier #1 RETRY: V1 (VO9 FR12 step lines), V2 (VO3/VO5 brace depth, JS opener after options object), V3 (VO7 guard outside test bodies), V4 (VO5 method-level @Disabled/[Ignore] followed by later class), V5 (VO4 duplicate_name positive, new languages), V6 (VO2 java `String name()`) | verified: obligation evidence gaps (tests), not spec challenges | correction batch 2 to test-implementer; also advisories A1 (swift non-start `@` prefix separated), A4 (comment-only brace body not empty), A6 (docstring v2) | evidence added (TestBatch2BraceDepthAndGuards, test_vo9_migration_0210_step_lines…); A1 not observable with swift rows → stays advisory |
| 3 | Advisories A2 (Scope paragraph substring check weak), A3 (cross-language rule leak negatives), A5 (R2 procedure) | advisory | A5 recorded in audit state; A2/A3 not required by an obligation | advisory, no change |
| 3 | Hand mutations M1–M11 (block ends at first `}`, prefix ignores contiguity, group range ignores block end, mock before snapshot, guard per body, no_assert ignores M/S, starts not merged, gtest prefix not joined, dotnet evidence last, rust require `#[test]` only, ruby equal indent stays in body) — chosen as the boundary/precedence/scope decisions most likely to regress silently | — | seed.py backup/restore per mutation; `unittest tests.test_test_scan_rules tests.test_test_scan` | 11/11 killed (M1 only incidentally via heavy_mock test → V2); restore ok |
| 4 | Test command after correction 2: 339 OK | — | — | pass |
| 4 | Confirming mutations C1 block ends at first `}` (V2), C2 JS opener = first `{` (V2), C3 java class-skip spans any text (V4), C4 duplicate_name python-only (V5), C5 guard ignored before first test (V3), C6 java capitalized type requires generics (V6), C7 empty 0.21.0 step lines (V1) | each targets one open finding | seed.py backup/restore | 7/7 killed by the intended new tests; restore ok |
| 5 | Verifier #2 PASS: V1–V6 resolved; VO1–VO11 accepted; change-impact for retained entries holds | — | — | complete; advisories A1 (swift separated prefix unobservable), A2, A3 remain non-blocking |

# Version Log
## v1
- Initial draft from the approved plan (vivid-drifting-pike) and understanding round.
## v2
- FR3(b): prefix extension does not cross into the previous test's body (implementer challenge C1). FR10: dotnet evidence sorts `*.sln` and `*.csproj` names together (test-implementer challenge C2). Contract-only clarifications; no brief item changed.
