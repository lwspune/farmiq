"""Build the static site's data files from the raw downloads.

Usage:  python scripts/build_site.py
Reads   data/raw/ceda/ (CEDA API) and raw/*.csv (Agmarknet downloads, optional)
Writes  docs/data/meta.json, docs/data/<commodity>.json  (summaries only; no raw rows)
        data/processed/quality.json                     (local data-quality detail)
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from farmiq_data.normalise import (  # noqa: E402
    append_after,
    normalise_agmarknet,
    normalise_ceda_prices,
    parse_agmarknet_csv,
)
from farmiq_data.patterns import (  # noqa: E402
    annual_change_autocorrelation,
    month_summary,
    monthly_medians,
    seasonal_index,
    volatility_by_month,
)
from farmiq_data.planner import harvest_offsets, window_prices, window_summary  # noqa: E402
from farmiq_data.report import (  # noqa: E402
    arrivals_price_correlation,
    boom_bust_verdict,
    compare_sources,
    market_key,
    seasonality_verdict,
    weather_verdict,
)
from farmiq_data.supply import (  # noqa: E402
    monthly_supply,
    parse_state_rows,
    supply_calendar,
    supply_surprise,
    supply_verdict,
)
from farmiq_data.weather import (  # noqa: E402
    after_dry_years,
    lagged_correlation,
    monthly_weather,
    parse_open_meteo,
    price_surprise,
    relative_to_neighbours,
    season_rain_pct,
    weather_anomalies,
)

WEATHER_RAW = ROOT / "data/raw/weather"
WEATHER_LAGS = [0, 1, 2, 3]
SUPPLY_LAGS = [0, 1]


def load_supply() -> dict[str, dict]:
    """Per commodity: state names, monthly supply surprises and the supply calendar."""
    states_file = ROOT / "data/raw/ceda/states.json"
    if not states_file.exists():
        return {}
    names = {int(k): v for k, v in json.loads(states_file.read_text(encoding="utf-8")).items()}
    out: dict[str, dict] = {}
    for f in sorted((ROOT / "data/raw/ceda/quantities").glob("c*_s*_state_*.json")):
        payload = json.loads(f.read_text(encoding="utf-8"))
        req = payload["request"]
        sid, crop = int(req["state_id"]), COMMODITIES[req["commodity_id"]]
        daily = parse_state_rows(payload["rows"], "quantity", state_id=sid)
        if daily.empty:
            continue
        m = monthly_supply(daily)
        entry = out.setdefault(crop, {"monthly": [], "names": names})
        entry["monthly"].append(m)
    for entry in out.values():
        monthly = pd.concat(entry["monthly"], ignore_index=True)
        entry["surprise"] = supply_surprise(monthly)
        entry["calendar"] = supply_calendar(monthly)
        entry["years"] = monthly.groupby("state_id")["year"].agg(["min", "max"])
    return out


def supply_for(index_one_market: pd.DataFrame, supply: dict) -> dict:
    """Correlate this market's price surprises with each state's supply surprises."""
    surprise = price_surprise(index_one_market[["year", "month", "index"]])
    corrs = []
    for sid, g in supply["surprise"].groupby("state_id"):
        for lag in SUPPLY_LAGS:
            res = lagged_correlation(surprise, g, "supply_surprise", lag_months=lag, min_n=60)
            corrs.append({"state": supply["names"].get(sid, str(sid)), "lag": lag,
                          "r": _r(res[0]) if res else None, "n": res[1] if res else 0})
    return {"corr": corrs, "verdict": supply_verdict(corrs)}

RAW = ROOT / "data/raw/ceda"
OUT = ROOT / "docs/data"
COMMODITIES = {78: "Tomato", 23: "Onion"}
MIN_YEARS_FOR_VERDICT = 8
THRESHOLD = 0.75
KNOWN_KEYS = {"date", "commodity_id", "census_state_id", "census_district_id", "market_id"}

# Planner crop-timing options (days from transplant to first harvest; days of harvesting).
# These are typical ranges the viewer picks from, not facts about any farm.
TIMING = {
    "Tomato": {"first": [60, 75, 90], "length": [30, 60, 90], "default": [75, 60]},
    "Onion": {"first": [90, 105, 120], "length": [15, 30], "default": [105, 30]},
}
PLANNER_MIN_FULL_YEARS = 5
RECENT_YEARS = 10


def planner_for(name: str, prices_one_market: pd.DataFrame) -> dict:
    """Harvest-window prices for every transplant month and timing option."""
    t = TIMING[name]
    monthly = monthly_medians(prices_one_market)[["year", "month", "monthly_median"]]
    monthly = monthly.rename(columns={"monthly_median": "median"})
    latest_year = int(prices_one_market["date"].dt.year.max())
    grid = {}
    for first in t["first"]:
        for length in t["length"]:
            months = {}
            for tm in range(1, 13):
                offsets = harvest_offsets(first, length, transplant_month=tm)
                w = window_prices(monthly, tm, offsets)
                s = window_summary(w, recent_years=RECENT_YEARS, min_years=5, latest_year=latest_year)
                months[tm] = {
                    "harvest_months": [((tm - 1 + k) % 12) + 1 for k in offsets],
                    "years": [[int(y), _r(p, 2)] for y, p in w[["transplant_year", "price"]].itertuples(index=False)],
                    "recent": {k: _r(v, 2) for k, v in s["recent"].items()} if s["recent"] else None,
                    "all": {k: _r(v, 2) for k, v in s["all"].items()} if s["all"] else None,
                }
            grid[f"{first}-{length}"] = months
    return {"timing": t, "recent_years": RECENT_YEARS, "grid": grid}


def _r(x, nd=3):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), nd)


def load_raw(indicator: str) -> list[tuple[int, int, list[dict]]]:
    out = []
    for f in sorted((RAW / indicator).glob("*.json")):
        if "_state_" in f.name:  # state-level series are loaded by load_supply()
            continue
        payload = json.loads(f.read_text(encoding="utf-8"))
        req = payload["request"]
        out.append((req["commodity_id"], req["district_id"][0], payload["rows"]))
    return out


# CEDA uses Census 2011 district names; show today's official names alongside.
DISTRICT_DISPLAY = {
    "Ahmadnagar": "Ahilyanagar (Ahmednagar)",
    "Aurangabad": "Chh. Sambhajinagar (Aurangabad)",
    "Bid": "Beed",
    "Osmanabad": "Dharashiv (Osmanabad)",
}


DISPLAY_TO_CENSUS = {v: k for k, v in DISTRICT_DISPLAY.items()}

# Agmarknet 2.0 uses today's district names; map them to the same display names.
AGM_DISTRICTS = {
    "Ahilyanagar": "Ahilyanagar (Ahmednagar)",
    "Chattrapati Sambhajinagar": "Chh. Sambhajinagar (Aurangabad)",
    "Chhatrapati Sambhajinagar": "Chh. Sambhajinagar (Aurangabad)",
    "Beed": "Beed",
    "Dharashiv": "Dharashiv (Osmanabad)",
    "Jalna": "Jalna",
    "Nashik": "Nashik",
    "Pune": "Pune",
    "Solapur": "Solapur",
}


def load_weather() -> dict[str, pd.DataFrame]:
    """Monthly weather with anomalies, keyed by district display name."""
    out = {}
    for f in sorted(WEATHER_RAW.glob("*.json")):
        payload = json.loads(f.read_text(encoding="utf-8"))
        out[DISTRICT_DISPLAY.get(payload["district"], payload["district"])] = weather_anomalies(
            monthly_weather(parse_open_meteo(payload)))
    return out


# The selling season that follows a monsoon, per crop (months of the next calendar year).
NEXT_SEASON = {"Onion": ([3, 4, 5, 6, 7, 8], "Mar-Aug next year"), "Tomato": ([1, 2, 3, 4, 5], "Jan-May next year")}
DRY_THRESHOLD = 85


def dry_year_for(prices_one_market: pd.DataFrame, wa: pd.DataFrame, crop: str) -> dict:
    """This year's monsoon and October rain vs normal, and the market's next-season
    price after past dry monsoons (relative to neighbouring years)."""
    current = int(wa["year"].max())
    monsoon = season_rain_pct(wa, (6, 7, 8, 9), base_years=(2003, current - 1))
    october = season_rain_pct(wa, (10,), base_years=(2003, current - 1))
    months, label = NEXT_SEASON[crop]
    mm = monthly_medians(prices_one_market)
    mm = mm[mm["month"].isin(months)]
    enough = mm.groupby("year")["month"].nunique() >= (len(months) + 1) // 2
    nxt = mm.groupby("year")["monthly_median"].mean()[enough]
    nxt.index = nxt.index - 1  # season after the monsoon of the previous year
    rel = relative_to_neighbours(nxt) if len(nxt) >= 5 else pd.Series(dtype=float)
    after = after_dry_years(monsoon.drop(current, errors="ignore"), rel, DRY_THRESHOLD)
    ranked = monsoon.sort_values()
    cur = {
        "year": current,
        "monsoon_pct": _r(monsoon.get(current), 0),
        "rank_driest": int(list(ranked.index).index(current)) + 1 if current in ranked.index else None,
        "of_years": int(len(ranked)),
        "october_pct": _r(october.get(current), 0),
    }
    return {
        "monsoon": [[int(y), _r(v, 0)] for y, v in monsoon.items()],
        "current": cur,
        "next_label": label,
        "threshold": DRY_THRESHOLD,
        "after": {**after, "median_after_dry": _r(after["median_after_dry"], 2),
                  "median_after_normal": _r(after["median_after_normal"], 2)},
    }


def weather_for(index_one_market: pd.DataFrame, wa: pd.DataFrame) -> dict:
    """Weather normals for the district, and how weather anomalies line up with price surprises."""
    normals = wa.groupby("month").agg(rain=("rain_mm", "mean"), tmax=("tmax_c", "mean")).reset_index()
    surprise = price_surprise(index_one_market[["year", "month", "index"]])
    corrs = []
    for var, col in (("rain", "rain_anom"), ("heat", "tmax_anom")):
        for lag in WEATHER_LAGS:
            res = lagged_correlation(surprise, wa, col, lag_months=lag, min_n=60)
            corrs.append({"var": var, "lag": lag, "r": _r(res[0]) if res else None, "n": res[1] if res else 0})
    return {
        "normals": [[int(m), _r(r, 0), _r(t, 1)] for m, r, t in normals.itertuples(index=False)],
        "years": [int(wa["year"].min()), int(wa["year"].max())],
        "corr": corrs,
        "verdict": weather_verdict(corrs),
    }


def market_names() -> dict[int, str]:
    meta = json.loads((RAW / "markets.json").read_text(encoding="utf-8"))
    return {m["market_id"]: m["market_name"].strip() for ms in meta.values() for m in ms}


def load_prices():
    names = market_names()
    districts = {v: DISTRICT_DISPLAY.get(k, k)
                 for k, v in json.loads((RAW / "districts.json").read_text(encoding="utf-8")).items()}
    clean, rejected = [], []
    for cid, _did, rows in load_raw("prices"):
        if not rows:
            logging.info("no price rows for commodity %s district %s", cid, _did)
            continue
        c, r = normalise_ceda_prices(rows, COMMODITIES[cid], names, district_names=districts)
        clean.append(c)
        rejected.append(r)
    prices = pd.concat(clean, ignore_index=True)
    prices["date"] = pd.to_datetime(prices["date"])
    return prices, pd.concat(rejected, ignore_index=True)


def load_arrivals() -> pd.DataFrame:
    names = market_names()
    frames = []
    for cid, _did, rows in load_raw("quantities"):
        if not rows:
            continue
        df = pd.DataFrame(rows)
        qty_cols = [c for c in df.columns if c not in KNOWN_KEYS]
        if len(qty_cols) != 1:
            raise ValueError(f"Expected one quantity column, found {qty_cols}")
        frames.append(pd.DataFrame({
            "date": pd.to_datetime(df["date"].astype(str).str[:10]),
            "market": df["market_id"].map(names),
            "commodity": COMMODITIES[cid],
            "arrivals": pd.to_numeric(df[qty_cols[0]], errors="coerce"),
        }))
    if not frames:
        return pd.DataFrame(columns=["date", "market", "commodity", "arrivals"])
    a = pd.concat(frames, ignore_index=True)
    return a[a["arrivals"] > 0]


def monthly_arrivals(a: pd.DataFrame) -> pd.DataFrame:
    a = a.assign(year=a["date"].dt.year, month=a["date"].dt.month)
    return a.groupby(["market", "commodity", "year", "month"])["arrivals"].sum().reset_index()


def build_commodity(name: str, prices: pd.DataFrame, arrivals: pd.DataFrame, weather: dict,
                    supply: dict | None = None) -> dict:
    p = prices[prices["commodity"] == name]
    idx = seasonal_index(p)
    summ = month_summary(idx, min_years=5)
    vol = volatility_by_month(p)
    arr_m = monthly_arrivals(arrivals[arrivals["commodity"] == name])
    d = p.assign(year=p["date"].dt.year, month=p["date"].dt.month)
    monthly = d.groupby(["market", "year", "month"])["modal_inr_kg"].agg(["median", "count"]).reset_index()

    markets = {}
    for market, g in p.groupby("market"):
        mi = idx[idx["market"] == market]
        ms = summ[summ["market"] == market].sort_values("month")
        annual = mi.groupby("year")["monthly_median"].mean()
        am = arr_m[arr_m["market"] == market]
        pm = mi[["market", "commodity", "year", "month", "monthly_median"]]
        arr_corr = arrivals_price_correlation(pm, am) if len(am) else None
        mm = monthly[monthly["market"] == market]
        markets[market] = {
            "district": g["district"].dropna().iloc[0] if g["district"].notna().any() else None,
            "n_days": int(len(g)),
            "first": g["date"].min().date().isoformat(),
            "last": g["date"].max().date().isoformat(),
            "full_years": int(mi["year"].nunique()),
            "monthly": [[int(y), int(m), _r(v, 2), int(n)]
                        for y, m, v, n in mm[["year", "month", "median", "count"]].itertuples(index=False)],
            "index": [[int(y), int(m), _r(v)] for y, m, v in mi[["year", "month", "index"]].itertuples(index=False)],
            "season": [
                {"month": int(r.month), "n_years": int(r.n_years), "years_above": int(r.years_above_avg),
                 "median": _r(r.median_index), "p10": _r(r.p10), "p90": _r(r.p90)}
                for r in ms.itertuples()
            ],
            "season_verdict": seasonality_verdict(ms, MIN_YEARS_FOR_VERDICT, THRESHOLD) if len(ms) else
                              {"verdict": "insufficient", "n_years": 0, "high_months": [], "low_months": []},
            "volatility": [[int(m), _r(v), int(n)] for m, v, n in
                           vol[vol["market"] == market][["month", "median_cv", "n_years"]].itertuples(index=False)],
            "annual": [[int(y), _r(v, 2)] for y, v in annual.items()],
            "boom_bust": boom_bust_verdict(annual_change_autocorrelation(annual, min_pairs=6)),
            "arrivals": [[int(y), int(m), _r(v, 1)]
                         for y, m, v in am[["year", "month", "arrivals"]].itertuples(index=False)],
            "arrivals_price": ({"r": _r(arr_corr[0]), "n_months": arr_corr[1]} if arr_corr else None),
            "planner": planner_for(name, g) if mi["year"].nunique() >= PLANNER_MIN_FULL_YEARS else None,
            "dry": (dry_year_for(g, weather[g["district"].iloc[0]], name)
                    if g["district"].iloc[0] in weather else None),
            "weather": (weather_for(mi, weather[g["district"].iloc[0]])
                        if len(mi) and g["district"].iloc[0] in weather else None),
            "supply": supply_for(mi, supply) if supply and len(mi) else None,
        }
    out = {"commodity": name, "markets": markets}
    if supply:
        cal = supply["calendar"]
        out["supply_calendar"] = {
            "states": [supply["names"].get(int(s), str(s)) for s in cal["state_id"].unique()],
            "rows": [[supply["names"].get(int(s), str(s)), int(m), _r(sh), int(n)]
                     for s, m, sh, n in cal[["state_id", "month", "share", "n_years"]].itertuples(index=False)],
            "years": {supply["names"].get(int(s), str(s)): [int(r["min"]), int(r["max"])]
                      for s, r in supply["years"].iterrows()},
        }
    return out


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    prices, rejected = load_prices()
    arrivals = load_arrivals()
    weather = load_weather()
    supply = load_supply()
    logging.info("prices: %d clean, %d rejected | arrivals: %d rows", len(prices), len(rejected), len(arrivals))

    # Agmarknet downloads: cross-check CEDA where they overlap, and extend the
    # series past CEDA's last date (CEDA updates monthly and lags).
    agm_files = sorted((ROOT / "raw").glob("*.csv"))
    comparison = None
    sources = {"ceda": [prices["date"].min().date().isoformat(), prices["date"].max().date().isoformat()]}
    if agm_files:
        agm = pd.concat([parse_agmarknet_csv(f) for f in agm_files], ignore_index=True)
        # Agmarknet reports one row per variety/grade; compare on its single-variety market-days only.
        single = agm[~agm.duplicated(["market", "commodity", "date"], keep=False)]
        comparison = compare_sources(prices, single) | {"files": [f.name for f in agm_files]}
        logging.info("CEDA vs Agmarknet: %s", comparison)

        agm = agm[agm["district"].isin(AGM_DISTRICTS)]
        known = {market_key(n): n for n in prices["market"].dropna().unique()}
        agm_clean, agm_rej = normalise_agmarknet(agm, known, AGM_DISTRICTS)
        before = len(prices)
        prices = append_after(prices, agm_clean)
        added = prices[prices["source"] == "agmarknet"]
        rejected = pd.concat([rejected, agm_rej[agm_rej["date"].isin(added["date"])]], ignore_index=True)
        if len(added):
            sources["agmarknet"] = [added["date"].min().date().isoformat(), added["date"].max().date().isoformat()]
        logging.info("Agmarknet extension: %d market-days added after CEDA's last date", len(prices) - before)

    OUT.mkdir(parents=True, exist_ok=True)
    available = []
    for name in COMMODITIES.values():
        data = build_commodity(name, prices, arrivals, weather, supply.get(name))
        (OUT / f"{name.lower()}.json").write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
        logging.info("%s: %d markets", name, len(data["markets"]))
        if data["markets"]:
            available.append(name.lower())

    reasons = rejected["reason"].value_counts().to_dict() if len(rejected) else {}
    meta = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "date_range": [prices["date"].min().date().isoformat(), prices["date"].max().date().isoformat()],
        "sources": sources,
        "districts": sorted(prices["district"].dropna().unique().tolist()),
        "commodities": available,
        "n_price_days": int(len(prices)),
        "combined_market_days": int((prices["n_rows"] > 1).sum()),
        "rejected": {k: int(v) for k, v in reasons.items()},
        "source_check": comparison,
        "rules": {"min_years_for_verdict": MIN_YEARS_FOR_VERDICT, "reliable_share": THRESHOLD,
                  "min_days_per_month": 5, "min_months_per_year": 9, "boom_bust_r": 0.3},
        "credit": "Price and arrival data: Agmarknet (Directorate of Marketing & Inspection, GoI), "
                  "via the CEDA Agri Market API, Centre for Economic Data and Analysis, Ashoka University. "
                  "Weather: Open-Meteo historical weather API (ERA5 reanalysis), CC BY 4.0.",
    }
    (OUT / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")

    proc = ROOT / "data/processed"
    proc.mkdir(parents=True, exist_ok=True)
    rejected.to_csv(proc / "rejected.csv", index=False)
    prices.to_csv(proc / "prices_clean.csv", index=False)


if __name__ == "__main__":
    main()
