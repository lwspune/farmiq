"""Fetch state-level (and all-India) daily arrivals and prices for tomato and onion.

Usage:  python scripts/fetch_states.py [--to 2026-11-18]
Saved to data/raw/ceda/ as c<commodity>_s<state>_state_*.json (git-ignored). Re-running skips saved files.

Note: CEDA's quantities endpoint returns "No data exists" for short date windows
(e.g. one month) even when data exists; always request the full range.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from farmiq_data.ceda import CedaClient, fetch_state_series, http_transport, load_api_key  # noqa: E402

# Census 2011 state ids as used by CEDA. 0 = all India. Ordered by importance for
# tomato/onion supply so that, if the daily quota runs out, the most useful come first.
STATES = {
    0: "All India",
    28: "Andhra Pradesh",
    29: "Karnataka",
    23: "Madhya Pradesh",
    24: "Gujarat",
    36: "Telangana",
    8: "Rajasthan",
    27: "Maharashtra",
}
COMMODITIES = {"Tomato": 78, "Onion": 23}
RAW = Path("data/raw/ceda")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="from_date", default="2003-01-01")
    ap.add_argument("--to", dest="to_date", default=date.today().isoformat())
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    client = CedaClient(http_transport(load_api_key()), pause_seconds=12)
    (RAW / "states.json").write_text(json.dumps(STATES), encoding="utf-8")
    for indicator in ("quantities", "prices"):
        for sid, sname in STATES.items():
            for cname, cid in COMMODITIES.items():
                path = fetch_state_series(client, RAW, indicator, cid, sid, args.from_date, args.to_date)
                n = len(json.loads(path.read_text(encoding="utf-8"))["rows"])
                logging.info("%-6s %-15s %-10s %6d rows", cname, sname, indicator, n)


if __name__ == "__main__":
    main()
