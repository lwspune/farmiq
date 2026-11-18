"""Planting-window planner: what did mandi prices do in the harvest months that
follow a given transplant month, and how often were they above break-even?

Crop timing is an editable assumption (days from transplant to first harvest,
and how long harvesting lasts), never a fact about a particular farm.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

MIN_DAYS_IN_MONTH = 10
_REF_YEAR = 2001  # any non-leap year; only month offsets are used


def harvest_offsets(first_harvest_days: int, harvest_days: int, transplant_month: int = 1) -> list[int]:
    """Months after transplanting (0 = transplant month) that the harvest falls in.

    Transplanting is assumed mid-month. A month counts when at least 10 harvest
    days fall in it; if none qualifies, the month with the most harvest days.
    """
    start = date(_REF_YEAR, transplant_month, 15) + timedelta(days=first_harvest_days)
    days: dict[int, int] = {}
    for i in range(harvest_days):
        d = start + timedelta(days=i)
        k = (d.year - _REF_YEAR) * 12 + d.month - transplant_month
        days[k] = days.get(k, 0) + 1
    chosen = sorted(k for k, n in days.items() if n >= MIN_DAYS_IN_MONTH)
    return chosen or [max(days, key=days.get)]


def window_prices(monthly: pd.DataFrame, transplant_month: int, offsets: list[int]) -> pd.DataFrame:
    """Average monthly median price over the harvest window, per transplant year.

    `monthly`: one market's [year, month, median]. Years where any harvest month
    has no price are skipped rather than estimated.
    """
    lookup = {(int(y), int(m)): float(v) for y, m, v in monthly[["year", "month", "median"]].itertuples(index=False)}
    if not lookup:
        return pd.DataFrame(columns=["transplant_year", "price", "months"])
    years = [y for y, _ in lookup]
    rows = []
    for ty in range(min(years) - 1, max(years) + 1):
        vals = []
        for k in offsets:
            idx = ty * 12 + (transplant_month - 1) + k
            v = lookup.get((idx // 12, idx % 12 + 1))
            if v is None:
                break
            vals.append(v)
        if len(vals) == len(offsets):
            rows.append({"transplant_year": ty, "price": float(np.mean(vals)), "months": len(vals)})
    return pd.DataFrame(rows, columns=["transplant_year", "price", "months"])


def _summ(prices: pd.Series, years: pd.Series, min_years: int) -> dict | None:
    if len(prices) < min_years:
        return None
    return {
        "p10": float(np.percentile(prices, 10)),
        "p50": float(np.percentile(prices, 50)),
        "p90": float(np.percentile(prices, 90)),
        "n": int(len(prices)),
        "first_year": int(years.min()),
        "last_year": int(years.max()),
    }


def window_summary(
    windows: pd.DataFrame, recent_years: int = 10, min_years: int = 5, latest_year: int | None = None
) -> dict:
    """Low (P10) / typical (P50) / high (P90) harvest-window price, for the most
    recent `recent_years` transplant years and for all years. Prices are nominal,
    so the recent window is the fair comparison with today's costs.

    `latest_year` anchors "recent" to the market's latest data, so a window whose
    months stopped being reported years ago is not passed off as recent.
    """
    if windows.empty:
        return {"recent": None, "all": None}
    latest = latest_year if latest_year is not None else int(windows["transplant_year"].max())
    recent = windows[windows["transplant_year"] > latest - recent_years]
    return {
        "recent": _summ(recent["price"], recent["transplant_year"], min_years),
        "all": _summ(windows["price"], windows["transplant_year"], min_years),
    }


def break_even_price(cost_per_acre: float, yield_kg_per_acre: float, selling_cost_per_kg: float = 0.0) -> float:
    """Mandi price (Rs/kg) needed to cover growing costs plus the cost of selling."""
    if cost_per_acre <= 0 or yield_kg_per_acre <= 0:
        raise ValueError("cost per acre and yield per acre must both be positive")
    if selling_cost_per_kg < 0:
        raise ValueError("selling cost per kg cannot be negative")
    return cost_per_acre / yield_kg_per_acre + selling_cost_per_kg


def years_at_or_above(prices, threshold: float) -> tuple[int, int]:
    arr = list(prices)
    return sum(1 for p in arr if p >= threshold), len(arr)
