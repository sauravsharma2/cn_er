"""Builds the Entries frame from get_cases.sql (or a CSV/Excel for offline tests)."""
import logging
from pathlib import Path

import pandas as pd

from src.code.encoding_fix import decode_bytes, fix_mojibake
from src.db_connexion.data_extraction import fetch
from utils import config

log = logging.getLogger(__name__)

REQUIRED = ["id", "name", "native_name", "address", "pccity", "postcode"]
TEXT_COLS = ["native_name", "address", "pccity"]     # may contain Chinese


def _rename(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns=lambda c: str(c).strip().lower().replace(" ", "_"))
    if "nativename" in df.columns and "native_name" not in df.columns:
        df = df.rename(columns={"nativename": "native_name"})
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"Input is missing columns: {missing}")
    return df[REQUIRED].copy()


def _fix_encoding(df: pd.DataFrame, from_sql: bool) -> pd.DataFrame:
    fn = decode_bytes if from_sql else fix_mojibake
    flags = pd.Series("", index=df.index)
    for c in TEXT_COLS:
        res = df[c].map(fn)
        df[c] = res.str[0]
        f = res.str[1]
        if c == "native_name":
            flags = f
        else:   # only surface problems from address/city
            flags = flags.where(f != "unrecoverable", (flags + ";" + c + "_unrecoverable").str.lstrip(";"))
    df["encoding_flag"] = flags.replace("", pd.NA)
    counts = df["encoding_flag"].value_counts()
    if not counts.empty:
        log.info("Encoding:\n%s", counts.to_string())
    return df


def get_cases(input_file: str | None = None, ids=None) -> pd.DataFrame:
    if input_file:
        p = Path(input_file)
        log.info("Reading entries from %s", p)
        df = (pd.read_excel(p, dtype=str) if p.suffix.lower() in (".xlsx", ".xls")
              else pd.read_csv(p, dtype=str, encoding="utf-8-sig"))
        from_sql = False
    else:
        query = config.GET_CASES_BY_IDS_QUERY if ids else config.GET_CASES_QUERY
        df = fetch(query, ids=ids)
        from_sql = True

    df = _rename(df)
    df = _fix_encoding(df, from_sql)
    for c in ["id", "name", "postcode"] + TEXT_COLS:
        df[c] = df[c].astype("string").str.strip().replace({"": pd.NA})

    if config.TEST_LIMIT:
        df = df.head(config.TEST_LIMIT)
    log.info("Entries: %d rows", len(df))
    return df.reset_index(drop=True)
