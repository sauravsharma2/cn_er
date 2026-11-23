"""Builds the Entries frame from get_cases.sql (or a CSV/Excel for offline tests)."""
import logging
from pathlib import Path

import pandas as pd

from src.db_connexion.data_extraction import fetch
from utils import config

log = logging.getLogger(__name__)

REQUIRED = ["id", "name", "native_name", "address", "pccity", "postcode"]


def _normalise(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns=lambda c: str(c).strip().lower().replace(" ", "_"))
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"Input is missing columns: {missing}")
    df = df[REQUIRED].copy()
    for c in REQUIRED:
        df[c] = df[c].astype("string").str.strip().replace({"": pd.NA})
    return df


def get_cases(input_file: str | None = None, ids=None) -> pd.DataFrame:
    if input_file:
        p = Path(input_file)
        log.info("Reading entries from %s", p)
        df = (pd.read_excel(p, dtype=str) if p.suffix.lower() in (".xlsx", ".xls")
              else pd.read_csv(p, dtype=str, encoding="utf-8-sig"))
    else:
        query = config.GET_CASES_BY_IDS_QUERY if ids else config.GET_CASES_QUERY
        df = fetch(query, ids=ids)

    df = _normalise(df)
    if config.TEST_LIMIT:
        df = df.head(config.TEST_LIMIT)
    log.info("Entries: %d rows", len(df))
    return df.reset_index(drop=True)
