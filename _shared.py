"""Standalone helpers shared by refresh_dashboard_data.py and survey_ingest.py.

Copied inline from the parent project's data.py so the Price Live folder
is deployable on its own (Streamlit Cloud) without depending on the parent
Price-A-B project layout.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent

# ----- constants -------------------------------------------------------------

ASSORTMENT_GENERIC = (3, 4)   # Generic + Generic-Speciality
ASSORTMENT_ETHICAL = (1, 2)   # Ethical + Ethical-Speciality

COUPON_PREFIX = "GENRTN"

# RAG classification patterns (case-insensitive substring)
RED_PATTERNS = ["bana hi nahin", "chale gaye", "didn't buy", "didnt buy", "left without", "bana hi nai"]
PARTIAL_PATTERNS = ["partial bana", "item kam"]

# Bill-ID normalization
PREFIX_FIXES = {"KEWT": "KRWT"}
SERIAL_RE = re.compile(r"^[A-Z]+-\d+$")


# ----- Redshift connection (used by refresh only; not needed for viewing) ----

def _env() -> dict:
    # Try local .env first; fall back to parent project dir (main Price-A-B repo).
    load_dotenv(HERE / ".env")
    load_dotenv(HERE.parent / ".env")
    return {
        "host": os.environ["REDSHIFT_HOST"],
        "port": int(os.environ["REDSHIFT_PORT"]),
        "dbname": os.environ["REDSHIFT_DB"],
        "user": os.environ["REDSHIFT_USER"],
        "password": os.environ["REDSHIFT_PASSWORD"],
    }


def _connect():
    return psycopg2.connect(connect_timeout=15, **_env())


# ----- RAG classifier --------------------------------------------------------

def classify_rag(outcome: str, used_genrtn: bool) -> tuple[str, bool, bool]:
    """Return (rag, is_amber_partial, is_amber_genrtn) for one bill.

    Precedence: RED > AMBER (partial OR genrtn) > GREEN.
    """
    o = (outcome or "").strip().lower()
    if any(p in o for p in RED_PATTERNS):
        return "red", False, False
    is_partial = any(p in o for p in PARTIAL_PATTERNS)
    if is_partial or used_genrtn:
        return "amber", is_partial, bool(used_genrtn)
    return "green", False, False


# ----- Bill-ID serial normalizer --------------------------------------------

def _normalize_alpha_serial(raw: str) -> str | None:
    """Normalize surveyor-typed bill IDs into `STORE-NNN` shape.

    Handles: leading Z/z, underscore-vs-hyphen, spaces, KEWT typo,
    multi-bill separators (`/`, `,`, `;`), and no-separator patterns like
    `KHAN312395`.
    """
    if not raw: return None
    if any(sep in raw for sep in ("/", ",", ";")):
        for tok in re.split(r"[/,;]", raw):
            result = _normalize_alpha_serial(tok)
            if result is not None: return result
        return None

    s = raw.strip().replace("_", "-")
    if not s or s.isdigit():
        return None
    if s[:1] in ("Z", "z"):
        s = s[1:]
    s = s.strip().upper().replace(" ", "")
    if "-" not in s:
        m = re.match(r"^([A-Z]+)(\d+)$", s)
        if m: s = f"{m.group(1)}-{m.group(2)}"
    if not SERIAL_RE.match(s):
        return None
    prefix, _, rest = s.partition("-")
    if prefix in PREFIX_FIXES:
        s = f"{PREFIX_FIXES[prefix]}-{rest}"
    return s
