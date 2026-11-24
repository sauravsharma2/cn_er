"""China direct entries - exact native-name matching against the CN pool.

Steps
  1. Fetch entries (SQL or file) + encoding fix
  2. Build simplified_chinese_name and the match key for every entry
  3. Scan the pool in batches; keep pairs whose keys are exactly equal
  4. Ex-id dedupe (CN123 beats CN123!)
  5. Fetch full rows for the matched pool ids; enrich entries + matched pool
  6. Build sheets: Entries, Propositions, Unique_Matches, Multiple_Matches, NoMatch;
     add LinkType + OwnershipLink to Unique_Matches and Multiple_Matches
  7. Write the workbook

Usage (project root, venv active)
  python main.py                                     full run from SQL Server
  python main.py --limit 1000                        first 1000 entries
  python main.py --ids-file ids.txt                  selected entries via #TempIds
  python main.py --input sample/entries.csv --pool-file sample/pool.csv    offline test
"""
import argparse
import logging
import sys
import time
from pathlib import Path

import pandas as pd

from src.code.address_enrichment import enrich_addresses
from src.code.get_cases import get_cases
from src.code.match_key import display_name, key_kind, match_key
from src.code.match_output import build_sheets, to_block, write_workbook
from src.code.matcher import load_pool_rows, match_against_pool
from src.code.ownership import apply_ownership
from src.code.text_utils import to_pinyin
from utils import config

log = logging.getLogger("main")


def _args():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", help="entries CSV/Excel instead of SQL (offline test)")
    ap.add_argument("--pool-file", help="pool CSV/Excel instead of SQL (offline test)")
    ap.add_argument("--ids-file", help="text file, one entry id per line")
    ap.add_argument("--limit", type=int, help="keep only the first N entries")
    ap.add_argument("--batch-size", type=int, help="pool rows per batch (default from config)")
    ap.add_argument("--output", help="output .xlsx path")
    ap.add_argument("--skip-ownership", action="store_true", help="don't fetch ownership links")
    return ap.parse_args()


def _enrich(df: pd.DataFrame, label: str) -> pd.DataFrame:
    """Names (simplified + pinyin) and address for one frame."""
    if df.empty:
        return df
    t = time.perf_counter()
    df = df.copy()
    df["simplified_chinese_name"] = df["native_name"].map(display_name)
    log.info("[5] %s: pinyin for %s names", label, f"{df['simplified_chinese_name'].notna().sum():,}")
    df["pinyin_name"] = df["simplified_chinese_name"].map(to_pinyin)
    log.info("[5] %s: address enrichment for %s rows", label, f"{len(df):,}")
    df = enrich_addresses(df)
    log.info("[5] %s enriched in %.1fs", label, time.perf_counter() - t)
    return df


def run(a) -> int:
    t0 = time.perf_counter()
    if a.limit:
        config.TEST_LIMIT = a.limit
    if a.batch_size:
        config.POOL_BATCH_SIZE = a.batch_size

    # ---- 1. entries
    log.info("[1] Fetching entries...")
    ids = None
    if a.ids_file:
        ids = [l.strip() for l in Path(a.ids_file).read_text(encoding="utf-8").splitlines() if l.strip()]
        log.info("[1] %s ids read from %s", f"{len(ids):,}", a.ids_file)
    entries = get_cases(a.input, ids=ids)
    log.info("[1] Entries fetched: %s rows", f"{len(entries):,}")
    if entries.empty:
        log.warning("[1] No entries returned - nothing to do.")
        return 0
    entries = entries.drop_duplicates(subset=["id"]).reset_index(drop=True)

    # ---- 2. match keys
    log.info("[2] Building match keys...")
    entries["_display"] = entries["native_name"].map(display_name)
    entries["_key"] = entries["_display"].map(match_key)
    kinds = entries["_key"].map(key_kind).value_counts()
    log.info("[2] Match keys: chinese=%s | english=%s | blank (excluded)=%s",
             f"{kinds.get('chinese', 0):,}", f"{kinds.get('english', 0):,}", f"{kinds.get('blank', 0):,}")
    dup_keys = entries["_key"].dropna().duplicated(keep=False).sum()
    if dup_keys:
        log.info("[2] %s entries share their key with another entry (each is matched on its own)",
                 f"{dup_keys:,}")

    # ---- 3 + 4. pool scan, ex-id dedupe
    log.info("[3] Scanning the pool in batches of %s...", f"{config.POOL_BATCH_SIZE:,}")
    pairs, pool_ids = match_against_pool(entries, pool_file=a.pool_file)
    log.info("[4] Pairs after dedupe: %s | entries matched: %s | pool ids matched: %s",
             f"{len(pairs):,}", f"{pairs['OriginalId'].nunique():,}", f"{len(pool_ids):,}")

    # ---- 5. enrichment
    pool_rows = load_pool_rows(pool_ids, pool_file=a.pool_file)
    missing = set(pool_ids) - set(pool_rows["id"])
    if missing:
        log.warning("[5] %s matched pool ids not found on re-fetch; their columns will be blank",
                    f"{len(missing):,}")
    entries_enriched = _enrich(entries.drop(columns=["_display", "_key"]), "Entries")
    pool_enriched = _enrich(pool_rows, "Matched pool")

    # ---- 6. sheets
    matched = set(pairs["OriginalId"])
    reason = {}
    for i, k in zip(entries["id"], entries["_key"]):
        if i not in matched:
            reason[i] = "blank_native_name" if pd.isna(k) else "no_match"
    sheets = build_sheets(to_block(entries_enriched), to_block(pool_enriched), pairs, reason)

    # ---- 6b. ownership labels on Unique_Matches / Multiple_Matches (rows are not moved)
    if a.pool_file or a.skip_ownership:
        log.info("[6] Ownership skipped (%s): rows get 'No ownership data'",
                 "offline test" if a.pool_file else "--skip-ownership")
        sheets = apply_ownership(sheets, ownership={})
    else:
        sheets = apply_ownership(sheets)

    # ---- 7. write
    out = Path(a.output) if a.output else Path(getattr(config, "MATCH_OUTPUT_FILE",
                                                       config.OUTPUT_DIR / "china_direct_entries_matches.xlsx"))
    write_workbook(sheets, out)

    m, s = divmod(time.perf_counter() - t0, 60)
    h, m = divmod(m, 60)
    log.info("[DONE] %s in %dh %dm %.0fs", out, h, m, s)
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stdout)
    try:
        sys.exit(run(_args()))
    except Exception:
        log.exception("[ERROR] run failed")
        sys.exit(1)
