"""Supply from other states: when each state sends produce, and whether unusually
big or small arrivals line up with local price surprises.

Arrivals are CEDA (Agmarknet) daily totals per state, or all India. They count
only produce sold through reporting mandis, and the number of reporting mandis
changes over the years, so every measure here is relative to the same year's
average rather than in absolute tonnes.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def parse_state_rows(rows: list[dict], value_field: str, state_id: int) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["date", "state_id", "value"])
    return pd.DataFrame({
        "date": pd.to_datetime(df["date"].astype(str).str[:10]),
        "state_id": state_id,
        "value": pd.to_numeric(df[value_field], errors="coerce"),
    })


def monthly_supply(daily: pd.DataFrame, min_days: int = 20) -> pd.DataFrame:
    """Monthly arrival totals per state; months with too few reporting days dropped."""
    d = daily.dropna(subset=["value"]).assign(year=daily["date"].dt.year, month=daily["date"].dt.month)
    m = d.groupby(["state_id", "year", "month"]).agg(total=("value", "sum"), n_days=("date", "nunique")).reset_index()
    return m[m["n_days"] >= min_days].reset_index(drop=True)


def supply_calendar(monthly: pd.DataFrame, min_months: int = 12) -> pd.DataFrame:
    """Average share of the year's arrivals that each month brings, per state (complete years only)."""
    n = monthly.groupby(["state_id", "year"])["month"].transform("count")
    full = monthly[n >= min_months].copy()
    full["share"] = full["total"] / full.groupby(["state_id", "year"])["total"].transform("sum")
    return (full.groupby(["state_id", "month"])
            .agg(share=("share", "mean"), n_years=("year", "nunique")).reset_index())


def supply_surprise(monthly: pd.DataFrame, min_months: int = 9) -> pd.DataFrame:
    """How much bigger or smaller a month's arrivals were than usual for that month.

    Each month is first compared with its own year's average (removing growth in
    reporting markets), then with the usual level for that calendar month:
    log(index / median index for the month). 0 = a normal month.
    """
    n = monthly.groupby(["state_id", "year"])["month"].transform("count")
    m = monthly[n >= min_months].copy()
    m["index"] = m["total"] / m.groupby(["state_id", "year"])["total"].transform("mean")
    usual = m.groupby(["state_id", "month"])["index"].transform("median")
    m["supply_surprise"] = np.log(m["index"] / usual)
    return m[["state_id", "year", "month", "supply_surprise"]].reset_index(drop=True)


def supply_verdict(corrs: list[dict], threshold: float = 0.3) -> dict:
    """The strongest negative link (more supply -> lower price) across states and lags."""
    valid = [c for c in corrs if c.get("r") is not None]
    if not valid:
        return {"verdict": "insufficient", "state": None, "lag": None, "r": None, "n": 0}
    best = min(valid, key=lambda c: c["r"])
    verdict = "link" if best["r"] <= -threshold else "weak"
    return {"verdict": verdict, "state": best["state"], "lag": best["lag"], "r": best["r"], "n": best["n"]}
