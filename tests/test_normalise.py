from pathlib import Path

import pandas as pd
import pytest

from farmiq_data.normalise import normalise_ceda_prices, parse_agmarknet_csv


def _row(date="2021-03-05T00:00:00.000Z", market_id=153, mn=1000, mx=3000, modal=2000):
    return {
        "date": date,
        "commodity_id": 78,
        "census_state_id": 27,
        "census_district_id": 522,
        "market_id": market_id,
        "min_price": mn,
        "max_price": mx,
        "modal_price": modal,
    }


MARKETS = {153: "Ahmednagar", 1803: "Rahuri"}


def test_converts_rupees_per_quintal_to_per_kg_once():
    clean, _ = normalise_ceda_prices([_row(modal=2000, mn=1000, mx=3000)], "Tomato", MARKETS)
    row = clean.iloc[0]
    assert row["modal_inr_quintal"] == 2000
    assert row["modal_inr_kg"] == pytest.approx(20.0)
    assert row["min_inr_kg"] == pytest.approx(10.0)
    assert row["max_inr_kg"] == pytest.approx(30.0)


def test_keeps_the_calendar_date_without_timezone_shift():
    clean, _ = normalise_ceda_prices([_row(date="2003-01-04T00:00:00.000Z")], "Tomato", MARKETS)
    assert clean.iloc[0]["date"] == pd.Timestamp("2003-01-04")


def test_attaches_market_name_and_source():
    clean, _ = normalise_ceda_prices([_row(market_id=1803)], "Tomato", MARKETS)
    assert clean.iloc[0]["market"] == "Rahuri"
    assert clean.iloc[0]["source"] == "ceda"
    assert clean.iloc[0]["commodity"] == "Tomato"


@pytest.mark.parametrize(
    "kwargs, reason",
    [
        ({"modal": 0}, "non_positive_price"),
        ({"modal": None}, "missing_price"),
        ({"mn": 3000, "mx": 1000, "modal": 2000}, "min_gt_max"),
        ({"mn": 1000, "mx": 3000, "modal": 5000}, "modal_outside_range"),
    ],
)
def test_rejects_invalid_prices_with_a_logged_reason(kwargs, reason):
    clean, rejected = normalise_ceda_prices([_row(**kwargs)], "Tomato", MARKETS)
    assert clean.empty
    assert list(rejected["reason"]) == [reason]


def test_zero_min_or_max_is_allowed_when_modal_is_valid():
    # Some markets report min/max as 0 when only a modal price exists; keep the modal.
    clean, rejected = normalise_ceda_prices([_row(mn=0, mx=0, modal=1500)], "Tomato", MARKETS)
    assert len(clean) == 1 and rejected.empty
    assert pd.isna(clean.iloc[0]["min_inr_kg"]) and pd.isna(clean.iloc[0]["max_inr_kg"])


def test_identical_duplicate_market_day_is_kept_once_and_logged():
    rows = [_row(modal=2000), _row(modal=2000)]
    clean, rejected = normalise_ceda_prices(rows, "Tomato", MARKETS)
    assert len(clean) == 1
    assert clean.iloc[0]["n_rows"] == 1
    assert list(rejected["reason"]) == ["duplicate"]


def test_several_lots_on_one_market_day_are_combined_not_picked_arbitrarily():
    # Same market and day, different lots/varieties (CEDA has no variety field).
    rows = [_row(mn=250, mx=500, modal=375), _row(mn=150, mx=450, modal=300)]
    clean, rejected = normalise_ceda_prices(rows, "Onion", MARKETS)
    assert rejected.empty
    assert len(clean) == 1
    row = clean.iloc[0]
    assert row["modal_inr_quintal"] == pytest.approx(337.5)  # median of the lots' modal prices
    assert row["min_inr_quintal"] == 150 and row["max_inr_quintal"] == 500
    assert row["n_rows"] == 2


def test_combining_uses_the_median_and_ignores_missing_min_max():
    rows = [_row(mn=0, mx=0, modal=100), _row(mn=90, mx=400, modal=200), _row(mn=80, mx=350, modal=300)]
    clean, _ = normalise_ceda_prices(rows, "Onion", MARKETS)
    row = clean.iloc[0]
    assert row["modal_inr_quintal"] == pytest.approx(200)
    assert row["min_inr_quintal"] == 80 and row["max_inr_quintal"] == 400
    assert row["n_rows"] == 3


def test_single_rows_record_one_lot():
    clean, _ = normalise_ceda_prices([_row()], "Tomato", MARKETS)
    assert clean.iloc[0]["n_rows"] == 1


def test_parses_agmarknet_csv_download(tmp_path: Path):
    csv = tmp_path / "report.csv"
    csv.write_text(
        ",,,,,,Daily Price Report-01-01-2021 to 31-12-2021 for Maharashtra,,,,,\n"
        "State/UT,District,Market,Commodity Group,Commodity,Variety,Grade,Min Price,Max Price,Modal Price,Price Unit,Price Date\n"
        'Maharashtra,Ahilyanagar,APMC Ahilyanagar ,Vegetables,Tomato,Other,FAQ,"1,000.00","3,000.00","2,000.00",Rs./Quintal,28-12-2021\n'
        "Maharashtra,Ahilyanagar,APMC Rahuri,Vegetables,Tomato,Local,FAQ,500.00,900.00,700.00,Rs./Quintal,03-01-2021\n",
        encoding="utf-8",
    )
    df = parse_agmarknet_csv(csv)
    assert list(df["market"]) == ["APMC Ahilyanagar", "APMC Rahuri"]
    assert list(df["modal_inr_quintal"]) == [2000.0, 700.0]
    assert list(df["date"]) == [pd.Timestamp("2021-12-28"), pd.Timestamp("2021-01-03")]
    assert set(df["source"]) == {"agmarknet"}
    assert list(df["variety"]) == ["Other", "Local"]


def _agm(rows):
    cols = ["source", "date", "commodity", "state", "district", "market", "variety", "grade",
            "min_inr_quintal", "max_inr_quintal", "modal_inr_quintal"]
    return pd.DataFrame([dict(zip(cols, r, strict=True)) for r in rows])


def test_normalise_agmarknet_maps_names_and_combines_varieties():
    from farmiq_data.normalise import normalise_agmarknet
    agm = _agm([
        ("agmarknet", pd.Timestamp("2026-10-01"), "Onion", "Maharashtra", "Ahilyanagar", "APMC Ahilyanagar", "Red", "Local", 1500, 5500, 3500),
        ("agmarknet", pd.Timestamp("2026-10-01"), "Onion", "Maharashtra", "Ahilyanagar", "APMC Ahilyanagar", "Unhali", "Local", 1000, 5000, 3000),
        ("agmarknet", pd.Timestamp("2026-10-01"), "Onion", "Maharashtra", "Nashik", "APMC Lasalgaon", "Red", "FAQ", 2000, 4000, 3200),
        ("agmarknet", pd.Timestamp("2026-10-02"), "Onion", "Maharashtra", "Nashik", "APMC Lasalgaon", "Red", "FAQ", 2000, 4000, 0),
    ])
    clean, rejected = normalise_agmarknet(
        agm, market_names={"ahmednagar": "Ahmednagar", "lasalgaon": "Lasalgaon"},
        district_names={"Ahilyanagar": "Ahilyanagar (Ahmednagar)"},
    )
    ahm = clean[clean["market"] == "Ahmednagar"].iloc[0]
    assert ahm["modal_inr_quintal"] == pytest.approx(3250)  # median of the two varieties
    assert ahm["n_rows"] == 2
    assert pd.isna(ahm["variety"])  # combined across varieties
    assert ahm["district"] == "Ahilyanagar (Ahmednagar)"
    las = clean[clean["market"] == "Lasalgaon"].iloc[0]
    assert las["district"] == "Nashik" and las["variety"] == "Red" and las["n_rows"] == 1
    assert set(clean["source"]) == {"agmarknet"}
    assert list(rejected["reason"]) == ["non_positive_price"]


def test_normalise_agmarknet_keeps_unknown_markets_with_cleaned_names():
    from farmiq_data.normalise import normalise_agmarknet
    agm = _agm([("agmarknet", pd.Timestamp("2026-10-01"), "Tomato", "Maharashtra", "Pune", "APMC Junnar ", "Local", "FAQ", 500, 900, 700)])
    clean, _ = normalise_agmarknet(agm, market_names={}, district_names={})
    assert clean.iloc[0]["market"] == "Junnar"


def test_append_after_adds_only_dates_beyond_the_primary_source_per_crop():
    from farmiq_data.normalise import append_after
    base = pd.DataFrame({"source": "ceda", "commodity": ["Tomato", "Onion"],
                         "date": pd.to_datetime(["2025-10-30", "2025-10-15"]), "modal_inr_kg": [10.0, 20.0]})
    extra = pd.DataFrame({"source": "agmarknet", "commodity": ["Tomato", "Tomato", "Onion"],
                          "date": pd.to_datetime(["2025-10-30", "2025-10-31", "2025-10-20"]), "modal_inr_kg": [11.0, 12.0, 21.0]})
    out = append_after(base, extra)
    added = out[out["source"] == "agmarknet"].sort_values("date")
    assert list(zip(added["commodity"], added["date"].dt.strftime("%Y-%m-%d"), strict=True)) == [
        ("Onion", "2025-10-20"), ("Tomato", "2025-10-31")]
    assert len(out) == 4


def test_agmarknet_csv_rejects_unexpected_price_unit(tmp_path: Path):
    csv = tmp_path / "report.csv"
    csv.write_text(
        "title\n"
        "State/UT,District,Market,Commodity Group,Commodity,Variety,Grade,Min Price,Max Price,Modal Price,Price Unit,Price Date\n"
        "Maharashtra,Pune,APMC Pune,Vegetables,Tomato,Other,FAQ,10,30,20,Rs./Kg,01-01-2021\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="price unit"):
        parse_agmarknet_csv(csv)
