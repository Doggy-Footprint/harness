import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from analytics.pricing import calculate_cost, load_prices


class PricingTests(unittest.TestCase):
    """Independent Decimal arithmetic oracle for spec v1 V4/Q1."""

    def setUp(self):
        self.prices = {"models": {"model-a": {
            "input": 1.0, "output": 2.0, "cache_read": 0.25,
            "cache_write_5m": 1.25, "cache_write_1h": 2.25,
        }}}

    def usage(self, **overrides):
        value = {"model": "model-a", "input_tokens": 0, "output_tokens": 0,
                 "cache_read_tokens": 0, "cache_write_5m_tokens": 0,
                 "cache_write_1h_tokens": 0}
        value.update(overrides)
        return value

    def test_v4_each_price_category_is_charged_independently(self):
        rates = {"input_tokens": "1", "output_tokens": "2", "cache_read_tokens": ".25",
                 "cache_write_5m_tokens": "1.25", "cache_write_1h_tokens": "2.25"}
        for key, expected in rates.items():
            with self.subTest(category=key):
                actual = calculate_cost(self.usage(**{key: 1_000_000}), self.prices)
                self.assertEqual(Decimal(str(actual)), Decimal(expected))

    def test_v4_combined_and_zero_cost_use_exact_fixture_arithmetic(self):
        usage = self.usage(input_tokens=500_000, output_tokens=250_000, cache_read_tokens=2_000_000,
                           cache_write_5m_tokens=100_000, cache_write_1h_tokens=200_000)
        self.assertEqual(Decimal(str(calculate_cost(usage, self.prices))), Decimal("2.075"))
        self.assertEqual(calculate_cost(self.usage(), self.prices), 0)

    def test_v4_unknown_model_is_unpriced_not_zero(self):
        self.assertIsNone(calculate_cost(self.usage(model="unknown"), self.prices))

    def test_v4_yaml_loader_keeps_all_five_rates(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prices.yaml"
            path.write_text("models:\n  model-a:\n    input: 1.0\n    output: 2.0\n    cache_read: 0.25\n    cache_write_5m: 1.25\n    cache_write_1h: 2.25\n", encoding="utf-8")
            self.assertEqual(load_prices(path), self.prices)


if __name__ == "__main__":
    unittest.main()
