from decimal import Decimal
from pathlib import Path
import yaml


def load_prices(path: Path) -> dict:
    with path.open(encoding="utf-8") as stream:
        prices = yaml.safe_load(stream)
    if not isinstance(prices, dict) or not isinstance(prices.get("models", prices), dict):
        raise ValueError("price YAML must contain a models mapping")
    for model, rates in prices.get("models", prices).items():
        if not isinstance(rates, dict) or not all(any(key in rates for key in names) for names in (("input", "input_tokens"), ("output", "output_tokens"), ("cache_read", "cache_read_tokens"), ("cache_write_5m", "cache_write_5m_tokens", "cache_write"), ("cache_write_1h", "cache_write_1h_tokens", "cache_write"))):
            raise ValueError(f"model {model} is missing token rates")
    return prices


def _rates_for(model: str | None, prices: dict) -> dict | None:
    """Longest-prefix match (FR16): a model id like
    claude-haiku-4-5-20251001 uses the claude-haiku-4-5 entry.
    """
    if not model:
        return None
    models = prices.get("models", prices)
    if model in models:
        return models[model]
    best_key = None
    for key in models:
        if model.startswith(key) and (best_key is None or len(key) > len(best_key)):
            best_key = key
    return models.get(best_key) if best_key is not None else None


def calculate_cost(usage: dict, prices: dict) -> float | None:
    rates = _rates_for(usage.get("model"), prices)
    if not isinstance(rates, dict):
        return None
    aliases = {"input_tokens": ("input", "input_tokens"), "output_tokens": ("output", "output_tokens"), "cache_read_tokens": ("cache_read", "cache_read_tokens"), "cache_write_5m_tokens": ("cache_write_5m", "cache_write_5m_tokens", "cache_write"), "cache_write_1h_tokens": ("cache_write_1h", "cache_write_1h_tokens", "cache_write")}
    try:
        total = sum(Decimal(str(usage.get(field, 0) or 0)) * Decimal(str(rates[next(key for key in keys if key in rates)])) / Decimal(1_000_000) for field, keys in aliases.items())
    except (KeyError, ValueError, ArithmeticError, StopIteration):
        return None
    return float(total)


def calculate_codex_cost(model: str | None, requests: list[dict], prices: dict) -> float | None:
    """Codex cost is computed request-by-request (FR15): each request's
    full input token count (cached included) decides whether the base or
    long_context tier rate applies (A3, threshold 272000).
    """
    rates = _rates_for(model, prices)
    if not isinstance(rates, dict):
        return None
    long_context = rates.get("long_context") if isinstance(rates.get("long_context"), dict) else None
    threshold = long_context.get("threshold") if long_context else None
    total = Decimal(0)
    try:
        for request in requests:
            input_tokens = int(request.get("input_tokens", 0) or 0)
            cached_tokens = int(request.get("cached_input_tokens", 0) or 0)
            output_tokens = int(request.get("output_tokens", 0) or 0)
            tier = rates
            if long_context is not None and threshold is not None and input_tokens > threshold:
                tier = long_context
            noncached_input = max(0, input_tokens - cached_tokens)
            total += Decimal(str(noncached_input)) * Decimal(str(tier["input"])) / Decimal(1_000_000)
            total += Decimal(str(cached_tokens)) * Decimal(str(tier["cache_read"])) / Decimal(1_000_000)
            total += Decimal(str(output_tokens)) * Decimal(str(tier["output"])) / Decimal(1_000_000)
    except (KeyError, ValueError, ArithmeticError, TypeError):
        return None
    return float(total)
