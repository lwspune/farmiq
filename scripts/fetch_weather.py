"""Fetch daily rainfall and maximum temperature for each district centre.

Usage:  python scripts/fetch_weather.py [--to 2026-11-10]
Source: Open-Meteo historical weather API (ERA5), CC BY 4.0. Saved to data/raw/weather/ (git-ignored).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from farmiq_data.weather import fetch_open_meteo  # noqa: E402

# District headquarters (approximate), keyed by the Census 2011 names CEDA uses.
DISTRICT_CENTRES = {
    "Ahmadnagar": (19.09, 74.74),
    "Aurangabad": (19.88, 75.34),
    "Bid": (18.99, 75.76),
    "Jalna": (19.84, 75.89),
    "Nashik": (20.00, 73.79),
    "Osmanabad": (18.18, 76.04),
    "Pune": (18.52, 73.86),
    "Solapur": (17.66, 75.91),
}
OUT = Path("data/raw/weather")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", default="2003-01-01")
    ap.add_argument("--to", dest="end", default=(date.today() - timedelta(days=7)).isoformat())
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (lat, lon) in DISTRICT_CENTRES.items():
        path = OUT / f"{name}.json"
        if path.exists():
            continue
        payload = fetch_open_meteo(lat, lon, args.start, args.end)
        payload["district"] = name
        path.write_text(json.dumps(payload), encoding="utf-8")
        logging.info("%s: %d days", name, len(payload["daily"]["time"]))
        time.sleep(2)


if __name__ == "__main__":
    main()
