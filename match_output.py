"""Matching workbook: Entries, Propositions, Unique_Matches, Multiple_Matches, NoMatch."""
import logging
import math
import re
import time

import pandas as pd

from utils import config

log = logging.getLogger(__name__)

# one block per side; the matched side repeats it with a "matched_" prefix
BLOCK = [
    "id", "name", "nativename", "simplified_chinese_name", "pinyin_name",
    "raw_address", "raw_pccity", "raw_postcode",
    "company_street_address", "company_district", "company_city",
    "company_state", "company_postcode",
]

# enriched frame column -> block column
_SOURCE = {
    "id": "id", "name": "name", "native_name": "nativename",
    "simplified_chinese_name": "simplified_chinese_name", "pinyin_name": "pinyin_name",
    "address": "raw_address", "pccity": "raw_pccity", "postcode": "raw_postcode",
    "street_address": "company_street_address", "county": "company_district",
    "city": "company_city", "province": "company_state",
    "postcode_enriched": "company_postcode",
}

# openpyxl rejects control characters
_ILLEGAL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def to_block(enriched: pd.DataFrame) -> pd.DataFrame:
    """Enriched frame -> the agreed column block, one row per id."""
    out = enriched.rename(columns=_SOURCE)
    for c in BLOCK:
        if c not in out.columns:
            out[c] = pd.NA
    return out[BLOCK].drop_duplicates(subset=["id"]).reset_index(drop=True)


def _pair_sheet(pairs: pd.DataFrame, block: pd.DataFrame) -> pd.DataFrame:
    left = block.rename(columns={"id": "OriginalId"})
    right = block.add_prefix("matched_").rename(columns={"matched_id": "MatchedId"})
    out = (pairs.merge(left, on="OriginalId", how="left")
                .merge(right, on="MatchedId", how="left"))
    out = out.rename(columns={"OriginalId": "id", "MatchedId": "matched_id"})
    cols = BLOCK + ["matched_" + c for c in BLOCK]
    return out[cols].sort_values(["id", "matched_id"], kind="stable").reset_index(drop=True)


def build_sheets(entries_block, pool_block, pairs, nomatch_reason):
    """
    entries_block  : block for every entry
    pool_block     : block for every matched pool id
    pairs          : OriginalId / MatchedId after the ex-id dedupe
    nomatch_reason : {entry id: reason} for the NoMatch sheet
    """
    both = pd.concat([entries_block, pool_block], ignore_index=True).drop_duplicates(subset=["id"])

    counts = pairs.groupby("OriginalId")["MatchedId"].nunique()
    unique_ids = set(counts[counts == 1].index)
    multi_ids = set(counts[counts >= 2].index)

    propositions = _pair_sheet(pairs, both)
    unique = propositions[propositions["id"].isin(unique_ids)].reset_index(drop=True)
    multiple = propositions[propositions["id"].isin(multi_ids)].reset_index(drop=True)

    nomatch = entries_block[entries_block["id"].isin(set(nomatch_reason))].copy()
    nomatch["no_match_reason"] = nomatch["id"].map(nomatch_reason)
    nomatch = nomatch.sort_values("id").reset_index(drop=True)

    log.info("[6] Propositions=%s | Unique_Matches=%s (%s ids) | Multiple_Matches=%s (%s ids) | "
             "NoMatch=%s", f"{len(propositions):,}", f"{len(unique):,}", f"{len(unique_ids):,}",
             f"{len(multiple):,}", f"{len(multi_ids):,}", f"{len(nomatch):,}")

    return {
        "Entries": entries_block.sort_values("id").reset_index(drop=True),
        "Propositions": propositions,
        "Unique_Matches": unique,
        "Multiple_Matches": multiple,
        "NoMatch": nomatch,
    }


def _clean_for_excel(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for c in df.columns:
        if df[c].dtype == object or str(df[c].dtype) == "string":
            df[c] = df[c].map(lambda v: _ILLEGAL.sub("", v) if isinstance(v, str) else v)
    return df


def write_workbook(sheets: dict, path) -> None:
    max_rows = getattr(config, "EXCEL_MAX_ROWS", 1_000_000)
    path.parent.mkdir(parents=True, exist_ok=True)
    t = time.perf_counter()
    log.info("[7] Writing %s", path)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for name, df in sheets.items():
            df = _clean_for_excel(df)
            n = max(1, math.ceil(len(df) / max_rows))
            for i in range(n):
                part = df.iloc[i * max_rows:(i + 1) * max_rows]
                sheet = f"{name}_{i + 1}" if n > 1 else name
                part.to_excel(writer, sheet_name=sheet[:31], index=False, freeze_panes=(1, 0))
                log.info("[7]   %s: %s rows", sheet, f"{len(part):,}")
    log.info("[7] Written in %.1fs", time.perf_counter() - t)
