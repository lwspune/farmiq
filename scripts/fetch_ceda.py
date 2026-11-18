"""Fetch tomato and onion prices and arrivals for Newasa's region from CEDA.

Usage:  python scripts/fetch_ceda.py [--to 2026-11-18]
Raw responses go to data/raw/ceda/ (git-ignored). Re-running skips files already saved.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from farmiq_data.ceda import CedaClient, fetch_series, http_transport, load_api_key  # noqa: E402

MAHARASHTRA = 27
COMMODITIES = {"Tomato": 78, "Onion": 23}
# Newasa is in Ahmednagar (Ahilyanagar) district. Neighbours and major nearby markets.
# Census 2011 names, as CEDA uses them.
DISTRICTS = ["Ahmadnagar", "Aurangabad", "Bid", "Beed", "Nashik", "Pune", "Jalna", "Solapur", "Osmanabad"]
RAW = Path("data/raw/ceda")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="from_date", default="2003-01-01")
    ap.add_argument("--to", dest="to_date", default=date.today().isoformat())
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    client = CedaClient(http_transport(load_api_key()), pause_seconds=12)
    geo = [g for g in client.geographies() if g["census_state_id"] == MAHARASHTRA]
    by_name = {g["census_district_name"]: g["census_district_id"] for g in geo}
    districts = {n: by_name[n] for n in DISTRICTS if n in by_name}
    missing = [n for n in DISTRICTS if n not in by_name]
    logging.info("districts: %s | not in CEDA: %s", districts, missing)

    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / "districts.json").write_text(json.dumps(districts), encoding="utf-8")
    meta_path = RAW / "markets.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    for cname, cid in COMMODITIES.items():
        for dname, did in districts.items():
            key = f"{cid}:{did}"
            if key not in meta:
                meta[key] = client.markets(cid, MAHARASHTRA, did, "price")
                meta_path.write_text(json.dumps(meta), encoding="utf-8")
            for indicator in ("prices", "quantities"):
                path = fetch_series(client, RAW, indicator, cid, did, args.from_date, args.to_date)
                n = len(json.loads(path.read_text(encoding="utf-8"))["rows"])
                logging.info("%-6s %-10s %-10s %6d rows", cname, dname, indicator, n)


if __name__ == "__main__":
    main()
