import math

import numpy as np
import pandas as pd
import pytest

from farmiq_data.weather import (
    lagged_correlation,
    monthly_weather,
    parse_open_meteo,
    price_surprise,
    weather_anomalies,
)


def test_parse_open_meteo_daily_payload():
    payload = {"daily": {"time": ["2003-01-01", "2003-01-02"], "precipitation_sum": [0.0, 4.5],
                         "temperature_2m_max": [25.0, None]}}
    df = parse_open_meteo(payload)
    assert list(df["date"]) == [pd.Timestamp("2003-01-01"), pd.Timestamp("2003-01-02")]
    assert list(df["rain_mm"]) == [0.0, 4.5]
    assert df["tmax_c"].isna().tolist() == [False, True]


def test_monthly_weather_sums_rain_averages_heat_and_drops_partial_months():
    days = pd.date_range("2020-01-01", "2020-02-10")
    df = pd.DataFrame({"date": days, "rain_mm": 1.0, "tmax_c": 30.0})
    m = monthly_weather(df, min_days=25)
    assert list(zip(m["year"], m["month"], strict=True)) == [(2020, 1)]  # Feb has only 10 days
    assert m.iloc[0]["rain_mm"] == pytest.approx(31.0)
    assert m.iloc[0]["tmax_c"] == pytest.approx(30.0)


def test_weather_anomalies_are_relative_to_the_same_calendar_month():
    m = pd.DataFrame({"year": [2020, 2021, 2020, 2021], "month": [1, 1, 7, 7],
                      "rain_mm": [10.0, 30.0, 200.0, 400.0], "tmax_c": [28.0, 30.0, 30.0, 30.0]})
    a = weather_anomalies(m).set_index(["year", "month"])
    assert a.loc[(2020, 1), "rain_anom"] == pytest.approx(-10.0)
    assert a.loc[(2021, 7), "rain_anom"] == pytest.approx(100.0)
    assert a.loc[(2021, 1), "tmax_anom"] == pytest.approx(1.0)


def test_price_surprise_compares_with_the_usual_level_for_that_month():
    idx = pd.DataFrame({"year": [2020, 2021, 2020, 2021], "month": [7, 7, 1, 1], "index": [2.0, 1.0, 0.5, 0.5]})
    s = price_surprise(idx).set_index(["year", "month"])
    assert s.loc[(2020, 7), "surprise"] == pytest.approx(math.log(2.0 / 1.5))
    assert s.loc[(2021, 7), "surprise"] == pytest.approx(math.log(1.0 / 1.5))
    assert s.loc[(2020, 1), "surprise"] == pytest.approx(0.0)


def _series(values, start=2010):
    rows = []
    for i, v in enumerate(values):
        y, m = divmod(i, 12)
        rows.append({"year": start + y, "month": m + 1, "v": v})
    return pd.DataFrame(rows)


def test_lagged_correlation_finds_weather_that_leads_prices():
    rng = np.random.default_rng(1)
    w = rng.normal(size=120)
    weather = _series(w).rename(columns={"v": "rain_anom"})
    # Price surprise follows last month's rain anomaly exactly.
    surprise = _series(np.r_[0.0, w[:-1]]).rename(columns={"v": "surprise"})
    r1, n1 = lagged_correlation(surprise, weather, "rain_anom", lag_months=1, min_n=60)
    assert r1 == pytest.approx(1.0)
    assert n1 == 119
    r0, _ = lagged_correlation(surprise, weather, "rain_anom", lag_months=0, min_n=60)
    assert abs(r0) < 0.3


def test_season_rain_pct_compares_each_year_with_the_base_average():
    from farmiq_data.weather import season_rain_pct
    m = pd.DataFrame({"year": [2020, 2020, 2021, 2021, 2022, 2022], "month": [7, 8, 7, 8, 7, 8],
                      "rain_mm": [100.0, 100.0, 300.0, 300.0, 100.0, 50.0], "tmax_c": 30.0})
    pct = season_rain_pct(m, months=(7, 8), base_years=(2020, 2021))
    assert pct[2020] == pytest.approx(50.0)   # 200 vs base average 400
    assert pct[2021] == pytest.approx(150.0)
    assert pct[2022] == pytest.approx(37.5)   # outside the base years, still compared with it


def test_season_rain_pct_skips_years_missing_a_season_month():
    from farmiq_data.weather import season_rain_pct
    m = pd.DataFrame({"year": [2020, 2020, 2021], "month": [7, 8, 7], "rain_mm": 100.0, "tmax_c": 30.0})
    pct = season_rain_pct(m, months=(7, 8), base_years=(2020, 2021))
    assert 2021 not in pct.index


def test_relative_to_neighbours_removes_the_trend():
    from farmiq_data.weather import relative_to_neighbours
    s = pd.Series([10.0, 11.0, 12.0, 30.0, 14.0, 15.0, 16.0], index=range(2010, 2017))
    rel = relative_to_neighbours(s, window=5)
    assert rel[2013] > 2.0           # a spike stands out
    assert rel[2011] == pytest.approx(1.0, abs=0.1)


def test_after_dry_years_summarises_the_next_season():
    from farmiq_data.weather import after_dry_years
    rain = pd.Series({2010: 70.0, 2011: 100.0, 2012: 60.0, 2013: 110.0, 2014: 95.0})
    nxt = pd.Series({2010: 1.5, 2011: 1.0, 2012: 2.0, 2013: 0.9, 2014: 1.1})
    out = after_dry_years(rain, nxt, threshold=85)
    assert out["dry_years"] == [[2010, 70.0, 1.5], [2012, 60.0, 2.0]]
    assert out["median_after_dry"] == pytest.approx(1.75)
    assert out["median_after_normal"] == pytest.approx(1.0)
    assert out["n_dry"] == 2 and out["n_normal"] == 3
    assert out["dry_higher"] == 2


def test_lagged_correlation_refuses_short_series():
    weather = _series(range(20)).rename(columns={"v": "rain_anom"})
    surprise = _series(range(20)).rename(columns={"v": "surprise"})
    assert lagged_correlation(surprise, weather, "rain_anom", lag_months=0, min_n=60) is None
