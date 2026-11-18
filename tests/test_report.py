import numpy as np
import pandas as pd
import pytest

from farmiq_data.report import (
    arrivals_price_correlation,
    boom_bust_verdict,
    compare_sources,
    market_key,
    seasonality_verdict,
)


@pytest.mark.parametrize(
    "raw, key",
    [("APMC Pune ", "pune"), ("Pune", "pune"), ("Junnar(Narayangaon)", "junnar(narayangaon)"),
     # Renamed or differently spelled markets map to one key
     ("APMC Ahilyanagar", "ahmednagar"), ("Ahmednagar", "ahmednagar"),
     ("APMC Chandwad", "chandvad"), ("Chandvad", "chandvad"),
     ("APMC  Pimpalgaon Baswant", "pimpalgaon"), ("Pimpalgaon", "pimpalgaon")],
)
def test_market_key_matches_names_across_sources(raw, key):
    assert market_key(raw) == key


def _summary(n_years, above_by_month):
    return pd.DataFrame(
        [{"month": m, "n_years": n_years, "years_above_avg": a} for m, a in above_by_month.items()]
    )


def test_seasonality_is_clear_when_some_months_are_reliably_high_and_others_low():
    above = {m: 5 for m in range(1, 13)}
    above.update({7: 10, 8: 9, 2: 1, 12: 0})
    v = seasonality_verdict(_summary(10, above), min_years=8, threshold=0.75)
    assert v["verdict"] == "clear"
    assert v["high_months"] == [7, 8]
    assert v["low_months"] == [2, 12]


def test_seasonality_is_weak_when_no_month_is_reliable():
    v = seasonality_verdict(_summary(10, {m: 5 for m in range(1, 13)}), min_years=8)
    assert v["verdict"] == "weak"
    assert v["high_months"] == [] and v["low_months"] == []


def test_seasonality_is_insufficient_with_too_few_years():
    v = seasonality_verdict(_summary(4, {m: 4 for m in range(1, 13)}), min_years=8)
    assert v["verdict"] == "insufficient"


@pytest.mark.parametrize(
    "result, verdict",
    [(None, "insufficient"), ((-0.55, 12), "boom_bust"), ((0.1, 12), "none"), ((0.45, 12), "momentum")],
)
def test_boom_bust_verdict(result, verdict):
    assert boom_bust_verdict(result)["verdict"] == verdict


def _monthly(values_by_ym, col):
    return pd.DataFrame(
        [{"market": "Pune", "commodity": "Tomato", "year": y, "month": m, col: v}
         for (y, m), v in values_by_ym.items()]
    )


def test_arrivals_price_correlation_detects_inverse_relationship():
    rng = np.random.default_rng(0)
    arr, price = {}, {}
    for y in range(2015, 2020):
        for m in range(1, 13):
            a = float(rng.uniform(100, 1000))
            arr[(y, m)] = a
            price[(y, m)] = 50_000 / a  # more supply -> lower price
    r, n = arrivals_price_correlation(_monthly(price, "monthly_median"), _monthly(arr, "arrivals"), min_n=24)
    assert r < -0.9
    assert n == 60


def test_arrivals_price_correlation_refuses_small_samples():
    p = _monthly({(2020, m): 10 for m in range(1, 7)}, "monthly_median")
    a = _monthly({(2020, m): 100 for m in range(1, 7)}, "arrivals")
    assert arrivals_price_correlation(p, a, min_n=24) is None


def test_weather_verdict_reports_the_strongest_link():
    from farmiq_data.report import weather_verdict
    corrs = [{"var": "rain", "lag": 0, "r": 0.1, "n": 150}, {"var": "heat", "lag": 1, "r": 0.42, "n": 148},
             {"var": "rain", "lag": 2, "r": -0.2, "n": 146}]
    v = weather_verdict(corrs)
    assert v["verdict"] == "link"
    assert (v["var"], v["lag"], v["r"]) == ("heat", 1, 0.42)


def test_weather_verdict_weak_and_insufficient():
    from farmiq_data.report import weather_verdict
    assert weather_verdict([{"var": "rain", "lag": 0, "r": 0.12, "n": 150}])["verdict"] == "weak"
    assert weather_verdict([])["verdict"] == "insufficient"


def test_compare_sources_matches_by_market_and_date():
    ceda = pd.DataFrame({"market": ["Pune", "Pune", "Rahuri"], "commodity": "Tomato",
                         "date": pd.to_datetime(["2021-01-01", "2021-01-02", "2021-01-01"]),
                         "modal_inr_quintal": [2000.0, 1500.0, 900.0]})
    agm = pd.DataFrame({"market": ["APMC Pune", "APMC Pune", "APMC Nashik"], "commodity": "Tomato",
                        "date": pd.to_datetime(["2021-01-01", "2021-01-02", "2021-01-01"]),
                        "modal_inr_quintal": [2000.0, 1700.0, 800.0]})
    out = compare_sources(ceda, agm)
    assert out["n_matched"] == 2
    assert out["share_equal"] == pytest.approx(0.5)
    assert out["median_abs_diff_inr_quintal"] == pytest.approx(100.0)
