"""Turn pattern statistics into plain verdicts, and cross-check sources.

Verdict rules are explicit and deliberately conservative: a pattern is only
called "clear" when it held in most years across a long enough history.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd


def market_key(name: str) -> str:
    """Normalise a market name so CEDA ('Pune') and Agmarknet ('APMC Pune ') match."""
    key = re.sub(r"\s+", " ", str(name).strip().lower())
    return re.sub(r"^apmc\s+", "", key)


def seasonality_verdict(summary: pd.DataFrame, min_years: int = 8, threshold: float = 0.75) -> dict:
    """`summary`: one row per month with n_years and years_above_avg.

    A month is reliably high if it was above that year's average in at least
    `threshold` of years, reliably low if above average in at most 1 - threshold.
    """
    s = summary[summary["n_years"] > 0]
    n_years = int(s["n_years"].max()) if len(s) else 0
    if n_years < min_years:
        return {"verdict": "insufficient", "n_years": n_years, "high_months": [], "low_months": []}
    usable = s[s["n_years"] >= min_years]
    share = usable["years_above_avg"] / usable["n_years"]
    high = sorted(int(m) for m in usable.loc[share >= threshold, "month"])
    low = sorted(int(m) for m in usable.loc[share <= 1 - threshold, "month"])
    verdict = "clear" if high and low else "weak"
    return {"verdict": verdict, "n_years": n_years, "high_months": high, "low_months": low}


def boom_bust_verdict(result, threshold: float = 0.3) -> dict:
    """`result`: (r, n_pairs) from annual_change_autocorrelation, or None."""
    if result is None:
        return {"verdict": "insufficient", "r": None, "n_pairs": 0}
    r, n = result
    if r <= -threshold:
        verdict = "boom_bust"
    elif r >= threshold:
        verdict = "momentum"
    else:
        verdict = "none"
    return {"verdict": verdict, "r": round(float(r), 3), "n_pairs": int(n)}


def _year_relative_log(df: pd.DataFrame, col: str) -> pd.Series:
    keys = ["market", "commodity", "year"]
    v = df[col].astype(float)
    return np.log(v / df.groupby(keys)[col].transform("mean"))


def arrivals_price_correlation(monthly_prices: pd.DataFrame, monthly_arrivals: pd.DataFrame, min_n: int = 24):
    """Correlation between a month's arrivals and its price, each relative to its
    own year's average (so long-run trends and inflation don't drive the result).

    Returns (r, n_months) or None when there are fewer than `min_n` matched months.
    """
    keys = ["market", "commodity", "year", "month"]
    p = monthly_prices[monthly_prices["monthly_median"] > 0].copy()
    a = monthly_arrivals[monthly_arrivals["arrivals"] > 0].copy()
    p["lp"] = _year_relative_log(p, "monthly_median")
    a["la"] = _year_relative_log(a, "arrivals")
    m = p[keys + ["lp"]].merge(a[keys + ["la"]], on=keys).dropna()
    if len(m) < min_n or m["lp"].std() == 0 or m["la"].std() == 0:
        return None
    return float(np.corrcoef(m["la"], m["lp"])[0, 1]), int(len(m))


def compare_sources(a: pd.DataFrame, b: pd.DataFrame, tolerance_inr_quintal: float = 1.0) -> dict:
    """Match two sources on market name + commodity + date and compare modal prices."""
    def prep(df):
        return df.assign(key=df["market"].map(market_key))[["key", "commodity", "date", "modal_inr_quintal"]]

    m = prep(a).merge(prep(b), on=["key", "commodity", "date"], suffixes=("_a", "_b"))
    if m.empty:
        return {"n_matched": 0, "share_equal": None, "median_abs_diff_inr_quintal": None}
    diff = (m["modal_inr_quintal_a"] - m["modal_inr_quintal_b"]).abs()
    return {
        "n_matched": int(len(m)),
        "share_equal": float((diff <= tolerance_inr_quintal).mean()),
        "median_abs_diff_inr_quintal": float(diff.median()),
    }
