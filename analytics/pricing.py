from decimal import Decimal
from pathlib import Path
import yaml


def load_prices(path: Path) -> dict:
    with path.open(encoding="utf-8") as stream:
        prices = yaml.safe_load(stream)
    if not isinstance(prices, dict) or not isinstance(prices.get("models", prices), dict):
        raise ValueError("price YAML must contain a models mapping")
    for model, rates in prices.get("models", prices).items():
        if not isinstance(rates, dict) or not all(any(key in rates for key in names) for names in (("input", "input_tokens"), ("output", "output_tokens"), ("cache_read", "cache_read_tokens"), ("cache_write_5m", "cache_write_5m_tokens"), ("cache_write_1h", "cache_write_1h_tokens"))):
            raise ValueError(f"model {model} is missing token rates")
    return prices


def calculate_cost(usage: dict, prices: dict) -> float | None:
    model = usage.get("model")
    rates = prices.get("models", prices).get(model)
    if not isinstance(rates, dict):
        return None
    aliases = {"input_tokens": ("input", "input_tokens"), "output_tokens": ("output", "output_tokens"), "cache_read_tokens": ("cache_read", "cache_read_tokens"), "cache_write_5m_tokens": ("cache_write_5m", "cache_write_5m_tokens"), "cache_write_1h_tokens": ("cache_write_1h", "cache_write_1h_tokens")}
    try:
        total = sum(Decimal(str(usage.get(field, 0) or 0)) * Decimal(str(rates[next(key for key in keys if key in rates)])) / Decimal(1_000_000) for field, keys in aliases.items())
    except (KeyError, ValueError, ArithmeticError):
        return None
    return float(total)
