import math

import numpy as np
import pandas as pd
import pytest

from farmiq_data.patterns import (
    annual_change_autocorrelation,
    month_summary,
    percentiles,
    seasonal_index,
    volatility_by_month,
)

# A known seasonal shape: July is the peak, February the trough.
FACTORS = {1: 1.0, 2: 0.6, 3: 0.7, 4: 0.8, 5: 0.9, 6: 1.2, 7: 1.8, 8: 1.5, 9: 1.1, 10: 1.0, 11: 0.8, 12: 0.6}


def _daily(years, base_by_year, days_per_month=10, market="Pune", factors=FACTORS):
    rows = []
    for y in years:
        for m, f in factors.items():
            for d in range(1, days_per_month + 1):
                rows.append(
                    {"date": pd.Timestamp(y, m, d), "market": market, "commodity": "Tomato",
                     "modal_inr_kg": base_by_year[y] * f}
                )
    return pd.DataFrame(rows)


def test_seasonal_index_removes_the_yearly_level():
    years = range(2015, 2021)
    # Each year has a very different price level (boom/bust, inflation); the shape is identical.
    base = {y: 10 * (1 + i) for i, y in enumerate(years)}
    idx = seasonal_index(_daily(years, base))
    mean_factor = np.mean(list(FACTORS.values()))
    july = idx[idx["month"] == 7]
    assert len(july) == 6
    assert july["index"].to_numpy() == pytest.approx(FACTORS[7] / mean_factor)


def test_months_with_too_few_reporting_days_are_excluded():
    df = _daily([2020], {2020: 10}, days_per_month=3)
    idx = seasonal_index(df, min_days_per_month=5, min_months_per_year=1)
    assert idx.empty


def test_years_with_too_few_valid_months_are_excluded():
    df = _daily([2020], {2020: 10}, factors={1: 1.0, 2: 1.0, 3: 1.0})
    idx = seasonal_index(df, min_months_per_year=9)
    assert idx.empty


def test_month_summary_counts_years_above_average():
    years = range(2015, 2021)
    idx = seasonal_index(_daily(years, {y: 10 for y in years}))
    summary = month_summary(idx, min_years=5).set_index("month")
    assert summary.loc[7, "n_years"] == 6
    assert summary.loc[7, "years_above_avg"] == 6
    assert summary.loc[2, "years_above_avg"] == 0
    assert summary.loc[7, "p10"] == pytest.approx(summary.loc[7, "median_index"])


def test_month_summary_withholds_percentiles_when_too_few_years():
    years = range(2018, 2021)  # 3 years only
    idx = seasonal_index(_daily(years, {y: 10 for y in years}))
    summary = month_summary(idx, min_years=5).set_index("month")
    assert summary.loc[7, "n_years"] == 3
    assert pd.isna(summary.loc[7, "p10"]) and pd.isna(summary.loc[7, "p90"])


def test_percentiles_refuse_small_samples():
    assert percentiles([1, 2, 3], min_n=5) is None
    p = percentiles(list(range(1, 102)), min_n=5)
    assert p["p50"] == pytest.approx(51)
    assert p["n"] == 101


def test_alternating_boom_bust_gives_negative_autocorrelation():
    annual = pd.Series([10, 20, 10, 20, 10, 20, 10, 20, 10], index=range(2010, 2019))
    r, n_pairs = annual_change_autocorrelation(annual, min_pairs=6)
    assert r == pytest.approx(-1.0)
    assert n_pairs == 7


def test_autocorrelation_refuses_short_series():
    annual = pd.Series([10, 20, 10, 20], index=range(2010, 2014))
    assert annual_change_autocorrelation(annual, min_pairs=6) is None


def test_volatility_is_zero_for_flat_prices_and_positive_for_swings():
    flat = _daily([2020], {2020: 10}, factors={1: 1.0})
    swing = flat.copy()
    swing.loc[swing.index % 2 == 0, "modal_inr_kg"] = 20
    swing["market"] = "Nashik"
    vol = volatility_by_month(pd.concat([flat, swing])).set_index(["market", "month"])
    assert vol.loc[("Pune", 1), "median_cv"] == pytest.approx(0.0)
    assert vol.loc[("Nashik", 1), "median_cv"] > 0.2
    assert not math.isnan(vol.loc[("Nashik", 1), "median_cv"])
