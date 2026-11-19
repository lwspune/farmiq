"""Pattern statistics over daily mandi prices.

Every function works per market and commodity and never mixes markets. Each
result carries the number of observations behind it, and statistics are
withheld (NaN / None) when the sample is too small to mean anything.

Input columns expected: date, market, commodity, modal_inr_kg.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

GROUP = ["market", "commodity"]
PCTS = (10, 25, 50, 75, 90)


def monthly_medians(df: pd.DataFrame, min_days_per_month: int = 5) -> pd.DataFrame:
    """Median modal price per market, commodity, year and month, with reporting-day counts."""
    d = df.assign(year=df["date"].dt.year, month=df["date"].dt.month)
    m = (
        d.groupby([*GROUP, "year", "month"])["modal_inr_kg"]
        .agg(monthly_median="median", n_days="count")
        .reset_index()
    )
    return m[m["n_days"] >= min_days_per_month]


def monthly_range(df: pd.DataFrame) -> pd.DataFrame:
    """Per market, commodity and month: median, reporting days, and the P10-P90 range
    of daily modal prices (where most days fell, ignoring one-off extreme days)."""
    d = df.assign(year=df["date"].dt.year, month=df["date"].dt.month)
    g = d.groupby([*GROUP, "year", "month"])["modal_inr_kg"]
    return g.agg(
        monthly_median="median", n_days="count",
        p10=lambda s: s.quantile(0.1), p90=lambda s: s.quantile(0.9),
    ).reset_index()


def seasonal_index(
    df: pd.DataFrame, min_days_per_month: int = 5, min_months_per_year: int = 9
) -> pd.DataFrame:
    """Each month's median price divided by that year's average monthly median.

    Dividing by the year's own level removes inflation and boom/bust years, so
    only the shape within the year is left. 1.0 = an average month that year.
    """
    m = monthly_medians(df, min_days_per_month)
    n_months = m.groupby([*GROUP, "year"])["month"].transform("count")
    m = m[n_months >= min_months_per_year].copy()
    year_mean = m.groupby([*GROUP, "year"])["monthly_median"].transform("mean")
    m["index"] = m["monthly_median"] / year_mean
    return m.reset_index(drop=True)


def percentiles(values, min_n: int = 5) -> dict | None:
    """P10-P90 of `values`, or None when there are fewer than `min_n` values."""
    arr = np.asarray(pd.Series(values).dropna(), dtype=float)
    if len(arr) < min_n:
        return None
    out = {f"p{p}": float(np.percentile(arr, p)) for p in PCTS}
    out["n"] = int(len(arr))
    return out


def month_summary(index_df: pd.DataFrame, min_years: int = 5) -> pd.DataFrame:
    """Per calendar month: how many years, how many above average, and the spread."""
    rows = []
    for (market, commodity, month), g in index_df.groupby([*GROUP, "month"]):
        p = percentiles(g["index"], min_n=min_years)
        rows.append({
            "market": market, "commodity": commodity, "month": month,
            "n_years": int(g["year"].nunique()),
            "years_above_avg": int((g["index"] > 1).sum()),
            "median_index": float(g["index"].median()),
            "p10": p["p10"] if p else np.nan,
            "p90": p["p90"] if p else np.nan,
            "first_year": int(g["year"].min()),
            "last_year": int(g["year"].max()),
        })
    return pd.DataFrame(rows)


def annual_change_autocorrelation(annual: pd.Series, min_pairs: int = 6):
    """Correlation between one year's price change and the next year's.

    Strongly negative = boom tends to be followed by bust (and vice versa).
    Returns (r, n_pairs), or None when there are too few consecutive years.
    """
    s = annual.sort_index().astype(float)
    s = s[s > 0]
    change = np.log(s).diff()
    # Only use changes between consecutive calendar years.
    consecutive = pd.Series(s.index, index=s.index).diff() == 1
    change = change[consecutive]
    pairs = pd.DataFrame({"now": change, "next": change.shift(-1)})
    nxt_consecutive = pd.Series(change.index, index=change.index).diff().shift(-1) == 1
    pairs = pairs[nxt_consecutive].dropna()
    if len(pairs) < min_pairs:
        return None
    r = float(np.corrcoef(pairs["now"], pairs["next"])[0, 1])
    return r, int(len(pairs))


def volatility_by_month(df: pd.DataFrame, min_days_per_month: int = 5) -> pd.DataFrame:
    """How much prices swing within a month: coefficient of variation of daily
    modal prices, per market-year-month, then the median across years."""
    d = df.assign(year=df["date"].dt.year, month=df["date"].dt.month)
    g = d.groupby([*GROUP, "year", "month"])["modal_inr_kg"].agg(["mean", "std", "count"])
    g = g[g["count"] >= min_days_per_month]
    g["cv"] = (g["std"].fillna(0) / g["mean"]).astype(float)
    out = (
        g.reset_index()
        .groupby([*GROUP, "month"])["cv"]
        .agg(median_cv="median", n_years="count")
        .reset_index()
    )
    return out
