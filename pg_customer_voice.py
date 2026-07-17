"""Price Live — Customer Voice page.

Renders the 8 surveyor sheets (chain-wide price hike, Jul 1+) with:
  1. Hero KPIs
  2. Daily trend (stacked by RAG)
  3. Store × RAG heatmap
  4. Reaction fingerprint (top phrases)
  5. Voice-of-customer (notes on amber/red bills)
  6. Surveyor coverage table
"""
from __future__ import annotations

from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
SURVEY_CSV = DATA / "survey.csv"

# Palette (matches pg_impact.py)
INK = "#0b0b0b"; INK2 = "#52514e"; MUTED = "#898781"
GRID = "#e1e0d9"; SURFACE = "#fcfcfb"
GREEN = "#2ECC71"; AMBER = "#F39C12"; RED = "#E74C3C"
RAG_COLORS = {"green": GREEN, "amber": AMBER, "red": RED}
RAG_ORDER = ["green", "amber", "red"]
RAG_LABEL = {"green": "🟢 Accepted", "amber": "🟡 Pushback", "red": "🔴 Walked away"}

st.markdown("""
<style>
@keyframes rise { from {opacity:0; transform:translateY(10px);} to {opacity:1; transform:none;} }
.section-h {
  animation: rise .5s ease both;
  font-size: 1.35rem; font-weight: 700; color: #0b0b0b;
  border-left: 4px solid #2a78d6; padding-left: .6rem;
  margin: 1.8rem 0 .2rem 0;
}
.section-sub { color:#52514e; font-size:.9rem; margin: 0 0 .6rem .95rem; animation: rise .6s ease both; }
div[data-testid="stMetric"] { background:#fcfcfb; border:1px solid rgba(11,11,11,.10);
  border-radius:12px; padding:.6rem .9rem; animation: rise .5s ease both; }
.quote-card { background:#fcfcfb; border-left:4px solid #F39C12;
  padding:.7rem 1rem; margin:.4rem 0; border-radius:0 8px 8px 0;
  font-size:.95rem; color:#0b0b0b; }
.quote-card.red { border-left-color: #E74C3C; }
.quote-meta { color:#898781; font-size:.8rem; margin-top:.3rem; }
</style>
""", unsafe_allow_html=True)


def section(title: str, sub: str = "") -> None:
    st.markdown(f'<div class="section-h">{title}</div>', unsafe_allow_html=True)
    if sub:
        st.markdown(f'<div class="section-sub">{sub}</div>', unsafe_allow_html=True)


@st.cache_data(ttl=300)
def load_survey() -> pd.DataFrame:
    if not SURVEY_CSV.exists():
        return pd.DataFrame()
    df = pd.read_csv(SURVEY_CSV)
    df["submitted_at"] = pd.to_datetime(df["submitted_at"], errors="coerce")
    df["submitted_date"] = df["submitted_at"].dt.date
    df["store"] = df["store"].astype(str).str.strip()
    for c in ("staff_informed", "spoke_price", "checked_bill", "nonverbal",
              "reaction_type", "what_said", "outcome", "notes"):
        if c in df.columns:
            df[c] = df[c].fillna("").astype(str)
    if "is_amber_partial" in df.columns:
        df["is_amber_partial"] = df["is_amber_partial"].fillna(False).astype(bool)
    if "is_amber_genrtn" in df.columns:
        df["is_amber_genrtn"] = df["is_amber_genrtn"].fillna(False).astype(bool)
    return df


df = load_survey()

st.title("💬 Customer Voice — chain-wide")
st.caption(
    "Field surveyors sit at store counters and log each customer's reaction to the "
    "chain-wide price hike (2026-07-01 →). Each row = one billed customer. "
    "Rotating across stores; 8 surveyors."
)

if df.empty:
    st.warning(
        "No survey data yet. Run `.venv/bin/python \"Price Live/survey_ingest.py\"` "
        "(or the combined `refresh_dashboard_data.py`) to pull the 8 Google Sheets."
    )
    st.stop()

# --------------------------- filters ---------------------------
st.sidebar.header("Filters")
date_min = df["submitted_date"].min()
date_max = df["submitted_date"].max()
d1, d2 = st.sidebar.columns(2)
from_date = d1.date_input("From", value=date_min, min_value=date_min, max_value=date_max)
to_date = d2.date_input("To", value=date_max, min_value=date_min, max_value=date_max)

surveyors_all = sorted(df["surveyor"].dropna().unique().tolist())
sel_surveyors = st.sidebar.multiselect("Surveyors", surveyors_all, default=surveyors_all)

stores_all = sorted(df["store"].dropna().unique().tolist())
sel_stores = st.sidebar.multiselect("Stores", stores_all, default=[])
if not sel_stores:
    sel_stores = stores_all

view = df[
    (df["submitted_date"] >= from_date)
    & (df["submitted_date"] <= to_date)
    & (df["surveyor"].isin(sel_surveyors))
    & (df["store"].isin(sel_stores))
].copy()

if view.empty:
    st.warning("No rows for the current filter selection.")
    st.stop()

# --------------------------- 1. Hero KPIs ---------------------------
n_total = len(view)
n_stores = view["store"].nunique()
n_green = int((view["rag"] == "green").sum())
n_amber = int((view["rag"] == "amber").sum())
n_red = int((view["rag"] == "red").sum())
pct_green = 100 * n_green / n_total if n_total else 0
pct_pushback = 100 * (n_amber + n_red) / n_total if n_total else 0

c1, c2, c3, c4 = st.columns(4)
c1.metric("Surveys captured", f"{n_total:,}")
c2.metric("Stores covered", f"{n_stores:,}")
c3.metric("🟢 Accepted (green)", f"{pct_green:.1f}%", f"{n_green:,} bills")
c4.metric("🟡🔴 Pushback (amber + red)", f"{pct_pushback:.1f}%", f"{n_amber + n_red:,} bills")

st.caption(
    f"Window {from_date} → {to_date} · {len(sel_surveyors)}/8 surveyors · "
    f"{len(sel_stores)}/{len(stores_all)} stores selected"
)

# --------------------------- 2. Daily trend ---------------------------
section("📅 Daily surveys by outcome",
        "Volume rhythm and pushback share since chain-wide go-live.")

daily = (view.groupby(["submitted_date", "rag"]).size()
             .reset_index(name="n"))
daily["submitted_date"] = pd.to_datetime(daily["submitted_date"])
trend = alt.Chart(daily).mark_area(opacity=0.85).encode(
    x=alt.X("submitted_date:T", title=None, axis=alt.Axis(format="%d %b", labelColor=INK2, tickColor=GRID, domainColor=GRID)),
    y=alt.Y("n:Q", title="Surveys", stack="zero", axis=alt.Axis(labelColor=INK2, tickColor=GRID, domainColor=GRID, gridColor=GRID)),
    color=alt.Color("rag:N", scale=alt.Scale(domain=RAG_ORDER, range=[GREEN, AMBER, RED]),
                    legend=alt.Legend(orient="top", title=None)),
    tooltip=[alt.Tooltip("submitted_date:T", title="Date", format="%d %b %Y"),
             alt.Tooltip("rag:N", title="Outcome"),
             alt.Tooltip("n:Q", title="Surveys")],
).properties(height=260, background=SURFACE)
st.altair_chart(trend, use_container_width=True)

# --------------------------- 3. Store × RAG heatmap ---------------------------
section("🏪 Store × outcome",
        "Where is pushback concentrated? Top 20 stores by survey volume.")

by_store = view.groupby("store").agg(
    surveys=("rag", "size"),
    green=("rag", lambda s: (s == "green").sum()),
    amber=("rag", lambda s: (s == "amber").sum()),
    red=("rag", lambda s: (s == "red").sum()),
).reset_index()
by_store["pushback_pct"] = 100 * (by_store["amber"] + by_store["red"]) / by_store["surveys"]
by_store = by_store.sort_values("surveys", ascending=False).head(20).reset_index(drop=True)

st.dataframe(
    by_store,
    use_container_width=True,
    hide_index=True,
    column_config={
        "store": st.column_config.Column("Store", pinned=True),
        "surveys": st.column_config.NumberColumn("Surveys", format="%d"),
        "green": st.column_config.NumberColumn("🟢 Accepted", format="%d"),
        "amber": st.column_config.NumberColumn("🟡 Partial", format="%d"),
        "red": st.column_config.NumberColumn("🔴 Walkaway", format="%d"),
        "pushback_pct": st.column_config.ProgressColumn(
            "Pushback %", format="%.1f%%", min_value=0, max_value=max(20, float(by_store["pushback_pct"].max() or 20))),
    },
)

# --------------------------- 4. Reaction fingerprint ---------------------------
section("🎯 Reaction fingerprint",
        "What are customers actually saying? Top phrases from the multi-select "
        "'reactions' column, split by outcome.")

def explode_multi(col: pd.Series) -> pd.Series:
    return (col.fillna("").astype(str)
              .str.split(",")
              .explode()
              .str.strip()
              .replace("", pd.NA)
              .dropna())

reaction_rows: list[dict] = []
for rag_val in ("green", "amber", "red"):
    sub = view[view["rag"] == rag_val]
    if sub.empty:
        continue
    exploded = explode_multi(sub["reaction_type"])
    for phrase, n in exploded.value_counts().head(10).items():
        reaction_rows.append({"rag": rag_val, "phrase": phrase, "n": int(n)})

if reaction_rows:
    rx = pd.DataFrame(reaction_rows)
    chart = alt.Chart(rx).mark_bar().encode(
        y=alt.Y("phrase:N", sort="-x", title=None, axis=alt.Axis(labelColor=INK, labelLimit=280)),
        x=alt.X("n:Q", title="Mentions", axis=alt.Axis(labelColor=INK2, tickColor=GRID, domainColor=GRID, gridColor=GRID)),
        color=alt.Color("rag:N", scale=alt.Scale(domain=RAG_ORDER, range=[GREEN, AMBER, RED]),
                        legend=alt.Legend(orient="top", title=None)),
        row=alt.Row("rag:N", sort=RAG_ORDER, header=alt.Header(title=None, labelColor=INK)),
        tooltip=["phrase:N", "n:Q", "rag:N"],
    ).properties(width=560, height=180, background=SURFACE)
    st.altair_chart(chart, use_container_width=True)
else:
    st.info("No reactions recorded in this filter window.")

# --------------------------- 5. Voice of customer ---------------------------
section("🗣️ Voice of customer — pushback quotes",
        "Free-text notes surveyors wrote on amber/red bills. Verbatim (Hindi/Hinglish).")

quotes = view[(view["rag"].isin(("amber", "red"))) & (view["notes"].str.len() > 5)].copy()
quotes = quotes.sort_values("submitted_at", ascending=False).head(20)

if quotes.empty:
    st.info("No pushback notes in the current window.")
else:
    for _, r in quotes.iterrows():
        cls = "red" if r["rag"] == "red" else ""
        meta = f"{r['store']} · {r['submitted_date']} · {r['surveyor']} · {RAG_LABEL[r['rag']]}"
        st.markdown(
            f'<div class="quote-card {cls}">"{r["notes"].strip()}"<div class="quote-meta">{meta}</div></div>',
            unsafe_allow_html=True,
        )

# --------------------------- 6. Surveyor coverage ---------------------------
section("👥 Surveyor coverage",
        "Who logged what, and how much of it was pushback.")

by_surveyor = view.groupby("surveyor").agg(
    surveys=("rag", "size"),
    stores=("store", "nunique"),
    green=("rag", lambda s: (s == "green").sum()),
    amber=("rag", lambda s: (s == "amber").sum()),
    red=("rag", lambda s: (s == "red").sum()),
    first=("submitted_date", "min"),
    last=("submitted_date", "max"),
).reset_index()
by_surveyor["pushback_pct"] = 100 * (by_surveyor["amber"] + by_surveyor["red"]) / by_surveyor["surveys"]
by_surveyor = by_surveyor.sort_values("surveys", ascending=False).reset_index(drop=True)

st.dataframe(
    by_surveyor,
    use_container_width=True,
    hide_index=True,
    column_config={
        "surveyor": st.column_config.Column("Surveyor", pinned=True),
        "surveys": st.column_config.NumberColumn("Surveys", format="%d"),
        "stores": st.column_config.NumberColumn("Stores", format="%d"),
        "green": st.column_config.NumberColumn("🟢", format="%d"),
        "amber": st.column_config.NumberColumn("🟡", format="%d"),
        "red": st.column_config.NumberColumn("🔴", format="%d"),
        "first": st.column_config.DateColumn("First"),
        "last": st.column_config.DateColumn("Last"),
        "pushback_pct": st.column_config.ProgressColumn(
            "Pushback %", format="%.1f%%", min_value=0,
            max_value=max(20, float(by_surveyor["pushback_pct"].max() or 20))),
    },
)

st.download_button(
    "📥 Download all filtered surveys (CSV)",
    data=view.to_csv(index=False).encode("utf-8"),
    file_name=f"customer_voice_{from_date}_{to_date}.csv",
    mime="text/csv",
)
