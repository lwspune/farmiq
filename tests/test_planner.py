import pandas as pd
import pytest

from farmiq_data.planner import (
    break_even_price,
    harvest_offsets,
    window_prices,
    window_summary,
    years_at_or_above,
)


@pytest.mark.parametrize(
    "first, length, expected",
    [
        # Transplant 15 Jan: harvest 31 Mar - 29 May -> 1 day of Mar (ignored), Apr, May
        (75, 60, [3, 4]),
        # Harvest 16 Mar - 14 Apr: 16 days in Mar and 14 in Apr -> both count (>= 10 days)
        (60, 30, [2, 3]),
        # Long harvest spans three months
        (60, 90, [2, 3, 4, 5]),
    ],
)
def test_harvest_offsets_are_months_after_transplant(first, length, expected):
    assert harvest_offsets(first, length) == expected


def test_harvest_offsets_never_empty():
    # A 10-day window that falls between two mid-month points still yields the nearest month.
    assert harvest_offsets(80, 10) == [3]


def _monthly(rows):
    return pd.DataFrame(rows, columns=["year", "month", "median"])


def test_window_prices_wrap_into_next_year():
    monthly = _monthly([(2020, 1, 10.0), (2020, 2, 20.0), (2021, 1, 30.0), (2021, 2, 40.0)])
    # Transplant in November, harvest 2-3 months later -> January and February of the next year
    out = window_prices(monthly, transplant_month=11, offsets=[2, 3])
    assert out.to_dict("records") == [{"transplant_year": 2019, "price": 15.0, "months": 2},
                                      {"transplant_year": 2020, "price": 35.0, "months": 2}]


def test_window_prices_skip_years_with_missing_months():
    monthly = _monthly([(2020, 4, 10.0), (2020, 5, 12.0), (2021, 4, 8.0)])  # 2021 May missing
    out = window_prices(monthly, transplant_month=1, offsets=[3, 4])
    assert list(out["transplant_year"]) == [2020]
    assert out.iloc[0]["price"] == pytest.approx(11.0)


def test_window_summary_uses_recent_years_and_withholds_small_samples():
    w = pd.DataFrame({"transplant_year": range(2005, 2025), "price": [float(p) for p in range(1, 21)], "months": 2})
    s = window_summary(w, recent_years=10, min_years=5)
    assert s["recent"]["n"] == 10
    assert s["recent"]["first_year"] == 2015
    assert s["recent"]["p50"] == pytest.approx(15.5)
    assert s["all"]["n"] == 20
    small = window_summary(w.tail(3), recent_years=10, min_years=5)
    assert small["recent"] is None and small["all"] is None


def test_recent_window_is_anchored_to_the_market_latest_year_not_the_series():
    # This window's data stops in 2019, but the market reports until 2025:
    # "recent" must mean 2016-2025, so only 2016-2019 qualify (4 years -> withheld).
    w = pd.DataFrame({"transplant_year": range(2005, 2020), "price": 10.0, "months": 2})
    s = window_summary(w, recent_years=10, min_years=5, latest_year=2025)
    assert s["recent"] is None
    assert s["all"]["n"] == 15


def test_break_even_adds_selling_costs_to_growing_cost_per_kg():
    # Rs 1,50,000 per acre, 15,000 kg marketable -> Rs 10/kg, plus Rs 2/kg to get it to market
    assert break_even_price(150_000, 15_000, selling_cost_per_kg=2) == pytest.approx(12.0)


@pytest.mark.parametrize("cost, yield_kg", [(0, 1000), (-5, 1000), (1000, 0), (1000, -1)])
def test_break_even_rejects_non_positive_inputs(cost, yield_kg):
    with pytest.raises(ValueError):
        break_even_price(cost, yield_kg)


def test_break_even_rejects_negative_selling_cost():
    with pytest.raises(ValueError):
        break_even_price(1000, 100, selling_cost_per_kg=-1)


def test_years_at_or_above_counts_including_ties():
    assert years_at_or_above([8.0, 10.0, 12.0, 9.99], 10.0) == (2, 4)
    assert years_at_or_above([], 10.0) == (0, 0)
