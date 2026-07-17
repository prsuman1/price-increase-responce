# Price Live — Chain-wide Price Hike Impact Dashboard

Streamlit dashboard tracking the impact of the 2026-07-01 chain-wide price
increase (~4,800 SKUs, ~200 stores).

Two pages:

- **⚡ Impact** — revenue & RGM gain from the price hike, vs a
  counterfactual using pre-hike (June) prices at non-pilot stores.
- **💬 Customer Voice** — chain-wide surveyor-logged customer reactions,
  aggregated from 8 rotating field surveyors' Google Sheets.

## Local run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run dashboard.py --server.port 8502
```

The dashboard reads precomputed CSVs from `data/` — VPN is NOT required to
view. VPN + `.env` credentials only needed to refresh.

## Refresh data (VPN required)

Create `.env` at repo root with Redshift creds:

```
REDSHIFT_HOST=...
REDSHIFT_PORT=5439
REDSHIFT_DB=...
REDSHIFT_USER=...
REDSHIFT_PASSWORD=...
```

Then:

```bash
python refresh_dashboard_data.py
```

This runs the quant refresh (Redshift → 12 CSVs) and pulls the 8 Google
survey sheets → `data/survey.csv` in one command. Commit + push to
trigger a Streamlit Cloud redeploy.

## Deploying on Streamlit Cloud

- Point Cloud at `dashboard.py` on the `main` branch.
- No secrets needed for viewing — Cloud reads the committed CSVs.
- To refresh from Cloud is not supported (Cloud can't reach Redshift or
  authenticated Google Sheets); refresh locally with VPN and push.

## Files

| File | Purpose |
|---|---|
| `dashboard.py` | Multi-page nav entry (`st.navigation`) |
| `pg_impact.py` | Impact page — revenue/RGM gain analysis |
| `pg_customer_voice.py` | Customer Voice page — surveyor insights |
| `refresh_dashboard_data.py` | Rebuild all data files (needs VPN + `.env`) |
| `survey_ingest.py` | Fetch + normalize the 8 surveyor sheets |
| `_shared.py` | Standalone helpers (Redshift conn, RAG classifier, bill-ID normalizer) |
| `drug_old_selling_price.csv` | Pre-July modal rate per drug at non-pilot stores |
| `data/` | Precomputed CSVs read by the dashboard |
