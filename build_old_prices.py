"""Rebuild drug_old_selling_price.csv from Redshift.

For each drug sold at franchisee-1 non-pilot stores, pick the pre-July
modal selling rate (weighted by units) from June, falling back to May
then April. Requires ≥3 units of support in the modal month to guard
against single-sale outliers (which caused the Suraksha gloves ₹732
anomaly).

Excludes drug_ids in EXCLUDED_DRUG_IDS.

Run standalone:
    .venv/bin/python "Price Live/build_old_prices.py"

Or as part of the combined refresh:
    from build_old_prices import refresh_old_prices
    refresh_old_prices()
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _shared import _connect  # noqa: E402

OLD_PRICE_CSV = HERE / "drug_old_selling_price.csv"

# Pilot stores (same list as refresh_dashboard_data.py). Pre-July, these
# stores got hiked on 2026-05-06, so their prices are NOT valid old prices.
PILOT_SQL = """(
       "store-name" IN ('Colaba','Khanda Colony','Bhiwandi Dhamankar Naka','Khar West',
                        'Goregaon West S.V. Road','Sanpada','Goregaon','Bandra')
    OR "store-name" ILIKE '%%dighi%%'
    OR "store-name" ILIKE '%%sasane%%'
    OR "store-name" ILIKE '%%chinchwad%%'
)"""

FRANCHISEE_ID = 1
EXCLUDED_DRUG_IDS = (632426,)  # Suraksha Latex gloves — bad price history

# ≥ this many units must sit at the modal rate in a month for us to trust it
MIN_UNITS_SUPPORT = 3

FALLBACK_MONTHS = ["2026-06-01", "2026-05-01", "2026-04-01"]  # first is preferred


def refresh_old_prices() -> pd.DataFrame:
    excluded_sql = ", ".join(str(x) for x in EXCLUDED_DRUG_IDS) or "0"
    Q = f"""
    WITH src AS (
        SELECT "drug-id" AS drug_id,
               DATE_TRUNC('month', "created-at"::date)::date AS month,
               "rate" AS rate,
               SUM("net-quantity") AS units
        FROM "prod2-generico"."sales"
        WHERE "bill-flag" = 'gross'
          AND "net-quantity" > 0
          AND "drug-id" IS NOT NULL
          AND "drug-id" NOT IN ({excluded_sql})
          AND "franchisee-id" = {FRANCHISEE_ID}
          AND NOT {PILOT_SQL}
          AND "created-at"::date BETWEEN DATE '2026-04-01' AND DATE '2026-06-30'
        GROUP BY 1, 2, 3
    ),
    ranked AS (
        SELECT drug_id, month, rate, units,
               SUM(units) OVER (PARTITION BY drug_id, month) AS month_units,
               ROW_NUMBER() OVER (PARTITION BY drug_id, month
                                   ORDER BY units DESC, rate ASC) AS rn
        FROM src
    ),
    supported AS (
        -- keep only modal rate per (drug × month), and only if the month has enough support
        SELECT drug_id, month, rate AS modal_rate
        FROM ranked
        WHERE rn = 1
          AND month_units >= {MIN_UNITS_SUPPORT}
    )
    SELECT drug_id,
           MAX(CASE WHEN month = DATE '{FALLBACK_MONTHS[0]}' THEN modal_rate END) AS jun,
           MAX(CASE WHEN month = DATE '{FALLBACK_MONTHS[1]}' THEN modal_rate END) AS may,
           MAX(CASE WHEN month = DATE '{FALLBACK_MONTHS[2]}' THEN modal_rate END) AS apr
    FROM supported
    GROUP BY drug_id
    """
    print(f"Querying old prices (franchisee_id={FRANCHISEE_ID}, "
          f"exclude drug_ids={list(EXCLUDED_DRUG_IDS)}, min_support={MIN_UNITS_SUPPORT})…")
    with _connect() as conn:
        df = pd.read_sql(Q, conn)
    print(f"  {len(df):,} drugs returned")

    df["old_selling_price"] = df["jun"].combine_first(df["may"]).combine_first(df["apr"])
    out = df.dropna(subset=["old_selling_price"])[["drug_id", "old_selling_price"]].copy()
    out["drug_id"] = out["drug_id"].astype(int)

    # Diagnostics
    n_jun = int(df["jun"].notna().sum())
    n_may_fallback = int((df["jun"].isna() & df["may"].notna()).sum())
    n_apr_fallback = int((df["jun"].isna() & df["may"].isna() & df["apr"].notna()).sum())
    n_missing = int((df["jun"].isna() & df["may"].isna() & df["apr"].isna()).sum())

    out.to_csv(OLD_PRICE_CSV, index=False)
    print(f"→ {OLD_PRICE_CSV.name}: {len(out):,} drugs")
    print(f"    baseline from June     : {n_jun:,}")
    print(f"    baseline from May      : {n_may_fallback:,}")
    print(f"    baseline from April    : {n_apr_fallback:,}")
    print(f"    no baseline (dropped)  : {n_missing:,}")
    return out


if __name__ == "__main__":
    refresh_old_prices()
