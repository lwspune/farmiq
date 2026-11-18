"""Client for the CEDA Agmarknet API (https://api.ceda.ashoka.edu.in/).

Data: Agmarknet, via the Centre for Economic Data and Analysis (CEDA), Ashoka
University. Free for non-commercial use with credit. The API key is read from
the CEDA_API_KEY environment variable or a local, git-ignored .env file and is
never logged or written to output files.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

BASE_URL = "https://api.ceda.ashoka.edu.in/v1"
log = logging.getLogger(__name__)

Transport = Callable[[str, str, dict | None], dict]


def load_api_key(env_file: Path = Path(".env")) -> str:
    key = os.environ.get("CEDA_API_KEY")
    if not key and env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("CEDA_API_KEY="):
                key = line.split("=", 1)[1].strip()
    if not key:
        raise RuntimeError("CEDA_API_KEY is not set (environment or .env)")
    return key


def http_transport(api_key: str, retries: int = 5) -> Transport:
    def send(method: str, path: str, body: dict | None) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            BASE_URL + path, data=data, method=method,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        )
        for attempt in range(1, retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    return json.load(resp)
            except urllib.error.HTTPError as err:
                if err.code == 429 and attempt < retries:
                    wait = int(err.headers.get("Retry-After") or 0) or 90 * attempt
                    log.warning("CEDA rate limit; waiting %ss", wait)
                    time.sleep(wait)
                    continue
                log.error("CEDA %s %s failed: HTTP %s", method, path, err.code)
                raise
            except urllib.error.URLError as err:
                if attempt < retries:
                    time.sleep(5 * attempt)
                    continue
                log.error("CEDA %s %s failed: %s", method, path, err.reason)
                raise
        raise RuntimeError("unreachable")

    return send


class CedaClient:
    def __init__(self, transport: Transport, pause_seconds: float = 2.0):
        self._send = transport
        self._pause = pause_seconds

    def _call(self, method: str, path: str, body: dict | None = None) -> list[dict]:
        payload = self._send(method, path, body)
        if self._pause:
            time.sleep(self._pause)
        out = payload.get("output", payload)
        if out.get("type") != "success":
            log.info("CEDA %s returned no data: %s", path, out.get("message"))
            return []
        return out.get("data") or []

    def commodities(self) -> list[dict]:
        return self._call("GET", "/agmarknet/commodities")

    def geographies(self) -> list[dict]:
        return self._call("GET", "/agmarknet/geographies")

    def markets(self, commodity_id: int, state_id: int, district_id: int, indicator: str = "price") -> list[dict]:
        return self._call("POST", "/agmarknet/markets", {
            "commodity_id": commodity_id, "state_id": state_id,
            "district_id": district_id, "indicator": indicator,
        })

    def _series(self, path, commodity_id, state_id, district_ids, from_date, to_date):
        """`district_ids=None` asks for the state level (state_id 0 = all India)."""
        body = {"commodity_id": commodity_id, "state_id": state_id, "from_date": from_date, "to_date": to_date}
        if district_ids is not None:
            body["district_id"] = list(district_ids)
        return self._call("POST", path, body)

    def prices(self, commodity_id, state_id, district_ids, from_date, to_date) -> list[dict]:
        return self._series("/agmarknet/prices", commodity_id, state_id, district_ids, from_date, to_date)

    def quantities(self, commodity_id, state_id, district_ids, from_date, to_date) -> list[dict]:
        return self._series("/agmarknet/quantities", commodity_id, state_id, district_ids, from_date, to_date)


def fetch_series(
    client: CedaClient, out_dir: Path, indicator: str, commodity_id: int, district_id: int,
    from_date: str, to_date: str, state_id: int = 27,
) -> Path:
    """Fetch one commodity x district series and save the raw rows. Skips files already saved."""
    out = Path(out_dir) / indicator / f"c{commodity_id}_s{state_id}_d{district_id}_{from_date}_{to_date}.json"
    if out.exists():
        return out
    fetch = client.prices if indicator == "prices" else client.quantities
    rows = fetch(commodity_id, state_id, [district_id], from_date, to_date)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "request": {"indicator": indicator, "commodity_id": commodity_id, "state_id": state_id,
                    "district_id": [district_id], "from_date": from_date, "to_date": to_date},
        "fetched_at": datetime.now(UTC).isoformat(),
        "rows": rows,
    }), encoding="utf-8")
    return out


def fetch_state_series(
    client: CedaClient, out_dir: Path, indicator: str, commodity_id: int, state_id: int,
    from_date: str, to_date: str,
) -> Path:
    """Fetch one commodity at state level (state_id 0 = all India). Skips files already saved."""
    out = Path(out_dir) / indicator / f"c{commodity_id}_s{state_id}_state_{from_date}_{to_date}.json"
    if out.exists():
        return out
    fetch = client.prices if indicator == "prices" else client.quantities
    rows = fetch(commodity_id, state_id, None, from_date, to_date)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "request": {"indicator": indicator, "commodity_id": commodity_id, "state_id": state_id,
                    "from_date": from_date, "to_date": to_date},
        "fetched_at": datetime.now(UTC).isoformat(),
        "rows": rows,
    }), encoding="utf-8")
    return out
