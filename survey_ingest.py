"""Ingest customer-behaviour surveys from 8 Google Sheets → data/survey.csv.

Each sheet is owned by one surveyor. Sheets share the same Google Form
template as the Mumbai pilot survey — we reuse the RAG classifier and
serial normalizer from the main `data` module.

Run standalone:
    .venv/bin/python "Price Live/survey_ingest.py"

Called from the combined refresh:
    from survey_ingest import refresh_survey; refresh_survey()
"""
from __future__ import annotations

import io
import re
import time
from pathlib import Path

import pandas as pd
import requests

HERE = Path(__file__).resolve().parent

from _shared import _normalize_alpha_serial, classify_rag  # noqa: E402

DATA_DIR = HERE / "data"
DATA_DIR.mkdir(exist_ok=True)
SURVEY_CSV = DATA_DIR / "survey.csv"
STORE_FRANCHISEE_CSV = DATA_DIR / "store_franchisee.csv"

# Scope: only keep surveys from franchisee-1 stores (see refresh_dashboard_data.py).
FRANCHISEE_ID = 1

# One entry per surveyor: (name, sheet_id, gid).
SHEETS: list[tuple[str, str, str]] = [
    ("Nadeem",  "1kB9V9WSZRQErjbMMAbHYH-GtmYiX4gJnpX3T1wjcTSU", "1083579682"),
    ("Shehzad", "1o7WhbMISOS9n12W7xjRJbggcMZ7mc62Km_zAhQqutUA", "1214622290"),
    ("Neha",    "1M_4OIoCx3bmunIEe-wjRGB0rhkC24MqkCLwRC_7wU64", "438985672"),
    ("Sonam",   "1RDsRH-Nh73jetY9KNWXI5Jpdud7shx2m3arkVbeBtyo", "1350436150"),
    ("Aliya",   "1JCnWrM0V58M8kumGDmFJVBsF5qFLX6nk40Mq04xRzUg", "1915751415"),
    ("Utkarsh", "1137fPTlzTtHAVkDJ6U4zGafsLSmzyOlHHS4YbkE2wME", "1337135438"),
    ("Ahmad",   "1Asn0kF6UKqnDu-gBWMLn6F4agNIodFD2GCPxam8JOqs", "1989217526"),
    ("Shreni",  "1Gtq78w4pBlAbSrQeX8l2l5bKMUaXH5Lj9ftekHcWtrE", "1086049011"),
]

CHAIN_GO_LIVE = pd.Timestamp("2026-07-01")

# Column indices in the Google Form output (0-based).
COL_TIMESTAMP = 0
COL_STORE = 1
COL_STAFF_INFORMED = 2
COL_SPOKE_PRICE = 3
COL_CHECKED_BILL = 4
COL_NONVERBAL = 5
COL_REACTION_TYPE = 6
COL_WHAT_SAID = 7
COL_OUTCOME = 8
COL_BILL = 9
COL_NOTES = 10

STORE_SUFFIX_RE = re.compile(r"\s*\(\s*\d+\s*\)\s*$")


def _fetch_sheet(sheet_id: str, gid: str, retries: int = 3) -> pd.DataFrame:
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&gid={gid}"
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            return pd.read_csv(io.StringIO(r.text), dtype=str).fillna("")
        except Exception as e:
            last_err = e
            time.sleep(1 + attempt)
    raise RuntimeError(f"Failed to fetch sheet {sheet_id}/{gid}: {last_err}")


def _normalize_frame(raw: pd.DataFrame, surveyor: str, sheet_id: str) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame()
    n = raw.shape[1]
    if n < 11:
        raise ValueError(f"{surveyor}'s sheet has only {n} columns (expected ≥11)")
    cols = list(raw.columns)
    df = pd.DataFrame({
        "surveyor": surveyor,
        "source_sheet_id": sheet_id,
        "timestamp_raw": raw[cols[COL_TIMESTAMP]],
        "store_raw": raw[cols[COL_STORE]],
        "staff_informed": raw[cols[COL_STAFF_INFORMED]],
        "spoke_price": raw[cols[COL_SPOKE_PRICE]],
        "checked_bill": raw[cols[COL_CHECKED_BILL]],
        "nonverbal": raw[cols[COL_NONVERBAL]],
        "reaction_type": raw[cols[COL_REACTION_TYPE]],
        "what_said": raw[cols[COL_WHAT_SAID]],
        "outcome": raw[cols[COL_OUTCOME]],
        "bill_raw": raw[cols[COL_BILL]].fillna("").str.strip(),
        "notes": raw[cols[COL_NOTES]],
    })
    df["submitted_at"] = pd.to_datetime(df["timestamp_raw"], errors="coerce")
    df["submitted_date"] = df["submitted_at"].dt.date
    df["store"] = df["store_raw"].str.replace(STORE_SUFFIX_RE, "", regex=True).str.strip()
    df["serial_norm"] = df["bill_raw"].apply(_normalize_alpha_serial)

    rag_tuples = [classify_rag(o, False) for o in df["outcome"]]
    df["rag"] = [t[0] for t in rag_tuples]
    df["is_amber_partial"] = [t[1] for t in rag_tuples]
    df["is_amber_genrtn"] = [t[2] for t in rag_tuples]

    return df


def refresh_survey() -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for surveyor, sid, gid in SHEETS:
        try:
            raw = _fetch_sheet(sid, gid)
        except Exception as e:
            print(f"  ⚠️  {surveyor}: fetch failed — {e}")
            continue
        try:
            df = _normalize_frame(raw, surveyor, sid)
        except Exception as e:
            print(f"  ⚠️  {surveyor}: normalize failed — {e}")
            continue
        print(f"  {surveyor:8}  raw={len(raw):4}  normalized={len(df):4}")
        frames.append(df)

    if not frames:
        print("No sheets fetched — writing empty survey.csv")
        pd.DataFrame().to_csv(SURVEY_CSV, index=False)
        return pd.DataFrame()

    all_df = pd.concat(frames, ignore_index=True)
    before = len(all_df)
    all_df = all_df.drop_duplicates(subset=["surveyor", "timestamp_raw", "bill_raw"], keep="last")
    after = len(all_df)
    all_df = all_df[all_df["submitted_at"].notna()]
    all_df = all_df[all_df["submitted_at"] >= CHAIN_GO_LIVE].copy()

    # Franchisee-1 scope filter (matches the Impact page's scope).
    franch_dropped_by_surveyor: dict[str, int] = {}
    if STORE_FRANCHISEE_CSV.exists():
        sf = pd.read_csv(STORE_FRANCHISEE_CSV)
        f1_stores = set(sf[sf["franchisee_id"] == FRANCHISEE_ID]["store_name"].astype(str))
        pre_f = len(all_df)
        matched_mask = all_df["store"].isin(f1_stores)
        franch_dropped_by_surveyor = (all_df[~matched_mask]
                                       .groupby("surveyor").size().to_dict())
        all_df = all_df[matched_mask].copy()
        print(f"  franchisee-1 filter: kept {len(all_df):,}/{pre_f:,} rows")
    else:
        print(f"  ⚠️  {STORE_FRANCHISEE_CSV.name} missing — skipping franchisee filter "
              f"(run refresh_dashboard_data.py first).")

    all_df = all_df.sort_values(["submitted_at", "surveyor"], ascending=[False, True]).reset_index(drop=True)

    all_df.to_csv(SURVEY_CSV, index=False)
    print(f"\nTotal rows written: {len(all_df):,}  (dedup dropped {before - after}, then filtered to >= {CHAIN_GO_LIVE.date()})")
    if franch_dropped_by_surveyor:
        print(f"  dropped by franchisee filter (per surveyor):")
        for s, n in sorted(franch_dropped_by_surveyor.items(), key=lambda x: -x[1]):
            print(f"    {s:8}  {n}")
    print(f"  date range: {all_df['submitted_at'].min()} → {all_df['submitted_at'].max()}")
    print(f"  RAG        : {dict(all_df['rag'].value_counts())}")
    print(f"  Per surveyor:")
    for s, n in all_df["surveyor"].value_counts().items():
        print(f"    {s:8}  {n:4}")
    print(f"→ {SURVEY_CSV}")
    return all_df


if __name__ == "__main__":
    refresh_survey()
