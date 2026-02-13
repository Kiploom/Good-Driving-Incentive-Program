from __future__ import annotations
import math, json
from typing import Any, Dict, Optional, Callable

from ...models import Sponsor
from ...models import SponsorPointsPolicy

def _get_attr(obj, *candidates):
    for name in candidates:
        if hasattr(obj, name):
            return getattr(obj, name)
    return None

def _load_json_maybe(val) -> Dict[str, Any]:
    if not val:
        return {}
    if isinstance(val, dict):
        return val
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return {}
    return {}

# ---- strategy execution ----

def _apply_strategy(policy: SponsorPointsPolicy, price: float) -> float:
    strategy = (_get_attr(policy, "Strategy", "strategy") or "FLAT_RATE").upper()
    cfg = _load_json_maybe(_get_attr(policy, "ConfigJSON", "config_json", "Config", "Settings"))

    if strategy == "FLAT_RATE":
        # points = price * rate (points per $)
        rate = float(cfg.get("rate", 100))
        return price * rate

    if strategy == "TIERED":
        tiers = cfg.get("tiers", [])
        rate = tiers[-1]["rate"] if tiers else 100
        for t in tiers:
            if t["min"] <= price < t.get("max", float("inf")):
                rate = t["rate"]; break
        return price * rate

    if strategy == "FORMULA":
        expr = cfg.get("expr", "price*100")
        local = {"price": float(price), "sqrt": math.sqrt, "min": min, "max": max}
        try:
            return float(eval(expr, {"__builtins__": {}}, local))
        except Exception:
            return price * 100

    return price * 100

def _round_points(val: float, mode: str | None) -> int:
    mode = (mode or "NEAREST_10").upper()
    if mode == "NEAREST_10": return int(round(val / 10.0)) * 10
    if mode == "NEAREST_25": return int(round(val / 25.0)) * 25
    if mode == "UP_10":      return int(math.ceil(val / 10.0)) * 10
    return int(round(val))

def price_to_points(sponsor_id: str, price_usd: float) -> int:
    """
    Priority:
      1) SponsorPointsPolicy (Strategy/ConfigJSON/Rounding/MinPoints/MaxPoints)
      2) Sponsor.PointToDollarRate (dollars per point) -> points = price / rate
      3) Fallback: 100 pts/$ rounded to NEAREST_10
    """
    # Find a policy row for this sponsor (tolerant to column names)
    # If you have multiple, pick the first active/enabled one (you can extend here)
    policies = SponsorPointsPolicy.query.all()
    pol = next(
        (p for p in policies if str(_get_attr(p, "SponsorID", "sponsor_id")) == str(sponsor_id)),
        None
    )

    if pol:
        pts = _apply_strategy(pol, price_usd)
        min_p = _get_attr(pol, "MinPoints", "min_points")
        max_p = _get_attr(pol, "MaxPoints", "max_points")
        if min_p is not None:
            pts = max(pts, float(min_p))
        if max_p is not None:
            pts = min(pts, float(max_p))
        rounding = _get_attr(pol, "Rounding", "rounding")
        return _round_points(pts, rounding)

    # No policy: fall back to sponsor rate
    s = Sponsor.query.filter_by(SponsorID=sponsor_id).first()
    rate = _get_attr(s, "PointToDollarRate", "point_to_dollar_rate")
    try:
        rate = float(rate)
    except Exception:
        rate = 0.01  # default $0.01 per point

    if rate and rate > 0:
        pts = price_usd / rate
        return _round_points(pts, "NEAREST_10")

    return _round_points(price_usd * 100, "NEAREST_10")


def get_points_converter(sponsor_id: str) -> Callable[[float], int]:
    """
    Create a cached price-to-points converter function for a sponsor.
    This loads the sponsor's points policy once and returns a converter function
    that can be reused for multiple items without additional database queries.
    
    Args:
        sponsor_id: The sponsor ID
        
    Returns:
        A function that takes a price (float) and returns points (int)
    """
    # Find a policy row for this sponsor (tolerant to column names)
    policies = SponsorPointsPolicy.query.all()
    pol = next(
        (p for p in policies if str(_get_attr(p, "SponsorID", "sponsor_id")) == str(sponsor_id)),
        None
    )
    
    if pol:
        min_p = _get_attr(pol, "MinPoints", "min_points")
        max_p = _get_attr(pol, "MaxPoints", "max_points")
        rounding = _get_attr(pol, "Rounding", "rounding")
        
        def convert(price_usd: float) -> int:
            pts = _apply_strategy(pol, price_usd)
            if min_p is not None:
                pts = max(pts, float(min_p))
            if max_p is not None:
                pts = min(pts, float(max_p))
            return _round_points(pts, rounding)
        
        return convert
    
    # No policy: fall back to sponsor rate
    s = Sponsor.query.filter_by(SponsorID=sponsor_id).first()
    rate = _get_attr(s, "PointToDollarRate", "point_to_dollar_rate")
    try:
        rate = float(rate) if rate else 0.01
    except Exception:
        rate = 0.01
    
    def convert(price_usd: float) -> int:
        if rate and rate > 0:
            pts = price_usd / rate
        else:
            pts = price_usd * 100
        return _round_points(pts, "NEAREST_10")
    
    return convert


def convert_prices_batch(items: list[dict], converter_func: Callable[[float], int]) -> None:
    """
    Convert prices to points for all items in a batch.
    Modifies items in-place.
    
    Args:
        items: List of item dictionaries with 'price' key
        converter_func: Function returned by get_points_converter()
    """
    from flask import current_app
    
    converted_count = 0
    missing_price_count = 0
    error_count = 0
    
    for it in items:
        price = it.get("price")
        item_id = it.get("id", "unknown")
        
        if price:
            try:
                price_float = float(price)
                points = converter_func(price_float)
                it["points"] = points
                converted_count += 1
                if converted_count <= 3:  # Log first 3 conversions
                    current_app.logger.debug(f"[POINTS_CONVERSION] Item {item_id}: price=${price_float} -> points={points}")
            except Exception as e:
                it["points"] = None
                error_count += 1
                current_app.logger.warning(f"[POINTS_CONVERSION] Error converting price for item {item_id}: {e}")
        else:
            it["points"] = None
            missing_price_count += 1
            if missing_price_count <= 3:  # Log first 3 missing prices
                current_app.logger.warning(f"[POINTS_CONVERSION] Item {item_id} missing price field. Available keys: {list(it.keys())}")
        
        it.pop("price", None)
        it.pop("currency", None)
    
    # Log summary
    current_app.logger.info(f"[POINTS_CONVERSION] Batch conversion complete: {converted_count} converted, {missing_price_count} missing price, {error_count} errors out of {len(items)} items")
