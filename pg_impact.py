"""Price Live — chain-wide go-live impact dashboard (Impact page)."""
from __future__ import annotations

import json
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"

# ---------- palette (validated dataviz defaults, light surface) ----------
INK = "#0b0b0b"; INK2 = "#52514e"; MUTED = "#898781"
GRID = "#e1e0d9"; SURFACE = "#fcfcfb"
GOOD = "#0ca30c"; BAD = "#d03b3b"; GOOD_TEXT = "#006300"
BLUE = "#2a78d6"; AQUA = "#1baf7a"; YELLOW = "#eda100"; VIOLET = "#4a3aa7"
DIV_NEG, DIV_MID, DIV_POS = "#d03b3b", "#f0efec", "#2a78d6"
SEG_COLORS = {"GA": BLUE, "NGA": AQUA, "Ethical": YELLOW, "Other": MUTED}
SEG_ORDER = ["GA", "NGA", "Ethical", "Other"]

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
</style>
""", unsafe_allow_html=True)

# ---------- helpers ----------
def inr_group(n: float) -> str:
    """Indian comma grouping: 1,87,938."""
    n = int(round(n)); sign = "-" if n < 0 else ""; s = str(abs(n))
    if len(s) <= 3: return sign + s
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:]); head = head[:-2]
    if head: parts.insert(0, head)
    return sign + ",".join(parts) + "," + tail

def lakh(v: float, signed: bool = True) -> str:
    s = "+" if (signed and v >= 0) else ""
    return f"{s}₹{v/1e5:,.2f} L"

@st.cache_data(ttl=300)
def load():
    d = {p.stem: pd.read_csv(p) for p in DATA.glob("*.csv")}
    meta = json.loads((DATA / "meta.json").read_text())
    for k in ("daily_gain", "daily_store_gain", "daily_units"):
        if k in d: d[k]["sale_date"] = pd.to_datetime(d[k]["sale_date"])
    return d, meta

if not (DATA / "meta.json").exists():
    st.error("No data yet — run `.venv/bin/python \"Price Live/refresh_dashboard_data.py\"` on VPN first.")
    st.stop()
d, meta = load()

PRE_LB = f"{meta['pre_window'][0]} → {meta['pre_window'][1]}"
POST_LB = f"{meta['post_window'][0]} → {meta['post_window'][1]}"
DIR_LABEL = {"increased": "Price ↑", "decreased": "Price ↓", "flat": "Flat", "unknown": "No old price"}

# ---------- sidebar ----------
with st.sidebar:
    st.markdown("### ⚡ Price Live")
    st.caption(f"Chain-wide go-live **2026-07-01**\n\nPre `{PRE_LB}`\n\nPost `{POST_LB}`\n\nRefreshed `{meta['refreshed_at']}`")
    all_stores = sorted(d["daily_store_gain"]["store_name"].unique())
    store_sel = st.multiselect("Stores (store-level sections)", all_stores, default=[])
    excl_pilot = st.toggle("Exclude 11 pilot stores from pre/post baselines", value=True,
                           help="Pilot stores already had new prices in June, so they contaminate the pre baseline for Qty / Substitution / GM% / Frequency. Gain sections always include all stores.")
    with st.expander("📖 Definitions"):
        st.markdown(f"""
- **Additional Revenue (gain)** = (current selling price − old selling price) × units, on post-window sales. Old price = pre-July modal rate at non-pilot stores. +ve or −ve per drug.
- **Additional RGM** = [(current selling price − current COGS) − (old selling price − old COGS)] × units — the change in unit margin, so purchase-rate movement counts too. Old COGS = June unit purchase rate per drug at non-pilot stores (falls back to current COGS when missing).
- **Price direction** — per drug, modal post rate vs old price (±0.5% threshold) → Price ↑ / Price ↓ / Flat.
- **Substitution %** = Generic units (GA+NGA) ÷ total units. GA = company `GOODAID`; NGA = other generics; Ethical = assortment 1–2.
- **GM %** = (revenue − COGS) / revenue, as-billed.
- **Frequency** = bills ÷ distinct patients, per window.
- {meta['drugs_no_old_price']:,} drugs ({meta['units_share_no_old_price_pct']}% of units) have no old-price reference and are excluded from gain.
""")

def filt_stores(df: pd.DataFrame) -> pd.DataFrame:
    return df if not store_sel else df[df["store_name"].isin(store_sel)]

def filt_pilot(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["pilot"] == 0] if excl_pilot else df

# ---------- hero ----------
n_up = meta["direction_counts"].get("increased", 0)
n_dn = meta["direction_counts"].get("decreased", 0)
hero_cards = [
    ("Additional Revenue", meta["total_gain_rev"] / 1e5, "L", GOOD_TEXT if meta["total_gain_rev"] >= 0 else BAD),
    ("Additional RGM", meta["total_gain_rgm"] / 1e5, "L", GOOD_TEXT if meta["total_gain_rgm"] >= 0 else BAD),
    ("Drugs repriced ↑ / ↓", None, f"{inr_group(n_up)} / {inr_group(n_dn)}", INK),
    ("GENRTN bills", None, inr_group(meta["genrtn_bills"]), INK),
]
cards_html = "".join(
    f"""<div class="card"><div class="lbl">{lbl}</div>
        <div class="val" {'data-target="%.2f" data-suffix=" L" data-prefix="₹"' % v if v is not None else ''}
             style="color:{color}">{txt if v is None else '0'}</div></div>"""
    for lbl, v, txt, color in [(l, v, (s if v is None else ""), c) for l, v, s, c in hero_cards]
)
components.html(f"""
<style>
  * {{ font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }}
  .hero {{ background: linear-gradient(120deg,#0d1b2e 0%,#173c6b 60%,#1c5cab 100%);
          border-radius: 16px; padding: 22px 26px 18px; color: #fff; }}
  .hero h1 {{ margin: 0 0 2px; font-size: 24px; font-weight: 750; }}
  .hero .sub {{ color: #b7d3f6; font-size: 13px; margin-bottom: 16px; }}
  .badge {{ display:inline-block; background:#0ca30c22; border:1px solid #0ca30c88; color:#7be27b;
           font-size:11px; padding:2px 10px; border-radius:99px; margin-left:10px; vertical-align:3px;}}
  .row {{ display:flex; gap:14px; flex-wrap:wrap; }}
  .card {{ flex:1 1 180px; background:rgba(252,252,251,.07); border:1px solid rgba(255,255,255,.14);
          border-radius:12px; padding:12px 16px; opacity:0; animation:fade .6s ease forwards; }}
  .card:nth-child(2){{animation-delay:.12s}} .card:nth-child(3){{animation-delay:.24s}} .card:nth-child(4){{animation-delay:.36s}}
  .card .lbl {{ font-size:12px; color:#9ec5f4; margin-bottom:4px; }}
  .card .val {{ font-size:26px; font-weight:750; color:#fff !important; }}
  @keyframes fade {{ from{{opacity:0; transform:translateY(8px)}} to{{opacity:1; transform:none}} }}
</style>
<div class="hero">
  <h1>Price Live — Impact Dashboard <span class="badge">LIVE chain-wide since 1 Jul 2026</span></h1>
  <div class="sub">Gain vs old prices · post window {POST_LB} · baseline {PRE_LB} · {meta['stores']} stores · franchisee_id={meta.get('franchisee_id', '?')} only</div>
  <div class="row">{cards_html}</div>
</div>
<script>
  document.querySelectorAll('.val[data-target]').forEach(el => {{
    const target = parseFloat(el.dataset.target), pre = el.dataset.prefix||'', suf = el.dataset.suffix||'';
    const t0 = performance.now(), dur = 1100;
    function tick(t) {{
      const p = Math.min((t - t0)/dur, 1), e = 1 - Math.pow(1 - p, 3);
      el.textContent = pre + (target*e).toLocaleString('en-IN',{{minimumFractionDigits:2, maximumFractionDigits:2}}) + suf;
      if (p < 1) requestAnimationFrame(tick);
    }}
    requestAnimationFrame(tick);
  }});
</script>
""", height=190)

def section(title: str, sub: str = ""):
    st.markdown(f'<div class="section-h">{title}</div>', unsafe_allow_html=True)
    if sub: st.markdown(f'<div class="section-sub">{sub}</div>', unsafe_allow_html=True)

AXIS = dict(labelColor=MUTED, titleColor=INK2, gridColor=GRID, domainColor="#c3c2b7", tickColor="#c3c2b7")
def themed(c: alt.Chart) -> alt.Chart:
    return c.configure_axis(**AXIS).configure_view(strokeWidth=0).configure_legend(labelColor=INK2, titleColor=INK2)

# =====================================================================
# §1 GAIN
# =====================================================================
section("1 · Gain — Additional Revenue & RGM",
        "Revenue gain = (current − old price) × units · RGM gain = Δ unit margin × units (COGS movement included)")

scope = st.segmented_control("Gain scope",
        ["Overall", "Positive-impacted prices", "Negative-impacted prices"],
        default="Overall", label_visibility="collapsed") or "Overall"
scope_dirs = {"Overall": ["increased", "decreased", "flat"],
              "Positive-impacted prices": ["increased"],
              "Negative-impacted prices": ["decreased"]}[scope]

dg = d["daily_gain"][d["daily_gain"]["direction"].isin(scope_dirs)]
dg_day = dg.groupby("sale_date")[["gain_rev", "gain_rgm"]].sum().reset_index()
dg_day["cum_rev"] = dg_day["gain_rev"].cumsum()
dg_day["cum_rgm"] = dg_day["gain_rgm"].cumsum()

drug_scope = d["drug_gain"][d["drug_gain"]["direction"].isin(scope_dirs)]
k1, k2, k3, k4 = st.columns(4)
k1.metric("Additional Revenue", lakh(dg["gain_rev"].sum()))
k2.metric("Additional RGM", lakh(dg["gain_rgm"].sum()))
k3.metric("Drugs in scope", inr_group(drug_scope["drug_id"].nunique()))
k4.metric("Avg gain / day", lakh(dg_day["gain_rev"].mean()))

melt = dg_day.melt(id_vars="sale_date", value_vars=["gain_rev", "gain_rgm"],
                   var_name="metric", value_name="gain")
melt["metric"] = melt["metric"].map({"gain_rev": "Additional Revenue", "gain_rgm": "Additional RGM"})
bars = alt.Chart(melt).mark_bar(cornerRadiusEnd=4, width=14).encode(
    x=alt.X("yearmonthdate(sale_date):O", title=None, axis=alt.Axis(format="%d %b", labelAngle=0)),
    y=alt.Y("gain:Q", title="₹ / day"),
    xOffset=alt.XOffset("metric:N"),
    color=alt.Color("metric:N", title=None,
                    scale=alt.Scale(domain=["Additional Revenue", "Additional RGM"], range=[BLUE, AQUA]),
                    legend=alt.Legend(orient="top")),
    tooltip=[alt.Tooltip("sale_date:T", format="%d %b"), "metric:N",
             alt.Tooltip("gain:Q", format=",.0f", title="₹")],
).properties(height=230)

cum = dg_day.melt(id_vars="sale_date", value_vars=["cum_rev", "cum_rgm"], var_name="metric", value_name="cum")
cum["metric"] = cum["metric"].map({"cum_rev": "Additional Revenue", "cum_rgm": "Additional RGM"})
cum_ch = alt.Chart(cum).mark_line(strokeWidth=2, point=alt.OverlayMarkDef(size=64, filled=True)).encode(
    x=alt.X("yearmonthdate(sale_date):O", title=None, axis=alt.Axis(format="%d %b", labelAngle=0)),
    y=alt.Y("cum:Q", title="₹ cumulative"),
    color=alt.Color("metric:N", scale=alt.Scale(domain=["Additional Revenue", "Additional RGM"],
                                                range=[BLUE, AQUA]), legend=None),
    tooltip=[alt.Tooltip("sale_date:T", format="%d %b"), "metric:N",
             alt.Tooltip("cum:Q", format=",.0f", title="₹ cumulative")],
).properties(height=180)

c1, c2 = st.columns(2)
with c1:
    st.markdown("**Date-wise gain**"); st.altair_chart(themed(bars), width="stretch")
with c2:
    st.markdown("**Cumulative gain**"); st.altair_chart(themed(cum_ch), width="stretch")

# --- Date × Store ---
st.markdown("**Date × Store gain**")
dsg = filt_stores(d["daily_store_gain"])
dsg = dsg[dsg["direction"].isin(scope_dirs)]
ds = dsg.groupby(["sale_date", "store_name"])[["gain_rev", "gain_rgm"]].sum().reset_index()
top_stores = (ds.groupby("store_name")["gain_rev"].sum().abs().nlargest(30).index.tolist())
hm = ds[ds["store_name"].isin(top_stores)]
lim = float(hm["gain_rev"].abs().max() or 1)
heat = alt.Chart(hm).mark_rect(stroke=SURFACE, strokeWidth=2).encode(
    x=alt.X("yearmonthdate(sale_date):O", title=None, axis=alt.Axis(format="%d %b", labelAngle=0)),
    y=alt.Y("store_name:N", title=None, sort=top_stores),
    color=alt.Color("gain_rev:Q", title="₹ gain",
                    scale=alt.Scale(domain=[-lim, 0, lim], range=[DIV_NEG, DIV_MID, DIV_POS])),
    tooltip=["store_name:N", alt.Tooltip("sale_date:T", format="%d %b"),
             alt.Tooltip("gain_rev:Q", format=",.0f", title="₹ revenue gain"),
             alt.Tooltip("gain_rgm:Q", format=",.0f", title="₹ RGM gain")],
).properties(height=max(360, 18 * len(top_stores)))
st.altair_chart(themed(heat), width="stretch")
st.caption("Top 30 stores by absolute gain shown; full data in the table below.")

pivot = (ds.pivot_table(index="store_name", columns=ds["sale_date"].dt.strftime("%d %b"),
                        values="gain_rev", aggfunc="sum").fillna(0).round(0))
pivot["TOTAL"] = pivot.sum(axis=1)
pivot = pivot.sort_values("TOTAL", ascending=False)
with st.expander(f"Table — Date × Store, all {ds['store_name'].nunique()} stores (₹ revenue gain)"):
    st.dataframe(pivot, width="stretch", height=420)
    st.download_button("⬇ CSV", pivot.to_csv().encode(), "date_store_gain.csv", "text/csv")

# =====================================================================
# §2 TOP 50 DRUGS
# =====================================================================
section("2 · Impact of pricing — top 50 drugs",
        "Largest absolute Revenue / RGM gain contributors (both signs)")
gm_metric = st.radio("Metric", ["Revenue gain", "RGM gain"], horizontal=True, label_visibility="collapsed")
mcol = "gain_rev" if gm_metric == "Revenue gain" else "gain_rgm"
dgn = (d["drug_gain"].groupby(["drug_id", "direction"])
       .agg(drug_name=("drug_name", "first"), units_post=("units_post", "sum"),
            gain_rev=("gain_rev", "sum"), gain_rgm=("gain_rgm", "sum"),
            old_price=("old_price", "first"), new_price=("new_price", "first")).reset_index())
top50 = dgn.reindex(dgn[mcol].abs().sort_values(ascending=False).index).head(50).copy()
top50["label"] = top50["drug_name"].str.slice(0, 38) + "  ·" + top50["drug_id"].astype(str)
bar50 = alt.Chart(top50).mark_bar(cornerRadiusEnd=4, height=11).encode(
    y=alt.Y("label:N", sort=alt.EncodingSortField(mcol, order="descending"), title=None,
            axis=alt.Axis(labelLimit=320)),
    x=alt.X(f"{mcol}:Q", title=f"₹ {gm_metric.lower()} (post window)"),
    color=alt.condition(alt.datum[mcol] >= 0, alt.value(GOOD), alt.value(BAD)),
    tooltip=["drug_id:Q", "drug_name:N", "direction:N",
             alt.Tooltip("old_price:Q", format=".2f"), alt.Tooltip("new_price:Q", format=".2f"),
             alt.Tooltip("units_post:Q", format=",.0f"),
             alt.Tooltip("gain_rev:Q", format=",.0f", title="₹ revenue gain"),
             alt.Tooltip("gain_rgm:Q", format=",.0f", title="₹ RGM gain")],
).properties(height=50 * 15)
st.altair_chart(themed(bar50), width="stretch")
with st.expander("Table — top 50"):
    show = top50[["drug_id", "drug_name", "direction", "old_price", "new_price",
                  "units_post", "gain_rev", "gain_rgm"]].round(2)
    st.dataframe(show, width="stretch", hide_index=True)
    st.download_button("⬇ CSV", show.to_csv(index=False).encode(), "top50_drug_gain.csv", "text/csv")

# =====================================================================
# §3 GENRTN
# =====================================================================
section("3 · GENRTN usage — Store × Drug", "Price-match coupon redemptions in the post window")
gn = filt_stores(d["genrtn_store_drug"])
if gn.empty or gn["bills"].sum() == 0:
    st.info("🎫 No GENRTN redemptions recorded in the post window yet.")
else:
    g1, g2, g3 = st.columns(3)
    g1.metric("GENRTN bills", inr_group(gn["bills"].sum()))
    g2.metric("Units", inr_group(gn["units"].sum()))
    g3.metric("Give-back", lakh(-gn["giveback"].sum(), signed=False))
    bub = alt.Chart(gn).mark_circle(opacity=.85, stroke=SURFACE, strokeWidth=2).encode(
        x=alt.X("drug_name:N", title=None, axis=alt.Axis(labelAngle=-45, labelLimit=140)),
        y=alt.Y("store_name:N", title=None),
        size=alt.Size("units:Q", title="units", scale=alt.Scale(range=[80, 900])),
        color=alt.value(VIOLET),
        tooltip=["store_name:N", "drug_name:N", alt.Tooltip("units:Q", format=",.0f"),
                 "bills:Q", alt.Tooltip("giveback:Q", format=",.0f", title="₹ give-back")],
    ).properties(height=max(240, 20 * gn["store_name"].nunique()))
    st.altair_chart(themed(bub), width="stretch")
    with st.expander("Table — GENRTN Store × Drug"):
        st.dataframe(gn.sort_values("giveback", ascending=False), width="stretch", hide_index=True)

# =====================================================================
# §4 QTY CHANGE
# =====================================================================
section("4 · Qty purchase change", f"Units, day-aligned: pre {PRE_LB} vs post {POST_LB}"
        + (" · pilot stores excluded" if excl_pilot else ""))
q = filt_pilot(d["qty_change"]).groupby(["window", "direction"])["units"].sum().reset_index()
qp = q.pivot(index="direction", columns="window", values="units").fillna(0)
qp["delta_pct"] = 100 * (qp["post"] / qp["pre"] - 1)
tot_pre, tot_post = qp["pre"].sum(), qp["post"].sum()
qc1, qc2, qc3 = st.columns(3)
qc1.metric("Units — pre", inr_group(tot_pre))
qc2.metric("Units — post", inr_group(tot_post), f"{100*(tot_post/tot_pre-1):+.1f}%")
if "increased" in qp.index:
    qc3.metric("Units on Price ↑ drugs", inr_group(qp.loc['increased', 'post']),
               f"{qp.loc['increased', 'delta_pct']:+.1f}%")
qm = q.copy()
qm["direction"] = qm["direction"].map(DIR_LABEL)
qm["window"] = qm["window"].map({"pre": f"Pre ({PRE_LB})", "post": f"Post ({POST_LB})"})
qty_ch = alt.Chart(qm).mark_bar(cornerRadiusEnd=4, width=26).encode(
    x=alt.X("direction:N", title=None, sort=["Price ↑", "Price ↓", "Flat", "No old price"],
            axis=alt.Axis(labelAngle=0)),
    y=alt.Y("units:Q", title="units"),
    xOffset=alt.XOffset("window:N", sort=[f"Pre ({PRE_LB})", f"Post ({POST_LB})"]),
    color=alt.Color("window:N", title=None, scale=alt.Scale(
        domain=[f"Pre ({PRE_LB})", f"Post ({POST_LB})"], range=[MUTED, BLUE]),
        legend=alt.Legend(orient="top")),
    tooltip=["direction:N", "window:N", alt.Tooltip("units:Q", format=",.0f")],
).properties(height=260)
du = filt_pilot(d["daily_units"]).copy()
du["dom"] = du["sale_date"].dt.day
du = du.groupby(["dom", "window"])["units"].sum().reset_index()
du["window"] = du["window"].map({"pre": "June (pre)", "post": "July (post)"})
du_ch = alt.Chart(du).mark_line(strokeWidth=2, point=alt.OverlayMarkDef(size=50, filled=True)).encode(
    x=alt.X("dom:O", title="day of month", axis=alt.Axis(labelAngle=0)),
    y=alt.Y("units:Q", title="units / day"),
    color=alt.Color("window:N", title=None, scale=alt.Scale(
        domain=["June (pre)", "July (post)"], range=[MUTED, BLUE]), legend=alt.Legend(orient="top")),
    tooltip=["window:N", "dom:O", alt.Tooltip("units:Q", format=",.0f")],
).properties(height=260)
qcol1, qcol2 = st.columns(2)
with qcol1:
    st.markdown("**Units by price direction**"); st.altair_chart(themed(qty_ch), width="stretch")
with qcol2:
    st.markdown("**Daily units, day-of-month aligned**"); st.altair_chart(themed(du_ch), width="stretch")

# =====================================================================
# §5 SUBSTITUTION
# =====================================================================
section("5 · Substitution %", "Generic (GA + NGA) share of units — pre vs post"
        + (" · pilot stores excluded" if excl_pilot else ""))
sb = filt_pilot(filt_stores(d["substitution"]))
sbt = sb.groupby(["window", "segment"])["units"].sum().reset_index()
piv = sbt.pivot(index="window", columns="segment", values="units").fillna(0)
for seg in SEG_ORDER:
    if seg not in piv: piv[seg] = 0.0
piv["total"] = piv[SEG_ORDER].sum(axis=1)
piv["subst_pct"] = 100 * (piv["GA"] + piv["NGA"]) / piv["total"]
piv["ga_share"] = 100 * piv["GA"] / (piv["GA"] + piv["NGA"])
s1, s2, s3 = st.columns(3)
s1.metric("Substitution % — pre", f"{piv.loc['pre', 'subst_pct']:.1f}%")
s2.metric("Substitution % — post", f"{piv.loc['post', 'subst_pct']:.1f}%",
          f"{piv.loc['post', 'subst_pct'] - piv.loc['pre', 'subst_pct']:+.1f} pp")
s3.metric("GA share of generic — post", f"{piv.loc['post', 'ga_share']:.1f}%",
          f"{piv.loc['post', 'ga_share'] - piv.loc['pre', 'ga_share']:+.1f} pp")
sbt["window_lb"] = sbt["window"].map({"pre": f"Pre ({PRE_LB})", "post": f"Post ({POST_LB})"})
stack = alt.Chart(sbt).mark_bar(cornerRadiusEnd=3, height=34, stroke=SURFACE, strokeWidth=2).encode(
    y=alt.Y("window_lb:N", title=None, sort=[f"Pre ({PRE_LB})", f"Post ({POST_LB})"]),
    x=alt.X("units:Q", stack="normalize", title="share of units", axis=alt.Axis(format="%")),
    color=alt.Color("segment:N", title=None, sort=SEG_ORDER,
                    scale=alt.Scale(domain=SEG_ORDER, range=[SEG_COLORS[s] for s in SEG_ORDER]),
                    legend=alt.Legend(orient="top")),
    order=alt.Order("color_segment_sort_index:Q"),
    tooltip=["window_lb:N", "segment:N", alt.Tooltip("units:Q", format=",.0f")],
).properties(height=140)
st.altair_chart(themed(stack), width="stretch")
ga_nga = piv[["GA", "NGA"]].copy()
ga_nga["GA %"] = (100 * ga_nga["GA"] / (ga_nga["GA"] + ga_nga["NGA"])).round(1)
ga_nga["NGA %"] = (100 - ga_nga["GA %"]).round(1)
st.caption(f"GA vs NGA (share of generic units): pre {ga_nga.loc['pre','GA %']}% / {ga_nga.loc['pre','NGA %']}% → "
           f"post {ga_nga.loc['post','GA %']}% / {ga_nga.loc['post','NGA %']}%")

# =====================================================================
# §6 GM% & FREQUENCY
# =====================================================================
section("6 · GM% & Frequency — pre vs post",
        ("Pilot stores excluded from both. " if excl_pilot else "") + "GM% as-billed; frequency = bills / patient")
gmv = filt_pilot(filt_stores(d["gm_store"]))
gm_tot = gmv.groupby("window")[["revenue", "cogs"]].sum()
gm_tot["gm_pct"] = 100 * (gm_tot["revenue"] - gm_tot["cogs"]) / gm_tot["revenue"]
fc = filt_pilot(d["freq_chain"]).groupby("window")[["bills", "patients"]].sum()
fc["freq"] = fc["bills"] / fc["patients"]
m1, m2, m3, m4 = st.columns(4)
m1.metric("GM % — pre", f"{gm_tot.loc['pre', 'gm_pct']:.1f}%")
m2.metric("GM % — post", f"{gm_tot.loc['post', 'gm_pct']:.1f}%",
          f"{gm_tot.loc['post', 'gm_pct'] - gm_tot.loc['pre', 'gm_pct']:+.2f} pp")
m3.metric("Frequency — pre", f"{fc.loc['pre', 'freq']:.3f}")
m4.metric("Frequency — post", f"{fc.loc['post', 'freq']:.3f}",
          f"{fc.loc['post', 'freq'] - fc.loc['pre', 'freq']:+.3f}")

gs = gmv.groupby(["window", "store_name"])[["revenue", "cogs"]].sum().reset_index()
gs["gm_pct"] = 100 * (gs["revenue"] - gs["cogs"]) / gs["revenue"]
top_rev = gs[gs["window"] == "post"].nlargest(20, "revenue")["store_name"]
gs20 = gs[gs["store_name"].isin(top_rev)].copy()
gs20["window_lb"] = gs20["window"].map({"pre": "Pre", "post": "Post"})
dumb_line = alt.Chart(gs20).mark_line(color=GRID, strokeWidth=2).encode(
    y=alt.Y("store_name:N", title=None, sort=top_rev.tolist()), x=alt.X("gm_pct:Q", title="GM %"),
    detail="store_name:N")
dumb_pts = alt.Chart(gs20).mark_point(filled=True, size=90, stroke=SURFACE, strokeWidth=2).encode(
    y=alt.Y("store_name:N", sort=top_rev.tolist(), title=None), x="gm_pct:Q",
    color=alt.Color("window_lb:N", title=None, scale=alt.Scale(domain=["Pre", "Post"], range=[MUTED, BLUE]),
                    legend=alt.Legend(orient="top")),
    tooltip=["store_name:N", "window_lb:N", alt.Tooltip("gm_pct:Q", format=".1f")])
st.markdown("**GM% shift — top 20 stores by post revenue**")
st.altair_chart(themed((dumb_line + dumb_pts).properties(height=420)), width="stretch")

fs = filt_pilot(filt_stores(d["freq_store"])).copy()
fs["frequency"] = fs["bills"] / fs["patients"]
fsp = fs.pivot_table(index="store_name", columns="window", values=["bills", "patients", "frequency"])
fsp.columns = [f"{a}_{b}" for a, b in fsp.columns]
fsp = fsp.round(3).sort_values("bills_post", ascending=False)
with st.expander("Table — per-store bills, patients, frequency (pre vs post)"):
    st.dataframe(fsp, width="stretch", height=400)
    st.download_button("⬇ CSV", fsp.to_csv().encode(), "freq_gm_store.csv", "text/csv")

st.divider()
st.caption(f"Gain excludes {meta['drugs_no_old_price']:,} drugs with no old-price reference "
           f"({meta['units_share_no_old_price_pct']}% of post units). Old prices = pre-July modal rate at "
           f"non-pilot stores (`drug_old_selling_price.csv`); old COGS = June unit purchase rate "
           f"({meta.get('drugs_no_old_cogs', 0):,} drugs fall back to current COGS). "
           f"As-billed values (not pre-tax). Data refreshed {meta['refreshed_at']}.")
