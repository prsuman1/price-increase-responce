"""Refresh data for the Price Live impact dashboard.

Pulls chain-wide sales for two day-aligned windows —
  PRE  : 2026-06-01 -> 2026-06-<N>   (baseline, before chain-wide go-live)
  POST : 2026-07-01 -> 2026-07-<N>   (new prices live at all stores)
where N = yesterday's day-of-month (windows grow daily) — computes all
dashboard metrics and writes small CSVs + meta.json into `Price Live/data/`.

Gain definitions (on post-window sales):
  gain_rev = (rate - old_selling_price) * units                        per line
  gain_rgm = (rate - current_unit_cogs)*units
             - (old_selling_price - old_unit_cogs)*units               per line
             i.e. change in unit margin x units, capturing COGS movement too.
Old price reference: Price Live/drug_old_selling_price.csv (pre-July modal
rate at non-pilot stores). Old unit COGS = pre-window (June) unit purchase
rate per drug at non-pilot stores; when missing, current unit COGS is used
(so gain_rgm falls back to gain_rev for that line). Drugs without an old
price are excluded from gain (counted in meta.json).

Run (VPN required):
    .venv/bin/python "Price Live/refresh_dashboard_data.py"
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from _shared import _connect, ASSORTMENT_GENERIC, ASSORTMENT_ETHICAL  # noqa: E402

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
DATA_DIR.mkdir(exist_ok=True)
OLD_PRICE_CSV = HERE / "drug_old_selling_price.csv"

# ---- windows (day-of-month aligned, complete days only) ---------------------
today = date.today()
N = min((today - timedelta(days=1)).day, 30) if today.month == 7 else 30
PRE_START, PRE_END = date(2026, 6, 1), date(2026, 6, N)
POST_START, POST_END = date(2026, 7, 1), date(2026, 7, N)
print(f"PRE  {PRE_START} -> {PRE_END}\nPOST {POST_START} -> {POST_END}")

PILOT_SQL = """(
       "store-name" IN ('Colaba','Khanda Colony','Bhiwandi Dhamankar Naka','Khar West',
                        'Goregaon West S.V. Road','Sanpada','Goregaon','Bandra')
    OR "store-name" ILIKE '%%dighi%%'
    OR "store-name" ILIKE '%%sasane%%'
    OR "store-name" ILIKE '%%chinchwad%%'
)"""

# --- Scope filters -----------------------------------------------------------
# Franchisee 1 = chain-owned stores. Other franchisees look at their numbers
# separately. Keep here as a hard constant; if we ever need to compare, wire
# a picker on top.
FRANCHISEE_ID = 1
# Drugs to exclude entirely (data errors that pollute gain math).
# Add drug_ids here and rerun — one-line change.
EXCLUDED_DRUG_IDS = (632426,)  # Suraksha Latex gloves — bad price history

_FRANCHISE_SQL = f'AND "franchisee-id" = {FRANCHISEE_ID}'
_EXCLUDE_SQL   = f'AND "drug-id" NOT IN ({", ".join(str(x) for x in EXCLUDED_DRUG_IDS) or "0"})'

Q_POST = f"""
SELECT "created-at"::date                       AS sale_date,
       "store-name"                             AS store_name,
       CASE WHEN {PILOT_SQL} THEN 1 ELSE 0 END  AS pilot,
       "drug-id"                                AS drug_id,
       MAX("drug-name")                         AS drug_name,
       MAX("assortment-classification-id")      AS assortment_id,
       MAX(UPPER(COALESCE("company", '')))      AS company,
       "rate"                                   AS rate,
       CASE WHEN UPPER(TRIM(COALESCE("promo-code",''))) LIKE 'GENRTN%%'
            THEN 1 ELSE 0 END                   AS is_genrtn,
       SUM("net-quantity")                      AS units,
       SUM("revenue-value")                     AS revenue,
       SUM("purchase-rate" * "net-quantity")    AS cogs,
       SUM(COALESCE("promo-discount", 0))       AS promo_discount,
       COUNT(DISTINCT "bill-id")                AS bills
FROM "prod2-generico"."sales"
WHERE "created-at"::date BETWEEN DATE '{POST_START}' AND DATE '{POST_END}'
  AND "bill-flag" = 'gross'
  AND "drug-id" IS NOT NULL
  {_FRANCHISE_SQL}
  {_EXCLUDE_SQL}
GROUP BY 1, 2, 3, 4, 8, 9
"""

Q_PRE = f"""
SELECT "created-at"::date                       AS sale_date,
       "store-name"                             AS store_name,
       CASE WHEN {PILOT_SQL} THEN 1 ELSE 0 END  AS pilot,
       "drug-id"                                AS drug_id,
       MAX("assortment-classification-id")      AS assortment_id,
       MAX(UPPER(COALESCE("company", '')))      AS company,
       SUM("net-quantity")                      AS units,
       SUM("revenue-value")                     AS revenue,
       SUM("purchase-rate" * "net-quantity")    AS cogs
FROM "prod2-generico"."sales"
WHERE "created-at"::date BETWEEN DATE '{PRE_START}' AND DATE '{PRE_END}'
  AND "bill-flag" = 'gross'
  AND "drug-id" IS NOT NULL
  {_FRANCHISE_SQL}
  {_EXCLUDE_SQL}
GROUP BY 1, 2, 3, 4
"""

Q_FREQ = f"""
SELECT CASE WHEN "created-at"::date >= DATE '{POST_START}' THEN 'post' ELSE 'pre' END AS window,
       "store-name"                             AS store_name,
       CASE WHEN {PILOT_SQL} THEN 1 ELSE 0 END  AS pilot,
       COUNT(DISTINCT "bill-id")                AS bills,
       COUNT(DISTINCT "patient-id")             AS patients
FROM "prod2-generico"."sales"
WHERE ("created-at"::date BETWEEN DATE '{PRE_START}' AND DATE '{PRE_END}'
    OR "created-at"::date BETWEEN DATE '{POST_START}' AND DATE '{POST_END}')
  AND "bill-flag" = 'gross'
  {_FRANCHISE_SQL}
GROUP BY 1, 2, 3
"""

Q_FREQ_CHAIN = f"""
SELECT CASE WHEN "created-at"::date >= DATE '{POST_START}' THEN 'post' ELSE 'pre' END AS window,
       CASE WHEN {PILOT_SQL} THEN 1 ELSE 0 END  AS pilot,
       COUNT(DISTINCT "bill-id")                AS bills,
       COUNT(DISTINCT "patient-id")             AS patients
FROM "prod2-generico"."sales"
WHERE ("created-at"::date BETWEEN DATE '{PRE_START}' AND DATE '{PRE_END}'
    OR "created-at"::date BETWEEN DATE '{POST_START}' AND DATE '{POST_END}')
  AND "bill-flag" = 'gross'
  {_FRANCHISE_SQL}
GROUP BY 1, 2
"""

# Store → franchisee lookup (used to filter surveys, and for reference)
Q_STORE_FRANCHISEE = f"""
SELECT DISTINCT "store-name" AS store_name,
                "franchisee-id" AS franchisee_id
FROM "prod2-generico"."sales"
WHERE "created-at"::date >= DATE '{PRE_START}'
  AND "store-name" IS NOT NULL
  AND "franchisee-id" IS NOT NULL
"""

# --- rebuild old-price baselines first (so downstream gain uses fresh CSV) ---
print("\n[0/4] Rebuilding old-price baselines…")
from build_old_prices import refresh_old_prices  # noqa: E402
refresh_old_prices()
print()

with _connect() as conn:
    print("Querying POST lines ...")
    post = pd.read_sql(Q_POST, conn)
    print(f"  {len(post):,} rows")
    print("Querying PRE lines ...")
    pre = pd.read_sql(Q_PRE, conn)
    print(f"  {len(pre):,} rows")
    print("Querying frequency ...")
    freq = pd.read_sql(Q_FREQ, conn)
    freq_chain = pd.read_sql(Q_FREQ_CHAIN, conn)
    print("Querying store → franchisee lookup ...")
    store_franchisee = pd.read_sql(Q_STORE_FRANCHISEE, conn)
    print(f"  {len(store_franchisee):,} store-franchisee pairs")

store_franchisee["franchisee_id"] = pd.to_numeric(store_franchisee["franchisee_id"], errors="coerce").astype("Int64")
store_franchisee.to_csv(DATA_DIR / "store_franchisee.csv", index=False)

for df in (post, pre):
    for c in ("units", "revenue", "cogs"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
post["rate"] = pd.to_numeric(post["rate"], errors="coerce")
post["promo_discount"] = pd.to_numeric(post["promo_discount"], errors="coerce").fillna(0.0)

# ---- segment (GA / NGA / Ethical / Other) -----------------------------------
def segment(df: pd.DataFrame) -> pd.Series:
    a = pd.to_numeric(df["assortment_id"], errors="coerce")
    seg = pd.Series("Other", index=df.index)
    seg[a.isin(ASSORTMENT_ETHICAL)] = "Ethical"
    generic = a.isin(ASSORTMENT_GENERIC)
    seg[generic] = np.where(df.loc[generic, "company"].eq("GOODAID"), "GA", "NGA")
    return seg

post["segment"] = segment(post)
pre["segment"] = segment(pre)

# ---- gain (post only) ---------------------------------------------------------
old = pd.read_csv(OLD_PRICE_CSV).set_index("drug_id")["old_selling_price"]
post["old_price"] = post["drug_id"].map(old)
has_old = post["old_price"].notna()
post["gain_rev"] = np.where(has_old, (post["rate"] - post["old_price"]) * post["units"], np.nan)

# old unit COGS per drug: pre-window (June) purchase rate at non-pilot stores
pre_np_cogs = pre[pre["pilot"] == 0].groupby("drug_id")[["cogs", "units"]].sum()
old_unit_cogs = (pre_np_cogs["cogs"] / pre_np_cogs["units"]).replace([np.inf, -np.inf], np.nan)
post["old_unit_cogs"] = post["drug_id"].map(old_unit_cogs)
has_old_cogs = post["old_unit_cogs"].notna()

# gain_rgm = (rate*units - cogs) - (old_price - old_unit_cogs)*units
# fallback when old COGS unknown: assume COGS unchanged -> gain_rgm = gain_rev
post["gain_rgm"] = np.where(
    has_old & has_old_cogs,
    (post["rate"] * post["units"] - post["cogs"])
    - (post["old_price"] - post["old_unit_cogs"]) * post["units"],
    post["gain_rev"],
)
post["genrtn_giveback"] = np.where(post["is_genrtn"] == 1, post["promo_discount"], 0.0)

# per-drug modal post rate -> price direction
g = (post[has_old].groupby(["drug_id", "rate"])["units"].sum().reset_index())
modal = g.loc[g.groupby("drug_id")["units"].idxmax()].set_index("drug_id")["rate"]
chg = 100 * (modal / old.reindex(modal.index) - 1)
direction = pd.Series("flat", index=modal.index)
direction[chg > 0.5] = "increased"
direction[chg < -0.5] = "decreased"
post["direction"] = post["drug_id"].map(direction).fillna("unknown")

gp = post[has_old]

# ---- outputs ------------------------------------------------------------------
# 1. daily gain by direction
daily_gain = (gp.groupby(["sale_date", "direction"])
                .agg(gain_rev=("gain_rev", "sum"), gain_rgm=("gain_rgm", "sum"),
                     units=("units", "sum"))
                .reset_index())
daily_gain.to_csv(DATA_DIR / "daily_gain.csv", index=False)

# 2. daily x store gain by direction
daily_store_gain = (gp.groupby(["sale_date", "store_name", "pilot", "direction"])
                      .agg(gain_rev=("gain_rev", "sum"), gain_rgm=("gain_rgm", "sum"))
                      .reset_index())
daily_store_gain.to_csv(DATA_DIR / "daily_store_gain.csv", index=False)

# 3. per-drug gain
drug_gain = (gp.groupby(["drug_id", "direction", "segment"])
               .agg(drug_name=("drug_name", "first"),
                    units_post=("units", "sum"),
                    gain_rev=("gain_rev", "sum"),
                    gain_rgm=("gain_rgm", "sum"),
                    revenue_post=("revenue", "sum"))
               .reset_index())
drug_gain["old_price"] = drug_gain["drug_id"].map(old)
drug_gain["new_price"] = drug_gain["drug_id"].map(modal)
drug_gain.to_csv(DATA_DIR / "drug_gain.csv", index=False)

# 4. GENRTN store x drug
genrtn = post[post["is_genrtn"] == 1]
genrtn_sd = (genrtn.groupby(["store_name", "pilot", "drug_id"])
                   .agg(drug_name=("drug_name", "first"), units=("units", "sum"),
                        bills=("bills", "sum"), giveback=("promo_discount", "sum"))
                   .reset_index())
genrtn_sd.to_csv(DATA_DIR / "genrtn_store_drug.csv", index=False)

# 5. qty change: per window x direction x pilot (drug direction mapped onto pre too)
pre["direction"] = pre["drug_id"].map(direction).fillna("unknown")
qty = pd.concat([
    pre.assign(window="pre").groupby(["window", "direction", "pilot"])["units"].sum().reset_index(),
    post.assign(window="post").groupby(["window", "direction", "pilot"])["units"].sum().reset_index(),
])
qty.to_csv(DATA_DIR / "qty_change.csv", index=False)

# daily units trend (both windows)
daily_units = pd.concat([
    pre.groupby(["sale_date", "pilot"])["units"].sum().reset_index().assign(window="pre"),
    post.groupby(["sale_date", "pilot"])["units"].sum().reset_index().assign(window="post"),
])
daily_units.to_csv(DATA_DIR / "daily_units.csv", index=False)

# 6. substitution: window x store x segment units
subst = pd.concat([
    pre.assign(window="pre").groupby(["window", "store_name", "pilot", "segment"])["units"].sum().reset_index(),
    post.assign(window="post").groupby(["window", "store_name", "pilot", "segment"])["units"].sum().reset_index(),
])
subst.to_csv(DATA_DIR / "substitution.csv", index=False)

# 7. GM% inputs: window x store revenue/cogs
gm = pd.concat([
    pre.assign(window="pre").groupby(["window", "store_name", "pilot"])[["revenue", "cogs"]].sum().reset_index(),
    post.assign(window="post").groupby(["window", "store_name", "pilot"])[["revenue", "cogs"]].sum().reset_index(),
])
gm.to_csv(DATA_DIR / "gm_store.csv", index=False)

# 8. frequency
freq.to_csv(DATA_DIR / "freq_store.csv", index=False)
freq_chain.to_csv(DATA_DIR / "freq_chain.csv", index=False)

# 9. meta
no_old = post[~has_old]
meta = {
    "refreshed_at": datetime.now().isoformat(timespec="seconds"),
    "franchisee_id": FRANCHISEE_ID,
    "excluded_drug_ids": list(EXCLUDED_DRUG_IDS),
    "pre_window": [PRE_START.isoformat(), PRE_END.isoformat()],
    "post_window": [POST_START.isoformat(), POST_END.isoformat()],
    "post_rows": int(len(post)),
    "stores": int(post["store_name"].nunique()),
    "drugs_post": int(post["drug_id"].nunique()),
    "drugs_no_old_price": int(no_old["drug_id"].nunique()),
    "units_share_no_old_price_pct": round(float(100 * no_old["units"].sum() / post["units"].sum()), 2),
    "drugs_no_old_cogs": int(post.loc[has_old & ~has_old_cogs, "drug_id"].nunique()),
    "direction_counts": direction.value_counts().to_dict(),
    "total_gain_rev": round(float(gp["gain_rev"].sum()), 0),
    "total_gain_rgm": round(float(gp["gain_rgm"].sum()), 0),
    "genrtn_bills": int(genrtn["bills"].sum()),
    "genrtn_units": float(genrtn["units"].sum()),
    "genrtn_giveback": round(float(genrtn["promo_discount"].sum()), 0),
}
(DATA_DIR / "meta.json").write_text(json.dumps(meta, indent=2))

print("\n--- meta ---")
print(json.dumps(meta, indent=2))
print(f"\nWrote {len(list(DATA_DIR.iterdir()))} files to {DATA_DIR}")

# ---- survey sheets (chain-wide surveyor rotation) ---------------------------
print("\nRefreshing survey sheets (8 Google Sheets)...")
try:
    from survey_ingest import refresh_survey
    refresh_survey()
except Exception as e:
    print(f"⚠️  Survey refresh failed: {e}")
    print("   (impact-side data is fine; re-run `.venv/bin/python \"Price Live/survey_ingest.py\"` to retry)")
