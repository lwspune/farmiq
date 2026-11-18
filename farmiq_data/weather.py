"""Local weather context for price surprises.

Weather: Open-Meteo historical weather API (ERA5 reanalysis), free for
non-commercial use with attribution (CC BY 4.0). One point per district centre:
it describes the local season, not the national supply that mostly sets prices.

A "price surprise" is how far a month's price was from the usual level for that
calendar month, so the normal seasonal swing is not mistaken for a weather effect.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request

import numpy as np
import pandas as pd

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
log = logging.getLogger(__name__)


def fetch_open_meteo(lat: float, lon: float, start: str, end: str, retries: int = 3) -> dict:
    query = urllib.parse.urlencode({
        "latitude": lat, "longitude": lon, "start_date": start, "end_date": end,
        "daily": "precipitation_sum,temperature_2m_max", "timezone": "Asia/Kolkata",
    })
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(f"{ARCHIVE_URL}?{query}", timeout=120) as resp:
                return json.load(resp)
        except (urllib.error.HTTPError, urllib.error.URLError) as err:
            if attempt == retries:
                log.error("Open-Meteo request failed for %s,%s: %s", lat, lon, err)
                raise
            time.sleep(10 * attempt)
    raise RuntimeError("unreachable")


def parse_open_meteo(payload: dict) -> pd.DataFrame:
    d = payload["daily"]
    return pd.DataFrame({
        "date": pd.to_datetime(d["time"]),
        "rain_mm": pd.to_numeric(pd.Series(d["precipitation_sum"], dtype="object"), errors="coerce"),
        "tmax_c": pd.to_numeric(pd.Series(d["temperature_2m_max"], dtype="object"), errors="coerce"),
    })


def monthly_weather(daily: pd.DataFrame, min_days: int = 25) -> pd.DataFrame:
    """Monthly rainfall total and mean daily maximum temperature; partial months dropped."""
    d = daily.assign(year=daily["date"].dt.year, month=daily["date"].dt.month)
    m = d.groupby(["year", "month"]).agg(
        rain_mm=("rain_mm", "sum"), tmax_c=("tmax_c", "mean"), n_days=("date", "count")
    ).reset_index()
    return m[m["n_days"] >= min_days].reset_index(drop=True)


def weather_anomalies(monthly: pd.DataFrame) -> pd.DataFrame:
    """Difference from the average for the same calendar month across all years."""
    out = monthly.copy()
    for col in ("rain_mm", "tmax_c"):
        normal = out.groupby("month")[col].transform("mean")
        out[col.split("_")[0] + "_anom"] = out[col] - normal
    return out


def price_surprise(index_df: pd.DataFrame) -> pd.DataFrame:
    """log(month's seasonal index / that calendar month's median index), per market if present."""
    keys = [k for k in ("market", "commodity") if k in index_df.columns]
    usual = index_df.groupby([*keys, "month"])["index"].transform("median")
    out = index_df[[*keys, "year", "month"]].copy()
    out["surprise"] = np.log(index_df["index"] / usual)
    return out


def season_rain_pct(
    monthly: pd.DataFrame, months=(6, 7, 8, 9), base_years: tuple[int, int] = (2003, 2025)
) -> pd.Series:
    """Each year's rainfall over `months` as a % of the average over `base_years`.
    Years missing any of the months are left out rather than under-counted."""
    m = monthly[monthly["month"].isin(months)]
    complete = m.groupby("year")["month"].nunique() == len(months)
    totals = m.groupby("year")["rain_mm"].sum()[complete]
    base = totals.loc[base_years[0]:base_years[1]].mean()
    return totals / base * 100


def relative_to_neighbours(series: pd.Series, window: int = 7) -> pd.Series:
    """Value divided by the median of the surrounding calendar years (centred window),
    so slow trends such as inflation do not look like shocks."""
    full = series.reindex(range(int(series.index.min()), int(series.index.max()) + 1))
    med = full.rolling(window, center=True, min_periods=3).median()
    return (full / med).dropna()


def after_dry_years(rain_pct: pd.Series, next_rel: pd.Series, threshold: float = 85) -> dict:
    """Next-season price (relative to neighbouring years) after dry vs normal monsoons."""
    both = pd.concat([rain_pct.rename("rain"), next_rel.rename("rel")], axis=1).dropna()
    dry = both[both["rain"] < threshold]
    normal = both[both["rain"] >= threshold]
    return {
        "dry_years": [[int(y), round(float(r), 1), round(float(v), 2)] for y, (r, v) in dry.iterrows()],
        "median_after_dry": float(dry["rel"].median()) if len(dry) else None,
        "median_after_normal": float(normal["rel"].median()) if len(normal) else None,
        "n_dry": int(len(dry)),
        "n_normal": int(len(normal)),
        "dry_higher": int((dry["rel"] > 1).sum()),
    }


def lagged_correlation(surprise: pd.DataFrame, weather: pd.DataFrame, column: str, lag_months: int, min_n: int = 60):
    """Correlation between a weather anomaly and the price surprise `lag_months` later.

    Returns (r, n_months) or None when fewer than `min_n` months line up.
    """
    w = weather[["year", "month", column]].copy()
    t = w["year"] * 12 + w["month"] - 1 + lag_months
    w["year"], w["month"] = t // 12, t % 12 + 1
    m = surprise[["year", "month", "surprise"]].merge(w, on=["year", "month"]).dropna()
    if len(m) < min_n or m[column].std() == 0 or m["surprise"].std() == 0:
        return None
    return float(np.corrcoef(m[column], m["surprise"])[0, 1]), int(len(m))
