import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from analytics.pricing import calculate_cost, load_prices


class PricingTests(unittest.TestCase):
    """Contract v3: U4; A2/A6/A11; V5."""

    def setUp(self):
        self.prices = {
            "models": {
                "model-a": {
                    "input": 1.0,
                    "output": 2.0,
                    "cache_read": 0.25,
                    "cache_write_5m": 1.25,
                    "cache_write_1h": 2.25,
                }
            }
        }

    def usage(self, **overrides):
        value = {
            "model": "model-a",
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_5m_tokens": 0,
            "cache_write_1h_tokens": 0,
        }
        value.update(overrides)
        return value

    def test_v5_each_price_category_is_charged_independently(self):
        cases = {
            "input_tokens": Decimal("1.0"),
            "output_tokens": Decimal("2.0"),
            "cache_read_tokens": Decimal("0.25"),
            "cache_write_5m_tokens": Decimal("1.25"),
            "cache_write_1h_tokens": Decimal("2.25"),
        }
        for key, expected in cases.items():
            with self.subTest(category=key):
                actual = calculate_cost(self.usage(**{key: 1_000_000}), self.prices)
                self.assertEqual(Decimal(str(actual)), expected)

    def test_v5_combined_fractional_cost_uses_all_categories(self):
        usage = self.usage(
            input_tokens=500_000,
            output_tokens=250_000,
            cache_read_tokens=2_000_000,
            cache_write_5m_tokens=100_000,
            cache_write_1h_tokens=200_000,
        )
        expected = Decimal("0.5") + Decimal("0.5") + Decimal("0.5") + Decimal("0.125") + Decimal("0.45")
        self.assertEqual(Decimal(str(calculate_cost(usage, self.prices))), expected)

    def test_v5_zero_and_unknown_model_boundaries(self):
        self.assertEqual(calculate_cost(self.usage(), self.prices), 0)
        self.assertIsNone(calculate_cost(self.usage(model="missing"), self.prices))

    def test_v5_yaml_loader_preserves_five_rates(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prices.yaml"
            path.write_text(
                "models:\n"
                "  model-a:\n"
                "    input: 1.0\n"
                "    output: 2.0\n"
                "    cache_read: 0.25\n"
                "    cache_write_5m: 1.25\n"
                "    cache_write_1h: 2.25\n",
                encoding="utf-8",
            )
            self.assertEqual(load_prices(path), self.prices)


if __name__ == "__main__":
    unittest.main()
