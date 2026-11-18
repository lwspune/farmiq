"""Turn raw price records from each source into one tidy table.

Prices arrive in rupees per quintal. They are converted to rupees per kg here,
and only here. Invalid records are never dropped silently: they are returned in
a separate `rejected` table with a reason.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

QUINTAL_KG = 100

COLUMNS = [
    "source", "date", "commodity", "state", "district", "market", "market_id", "variety", "grade",
    "min_inr_quintal", "max_inr_quintal", "modal_inr_quintal",
    "min_inr_kg", "max_inr_kg", "modal_inr_kg", "n_rows",
]


def _reject_reason(mn, mx, modal) -> str | None:
    if modal is None or pd.isna(modal):
        return "missing_price"
    if modal <= 0:
        return "non_positive_price"
    if mn > 0 and mx > 0:
        if mn > mx:
            return "min_gt_max"
        if not (mn <= modal <= mx):
            return "modal_outside_range"
    return None


def _finish(df: pd.DataFrame) -> pd.DataFrame:
    for col in ("min", "max"):
        q = df[f"{col}_inr_quintal"].where(df[f"{col}_inr_quintal"] > 0)
        df[f"{col}_inr_quintal"] = q
        df[f"{col}_inr_kg"] = q / QUINTAL_KG
    df["modal_inr_kg"] = df["modal_inr_quintal"] / QUINTAL_KG
    return df[COLUMNS]


def _split_valid(df: pd.DataFrame, key: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    reasons = [
        _reject_reason(mn, mx, md)
        for mn, mx, md in zip(df["min_inr_quintal"], df["max_inr_quintal"], df["modal_inr_quintal"], strict=True)
    ]
    df = df.assign(reason=reasons)
    rejected = [df[df["reason"].notna()]]
    valid = df[df["reason"].isna()].drop(columns="reason")

    # Exact repeats of the same record are dropped (and logged).
    exact = valid.duplicated(subset=[*key, "min_inr_quintal", "max_inr_quintal", "modal_inr_quintal"], keep="first")
    rejected.append(valid[exact].assign(reason="duplicate"))
    valid = valid[~exact]

    # Several different records for one market-day are separate lots or varieties
    # (the source has no variety field). Rather than pick one arbitrarily, combine
    # them: median of the modal prices, lowest min and highest max, and record how
    # many rows were combined.
    valid = valid.assign(n_rows=valid.groupby(key)["modal_inr_quintal"].transform("size"))
    single = valid[valid["n_rows"] == 1]
    multi = valid[valid["n_rows"] > 1]
    if not multi.empty:
        pos = multi.assign(
            min_pos=multi["min_inr_quintal"].where(multi["min_inr_quintal"] > 0),
            max_pos=multi["max_inr_quintal"].where(multi["max_inr_quintal"] > 0),
        )
        first_cols = [c for c in multi.columns if c not in
                      (*key, "min_inr_quintal", "max_inr_quintal", "modal_inr_quintal", "n_rows")]
        combined = pos.groupby(key, as_index=False).agg(
            modal_inr_quintal=("modal_inr_quintal", "median"),
            min_inr_quintal=("min_pos", "min"),
            max_inr_quintal=("max_pos", "max"),
            n_rows=("modal_inr_quintal", "size"),
            **{c: (c, "first") for c in first_cols},
        )
        combined[["min_inr_quintal", "max_inr_quintal"]] = combined[["min_inr_quintal", "max_inr_quintal"]].fillna(0)
        valid = pd.concat([single, combined[valid.columns]], ignore_index=True)

    rej = pd.concat(rejected, ignore_index=True)
    return _finish(valid.reset_index(drop=True)), rej.reset_index(drop=True)


def normalise_ceda_prices(
    rows: list[dict], commodity: str, market_names: dict[int, str],
    state: str = "Maharashtra", district_names: dict[int, str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Normalise rows from the CEDA `/agmarknet/prices` endpoint."""
    district_names = district_names or {}
    df = pd.DataFrame(rows)
    if df.empty:
        empty = pd.DataFrame(columns=COLUMNS)
        return empty, pd.DataFrame(columns=[*COLUMNS, "reason"])
    out = pd.DataFrame({
        "source": "ceda",
        # The API sends midnight UTC; the calendar date is what was reported.
        "date": pd.to_datetime(df["date"].astype(str).str[:10]),
        "commodity": commodity,
        "state": state,
        "district": df["census_district_id"].map(district_names),
        "market": df["market_id"].map(market_names),
        "market_id": df["market_id"],
        "variety": None,
        "grade": None,
        "min_inr_quintal": pd.to_numeric(df["min_price"], errors="coerce"),
        "max_inr_quintal": pd.to_numeric(df["max_price"], errors="coerce"),
        "modal_inr_quintal": pd.to_numeric(df["modal_price"], errors="coerce"),
    })
    out["min_inr_quintal"] = out["min_inr_quintal"].fillna(0)
    out["max_inr_quintal"] = out["max_inr_quintal"].fillna(0)
    return _split_valid(out, key=["source", "market_id", "commodity", "date"])


def normalise_agmarknet(
    df: pd.DataFrame, market_names: dict[str, str], district_names: dict[str, str]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Bring parsed Agmarknet rows into the same tidy table as CEDA.

    `market_names` maps a market key (see report.market_key) to the CEDA market
    name, so one market keeps one name across sources; unknown markets keep their
    own name without the "APMC" prefix. Several varieties or grades reported for
    the same market-day are combined with the same rule as CEDA lots.
    """
    from farmiq_data.report import market_key  # local import: report has no dependency back on this module

    out = df.copy()
    keys = out["market"].map(market_key)
    cleaned = out["market"].astype(str).str.strip().str.replace(r"(?i)^apmc\s+", "", regex=True)
    out["market"] = [market_names.get(k, c) for k, c in zip(keys, cleaned, strict=True)]
    out["district"] = out["district"].map(lambda d: district_names.get(d, d))
    out["market_id"] = None
    for col in ("min_inr_quintal", "max_inr_quintal"):
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0)
    clean, rejected = _split_valid(out, key=["source", "market", "commodity", "date"])
    combined = clean["n_rows"] > 1
    clean.loc[combined, ["variety", "grade"]] = None
    return clean, rejected


def append_after(primary: pd.DataFrame, extra: pd.DataFrame) -> pd.DataFrame:
    """Add rows from `extra` only for dates after the primary source's last date,
    per commodity, so two sources never overlap or double-count."""
    last = primary.groupby("commodity")["date"].max()
    cutoff = extra["commodity"].map(last)
    keep = extra[cutoff.isna() | (extra["date"] > cutoff)]
    return pd.concat([primary, keep], ignore_index=True)


def _num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series.astype(str).str.replace(",", "", regex=False), errors="coerce")


def parse_agmarknet_csv(path: Path | str) -> pd.DataFrame:
    """Parse a 'Daily Price Report' CSV downloaded from agmarknet.gov.in.

    The first line is a title row; the second is the header.
    """
    raw = pd.read_csv(path, skiprows=1, dtype=str)
    units = set(raw["Price Unit"].dropna().str.strip())
    if units - {"Rs./Quintal"}:
        raise ValueError(f"Unexpected price unit(s) {sorted(units)}; expected Rs./Quintal")
    return pd.DataFrame({
        "source": "agmarknet",
        "date": pd.to_datetime(raw["Price Date"].str.strip(), format="%d-%m-%Y"),
        "commodity": raw["Commodity"].str.strip(),
        "state": raw["State/UT"].str.strip(),
        "district": raw["District"].str.strip(),
        "market": raw["Market"].str.strip(),
        "variety": raw["Variety"].str.strip(),
        "grade": raw["Grade"].str.strip(),
        "min_inr_quintal": _num(raw["Min Price"]),
        "max_inr_quintal": _num(raw["Max Price"]),
        "modal_inr_quintal": _num(raw["Modal Price"]),
    })
