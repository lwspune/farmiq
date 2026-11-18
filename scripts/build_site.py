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
from farmiq_data.normalise import normalise_ceda_prices, parse_agmarknet_csv  # noqa: E402
from farmiq_data.patterns import (  # noqa: E402
    annual_change_autocorrelation,
    month_summary,
    seasonal_index,
    volatility_by_month,
)
from farmiq_data.report import (  # noqa: E402
    arrivals_price_correlation,
    boom_bust_verdict,
    compare_sources,
    seasonality_verdict,
)

RAW = ROOT / "data/raw/ceda"
OUT = ROOT / "docs/data"
COMMODITIES = {78: "Tomato", 23: "Onion"}
MIN_YEARS_FOR_VERDICT = 8
THRESHOLD = 0.75
KNOWN_KEYS = {"date", "commodity_id", "census_state_id", "census_district_id", "market_id"}


def _r(x, nd=3):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), nd)


def load_raw(indicator: str) -> list[tuple[int, int, list[dict]]]:
    out = []
    for f in sorted((RAW / indicator).glob("*.json")):
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


def build_commodity(name: str, prices: pd.DataFrame, arrivals: pd.DataFrame) -> dict:
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
        }
    return {"commodity": name, "markets": markets}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    prices, rejected = load_prices()
    arrivals = load_arrivals()
    logging.info("prices: %d clean, %d rejected | arrivals: %d rows", len(prices), len(rejected), len(arrivals))

    # Cross-check against Agmarknet downloads where we have them.
    agm_files = sorted((ROOT / "raw").glob("*.csv"))
    comparison = None
    if agm_files:
        agm = pd.concat([parse_agmarknet_csv(f) for f in agm_files], ignore_index=True)
        # Agmarknet reports one row per variety/grade; compare on its single-variety market-days only.
        agm = agm[~agm.duplicated(["market", "commodity", "date"], keep=False)]
        comparison = compare_sources(prices, agm) | {"files": [f.name for f in agm_files]}
        logging.info("CEDA vs Agmarknet: %s", comparison)

    OUT.mkdir(parents=True, exist_ok=True)
    for name in COMMODITIES.values():
        data = build_commodity(name, prices, arrivals)
        (OUT / f"{name.lower()}.json").write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
        logging.info("%s: %d markets", name, len(data["markets"]))

    reasons = rejected["reason"].value_counts().to_dict() if len(rejected) else {}
    meta = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "date_range": [prices["date"].min().date().isoformat(), prices["date"].max().date().isoformat()],
        "districts": sorted(prices["district"].dropna().unique().tolist()),
        "n_price_days": int(len(prices)),
        "rejected": {k: int(v) for k, v in reasons.items()},
        "source_check": comparison,
        "rules": {"min_years_for_verdict": MIN_YEARS_FOR_VERDICT, "reliable_share": THRESHOLD,
                  "min_days_per_month": 5, "min_months_per_year": 9, "boom_bust_r": 0.3},
        "credit": "Price and arrival data: Agmarknet (Directorate of Marketing & Inspection, GoI), "
                  "via the CEDA Agri Market API, Centre for Economic Data and Analysis, Ashoka University.",
    }
    (OUT / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")

    proc = ROOT / "data/processed"
    proc.mkdir(parents=True, exist_ok=True)
    rejected.to_csv(proc / "rejected.csv", index=False)
    prices.to_csv(proc / "prices_clean.csv", index=False)


if __name__ == "__main__":
    main()
