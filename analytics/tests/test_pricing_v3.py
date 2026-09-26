import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from analytics.app import create_app
from analytics.pricing import calculate_cost, load_prices

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_CONFIG_PATH = REPO_ROOT / "analytics" / "config.yaml"


def claude_usage(model, **overrides):
    value = {"model": model, "input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0,
             "cache_write_5m_tokens": 0, "cache_write_1h_tokens": 0}
    value.update(overrides)
    return value


class RealConfigClaudeRatesV3Tests(unittest.TestCase):
    """Independent hand-computed oracle for spec v3 VO10/FR14 (Claude rows):
    load_prices/calculate_cost against the real analytics/config.yaml, whose
    5-category shape matches the pre-existing pricing.py contract. The
    Codex rows use a tiered/long_context shape the spec does not describe at
    the pricing.py surface, so they are exercised end to end via the API in
    RealConfigCodexAndPrefixV3Tests instead of asserted here directly."""

    CLAUDE_RATES_PER_1M = {
        "claude-opus-5-5": (4, 20, 0.2, 5, 8),
        "claude-opus-5": (5, 25, 0.5, 6.25, 10),
        "claude-sonnet-5": (2, 10, 0.2, 2.5, 4),
        "claude-haiku-4-5": (1, 5, 0.1, 1.25, 2),
    }

    def test_fr14_real_config_claude_rows_match_the_spec_table(self):
        prices = load_prices(REAL_CONFIG_PATH)
        for model, (input_rate, output_rate, cache_read, write_5m, write_1h) in self.CLAUDE_RATES_PER_1M.items():
            with self.subTest(model=model):
                self.assertIn(model, prices["models"])
                entry = prices["models"][model]
                self.assertEqual(float(entry["input"]), input_rate)
                self.assertEqual(float(entry["output"]), output_rate)
                self.assertEqual(float(entry["cache_read"]), cache_read)
                self.assertEqual(float(entry["cache_write_5m"]), write_5m)
                self.assertEqual(float(entry["cache_write_1h"]), write_1h)

    def test_fr14_calculate_cost_hand_check_for_claude_sonnet_5(self):
        prices = load_prices(REAL_CONFIG_PATH)
        usage = claude_usage("claude-sonnet-5", input_tokens=1_000_000, output_tokens=1_000_000,
                              cache_read_tokens=1_000_000, cache_write_5m_tokens=1_000_000,
                              cache_write_1h_tokens=1_000_000)
        expected = 2 + 10 + 0.2 + 2.5 + 4
        self.assertAlmostEqual(float(calculate_cost(usage, prices)), expected, places=6)

    def test_fr14_all_claude_models_all_five_categories_are_independently_priced(self):
        """F8/F9 sibling fix: exercise all 4 Claude rows (not just sonnet-5)
        with distinct nonzero per-category token counts, including
        cache_write_5m/1h, so a wrong per-category rate for any Claude model
        or category is independently observable."""
        prices = load_prices(REAL_CONFIG_PATH)
        counts = {"input_tokens": 3_000_000, "output_tokens": 2_000_000, "cache_read_tokens": 5_000_000,
                  "cache_write_5m_tokens": 4_000_000, "cache_write_1h_tokens": 1_000_000}
        for model, (input_rate, output_rate, cache_read, write_5m, write_1h) in self.CLAUDE_RATES_PER_1M.items():
            with self.subTest(model=model):
                usage = claude_usage(model, **counts)
                expected = (counts["input_tokens"] * input_rate + counts["output_tokens"] * output_rate +
                            counts["cache_read_tokens"] * cache_read + counts["cache_write_5m_tokens"] * write_5m +
                            counts["cache_write_1h_tokens"] * write_1h) / 1_000_000
                self.assertAlmostEqual(float(calculate_cost(usage, prices)), expected, places=6)


class RealConfigCodexAndPrefixV3Tests(unittest.TestCase):
    """Independent hand-computed oracle for spec v3 VO10/FR14-FR16, C14-C16 at
    the API surface, using the real analytics/config.yaml as the price
    source (never read as text, only passed as a path)."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.telemetry_dir = self.root / "telemetry"
        self.telemetry_dir.mkdir()
        self.claude_root = self.root / "claude"
        self.codex_root = self.root / "codex"
        self.claude_root.mkdir()
        self.codex_root.mkdir()

    def make_client(self):
        return TestClient(create_app(self.root / "analytics.sqlite3", self.telemetry_dir, REAL_CONFIG_PATH,
                                      {"claude": self.claude_root, "codex": self.codex_root}, frontend_dir=None))

    def link(self, run_id, client, session_id):
        base = {"v": 1, "ts": "2026-09-22T00:00:00+00:00", "client": client, "session_id": session_id,
                "workflow_run_id": run_id, "spec": "analytics", "spec_version": 1}
        return [
            {**base, "event": "workflow_start"},
            {**base, "event": "workflow_phase", "phase": "implement_test"},
            {**base, "event": "workflow_phase", "phase": "verify"},
            {**base, "event": "verifier_result", "round": 1, "result": "pass", "findings": 0,
             "seeds_run": 0, "seeds_detected": 0},
            {**base, "event": "workflow_end", "status": "complete"},
        ]

    def write_telemetry(self, records, filename="repo.jsonl"):
        (self.telemetry_dir / filename).write_text(
            "".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")

    def codex_transcript(self, path, model, requests):
        lines = [json.dumps({"type": "session_meta", "payload": {"id": path.stem, "model": model}})]
        for last, total in requests:
            lines.append(json.dumps({"type": "event_msg", "payload": {"type": "token_count",
                                                                        "info": {"last_token_usage": last,
                                                                                 "total_token_usage": total}}}))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def cost_for(self, client, run_id, session_id):
        detail = client.get(f"/api/runs/{run_id}").json()
        entry = next(e for e in detail["transcript_metadata"] if e["session_id"] == session_id)
        return entry["linked_cost_usd"]

    def test_c14_codex_boundary_272000_uses_base_rate_272001_uses_long_context_rate(self):
        """FR14/FR15, C14: gpt-6-sol base 2/10/.2/2.5 -> long 4/15/.4/5 per 1M tok,
        threshold 272000 inclusive of base."""
        records = self.link("run-base", "codex", "codex-base") + self.link("run-long", "codex", "codex-long")
        self.write_telemetry(records)
        self.codex_transcript(self.codex_root / "codex-base.jsonl", "gpt-6-sol",
                               [({"input_tokens": 272000, "cached_input_tokens": 0, "output_tokens": 0},
                                 {"input_tokens": 272000, "cached_input_tokens": 0, "output_tokens": 0})])
        self.codex_transcript(self.codex_root / "codex-long.jsonl", "gpt-6-sol",
                               [({"input_tokens": 272001, "cached_input_tokens": 0, "output_tokens": 0},
                                 {"input_tokens": 272001, "cached_input_tokens": 0, "output_tokens": 0})])
        client = self.make_client()
        base_cost = self.cost_for(client, "run-base", "codex-base")
        long_cost = self.cost_for(client, "run-long", "codex-long")
        self.assertAlmostEqual(base_cost, 272000 * 2 / 1_000_000, places=6)
        self.assertAlmostEqual(long_cost, 272001 * 4 / 1_000_000, places=6)

    def test_c15_consecutive_duplicate_token_count_is_charged_once(self):
        """FR15, C15: two token_count events with an identical total_token_usage
        represent one request and are charged once; a genuinely new total is
        charged again."""
        records = self.link("run-dup", "codex", "codex-dup") + self.link("run-distinct", "codex", "codex-distinct")
        self.write_telemetry(records)
        same_total = {"input_tokens": 1000, "cached_input_tokens": 0, "output_tokens": 0}
        self.codex_transcript(self.codex_root / "codex-dup.jsonl", "gpt-6-sol",
                               [({"input_tokens": 1000, "cached_input_tokens": 0, "output_tokens": 0}, same_total),
                                ({"input_tokens": 1000, "cached_input_tokens": 0, "output_tokens": 0}, same_total)])
        self.codex_transcript(self.codex_root / "codex-distinct.jsonl", "gpt-6-sol",
                               [({"input_tokens": 1000, "cached_input_tokens": 0, "output_tokens": 0},
                                 {"input_tokens": 1000, "cached_input_tokens": 0, "output_tokens": 0}),
                                ({"input_tokens": 1000, "cached_input_tokens": 0, "output_tokens": 0},
                                 {"input_tokens": 2000, "cached_input_tokens": 0, "output_tokens": 0})])
        client = self.make_client()
        dup_cost = self.cost_for(client, "run-dup", "codex-dup")
        distinct_cost = self.cost_for(client, "run-distinct", "codex-distinct")
        self.assertAlmostEqual(dup_cost, 1000 * 2 / 1_000_000, places=6)
        self.assertAlmostEqual(distinct_cost, 2000 * 2 / 1_000_000, places=6)

    # FR14 Codex rows: (input, output, cache_read, cache_write) USD per 1M tok,
    # base tier then long_context tier (threshold 272000), transcribed by hand
    # from the spec table (never read from config.yaml).
    CODEX_BASE_RATES = {
        "gpt-6-astra": (10, 50, 1, 12.5),
        "gpt-6-sol": (2, 10, 0.2, 2.5),
        "gpt-6-luna": (0.1, 0.5, 0.01, 0.125),
        "gpt-5.6-sol": (4, 20, 0.4, 5),
        "gpt-5.6-terra": (2, 12, 0.2, 2.5),
        "gpt-5.6-luna": (0.2, 1.2, 0.02, 0.25),
    }
    CODEX_LONG_RATES = {
        "gpt-6-astra": (20, 75, 2, 25),
        "gpt-6-sol": (4, 15, 0.4, 5),
        "gpt-6-luna": (0.2, 0.75, 0.02, 0.25),
        "gpt-5.6-sol": (8, 30, 0.8, 10),
        "gpt-5.6-terra": (4, 18, 0.4, 5),
        "gpt-5.6-luna": (0.4, 1.8, 0.04, 0.5),
    }

    def expected_codex_cost(self, rates, noncached_input, cached_input, output):
        input_rate, output_rate, cache_read_rate, _cache_write_rate = rates
        return (noncached_input * input_rate + cached_input * cache_read_rate +
                output * output_rate) / 1_000_000

    def test_fr14_f8_f9_all_six_codex_models_both_tiers_with_distinct_nonzero_categories(self):
        """F8/F9: every FR14 Codex model, in both the base (<=272000) and
        long_context (>272000) tiers, with distinct nonzero noncached input,
        cached input, and output token counts so a wrong rate on any single
        category (including a changed long-context output rate) is
        independently observable. input_tokens includes cached_input_tokens
        per FR15, so the request's total input is noncached + cached."""
        noncached_input, cached_input, output = 150_000, 50_000, 30_000  # base tier: total input 200,000
        long_noncached_input, long_cached_input, long_output = 220_000, 80_000, 40_000  # long tier: total input 300,000
        self.assertLessEqual(noncached_input + cached_input, 272_000)
        self.assertGreater(long_noncached_input + long_cached_input, 272_000)

        run_ids = []
        for model in self.CODEX_BASE_RATES:
            base_run, long_run = f"run-{model}-base", f"run-{model}-long"
            run_ids += [base_run, long_run]
            self.write_telemetry(self.link(base_run, "codex", f"{model}-base") +
                                  self.link(long_run, "codex", f"{model}-long"), filename=f"{model}.jsonl")
            total_base = {"input_tokens": noncached_input + cached_input, "cached_input_tokens": cached_input,
                           "output_tokens": output}
            self.codex_transcript(self.codex_root / f"{model}-base.jsonl", model,
                                   [({"input_tokens": noncached_input + cached_input,
                                      "cached_input_tokens": cached_input, "output_tokens": output}, total_base)])
            total_long = {"input_tokens": long_noncached_input + long_cached_input,
                           "cached_input_tokens": long_cached_input, "output_tokens": long_output}
            self.codex_transcript(self.codex_root / f"{model}-long.jsonl", model,
                                   [({"input_tokens": long_noncached_input + long_cached_input,
                                      "cached_input_tokens": long_cached_input, "output_tokens": long_output}, total_long)])

        client = self.make_client()
        for model in self.CODEX_BASE_RATES:
            with self.subTest(model=model, tier="base"):
                expected = self.expected_codex_cost(self.CODEX_BASE_RATES[model], noncached_input, cached_input, output)
                actual = self.cost_for(client, f"run-{model}-base", f"{model}-base")
                self.assertAlmostEqual(actual, expected, places=6)
            with self.subTest(model=model, tier="long"):
                expected = self.expected_codex_cost(self.CODEX_LONG_RATES[model], long_noncached_input,
                                                     long_cached_input, long_output)
                actual = self.cost_for(client, f"run-{model}-long", f"{model}-long")
                self.assertAlmostEqual(actual, expected, places=6)

    def test_fr15_multi_request_session_sums_per_request_short_and_long_costs(self):
        """FR15: 'session token sum is per-request'. A single Codex session
        with one base-tier request and one long_context-tier request must
        cost the sum of each request's own-rate cost, not a single blended
        rate applied to the session total."""
        model = "gpt-6-sol"
        short_noncached, short_cached, short_output = 100_000, 20_000, 5_000  # total input 120,000 (base)
        long_noncached, long_cached, long_output = 200_000, 80_000, 10_000  # total input 280,000 (long)
        self.write_telemetry(self.link("run-multi", "codex", "codex-multi"))
        self.codex_transcript(
            self.codex_root / "codex-multi.jsonl", model,
            [({"input_tokens": short_noncached + short_cached, "cached_input_tokens": short_cached,
               "output_tokens": short_output},
              {"input_tokens": short_noncached + short_cached, "cached_input_tokens": short_cached,
               "output_tokens": short_output}),
             ({"input_tokens": long_noncached + long_cached, "cached_input_tokens": long_cached,
               "output_tokens": long_output},
              {"input_tokens": short_noncached + short_cached + long_noncached + long_cached,
               "cached_input_tokens": short_cached + long_cached,
               "output_tokens": short_output + long_output})])
        client = self.make_client()
        actual = self.cost_for(client, "run-multi", "codex-multi")
        expected = (self.expected_codex_cost(self.CODEX_BASE_RATES[model], short_noncached, short_cached, short_output) +
                    self.expected_codex_cost(self.CODEX_LONG_RATES[model], long_noncached, long_cached, long_output))
        self.assertAlmostEqual(actual, expected, places=6)

    def test_c16_claude_model_id_suffix_uses_the_longest_matching_price_prefix(self):
        """FR16, C16: claude-haiku-4-5-20251001 must price as claude-haiku-4-5,
        and claude-opus-5-5-<date> must price as claude-opus-5-5 (not the
        shorter claude-opus-5 prefix that is also a valid match)."""
        records = (self.link("run-haiku", "claude", "claude-haiku-suffixed") +
                   self.link("run-opus55", "claude", "claude-opus55-suffixed"))
        self.write_telemetry(records)
        (self.claude_root / "claude-haiku-suffixed.jsonl").write_text(
            json.dumps({"type": "assistant", "sessionId": "claude-haiku-suffixed",
                        "message": {"model": "claude-haiku-4-5-20251001",
                                    "usage": {"input_tokens": 1_000_000, "output_tokens": 0}}}) + "\n",
            encoding="utf-8")
        (self.claude_root / "claude-opus55-suffixed.jsonl").write_text(
            json.dumps({"type": "assistant", "sessionId": "claude-opus55-suffixed",
                        "message": {"model": "claude-opus-5-5-20260101",
                                    "usage": {"input_tokens": 1_000_000, "output_tokens": 0}}}) + "\n",
            encoding="utf-8")
        client = self.make_client()
        haiku_cost = self.cost_for(client, "run-haiku", "claude-haiku-suffixed")
        opus55_cost = self.cost_for(client, "run-opus55", "claude-opus55-suffixed")
        self.assertAlmostEqual(haiku_cost, 1.0, places=6)
        self.assertAlmostEqual(opus55_cost, 4.0, places=6)


if __name__ == "__main__":
    unittest.main()
