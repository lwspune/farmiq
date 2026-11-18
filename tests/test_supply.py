import math

import pandas as pd
import pytest

from farmiq_data.supply import (
    monthly_supply,
    parse_state_rows,
    supply_calendar,
    supply_surprise,
    supply_verdict,
)


def _daily(state, years, per_month, days=25):
    rows = []
    for y in years:
        for m, qty in per_month.items():
            for d in range(1, days + 1):
                rows.append({"date": pd.Timestamp(y, m, d), "state_id": state, "qty": qty})
    return pd.DataFrame(rows)


def test_parse_state_rows():
    rows = [{"date": "2024-07-01T00:00:00.000Z", "commodity_id": 78, "census_state_id": 29, "quantity": 204}]
    df = parse_state_rows(rows, "quantity", state_id=29)
    assert list(df.columns) == ["date", "state_id", "value"]
    assert df.iloc[0]["date"] == pd.Timestamp("2024-07-01") and df.iloc[0]["value"] == 204


def test_parse_state_rows_all_india_has_no_state_field():
    rows = [{"date": "2024-07-01T00:00:00.000Z", "commodity_id": 78, "quantity": 9000}]
    df = parse_state_rows(rows, "quantity", state_id=0)
    assert df.iloc[0]["state_id"] == 0


def test_monthly_supply_drops_months_with_few_reporting_days():
    d = _daily(29, [2020], {1: 10.0, 2: 10.0}, days=25)
    d = d[~((d.date.dt.month == 2) & (d.date.dt.day > 5))]  # February: only 5 days
    m = monthly_supply(d.rename(columns={"qty": "value"}), min_days=20)
    assert list(m["month"]) == [1]
    assert m.iloc[0]["total"] == pytest.approx(250.0)


def test_supply_calendar_gives_each_months_share_of_the_year():
    per_month = {m: (10.0 if m in (1, 2, 3) else 0.001) for m in range(1, 13)}
    d = _daily(29, [2019, 2020, 2021], per_month).rename(columns={"qty": "value"})
    cal = supply_calendar(monthly_supply(d)).set_index("month")
    assert cal.loc[1, "share"] == pytest.approx(1 / 3, rel=1e-3)
    assert cal.loc[7, "share"] == pytest.approx(0, abs=1e-3)
    assert cal.loc[1, "n_years"] == 3


def test_supply_surprise_flags_an_unusually_big_month():
    base = {m: 10.0 for m in range(1, 13)}
    normal = _daily(29, [2018, 2019, 2020], base)
    big = _daily(29, [2021], {**base, 7: 20.0})
    m = monthly_supply(pd.concat([normal, big]).rename(columns={"qty": "value"}))
    s = supply_surprise(m).set_index(["year", "month"])
    assert s.loc[(2021, 7), "supply_surprise"] > 0.5
    assert s.loc[(2019, 7), "supply_surprise"] == pytest.approx(0, abs=1e-9)
    assert s.loc[(2021, 1), "supply_surprise"] < 0  # same total year-average rises, other months look smaller


def test_supply_verdict_picks_the_strongest_negative_link():
    corrs = [{"state": "Karnataka", "lag": 0, "r": -0.12, "n": 150},
             {"state": "All India", "lag": 0, "r": -0.41, "n": 200},
             {"state": "Gujarat", "lag": 1, "r": 0.35, "n": 140}]
    v = supply_verdict(corrs)
    assert v["verdict"] == "link" and v["state"] == "All India" and v["r"] == -0.41


def test_supply_verdict_weak_and_insufficient():
    assert supply_verdict([{"state": "Karnataka", "lag": 0, "r": -0.1, "n": 150}])["verdict"] == "weak"
    assert supply_verdict([])["verdict"] == "insufficient"
    assert not math.isnan(0.0)
