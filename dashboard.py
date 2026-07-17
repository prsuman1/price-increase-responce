"""Price Live — chain-wide go-live dashboard (multi-page Streamlit app).

Reads precomputed CSVs from `Price Live/data/` (built by
refresh_dashboard_data.py — VPN needed only for the refresh, not for viewing).

Pages:
  ⚡ Impact         — revenue & RGM gain from the price hike
  💬 Customer Voice — surveyor-logged customer reactions (chain-wide Jul 1+)

Run:
    .venv/bin/streamlit run "Price Live/dashboard.py" --server.port 8502
"""
import streamlit as st

st.set_page_config(page_title="Price Live", page_icon="⚡", layout="wide")

pages = [
    st.Page("pg_impact.py",         title="Impact",         icon="⚡", default=True),
    st.Page("pg_customer_voice.py", title="Customer Voice", icon="💬"),
]
st.navigation(pages).run()
