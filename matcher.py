"""Exact native-name matching of the entries against the CN pool, batch by batch.

For each pool batch: decode the native name, build the match key, keep the rows
whose key equals an entry key. Everything else in the batch is discarded, so
memory stays flat however large the pool is.
"""
import logging
import time
from pathlib import Path

import pandas as pd

from src.code.encoding_fix import decode_bytes
from src.code.get_cases import _fix_encoding, _rename, TEXT_COLS
from src.code.match_key import display_name, match_key
from src.db_connexion.data_extraction import connect_db, fetch, load_query
from utils import config

log = logging.getLogger(__name__)

PAIR_COLS = ["OriginalId", "MatchedId"]


# ---------------------------------------------------------------- pool batches
def _sql_batches(batch_size: int):
    """Yield (batch_no, last_id_before, [(id, native_bytes), ...]) from SQL Server."""
    sql = load_query(config.POOL_BATCH_QUERY)
    conn = connect_db()
    try:
        cur = conn.cursor()
        last_id, batch_no = "", 0
        while True:
            batch_no += 1
            t = time.perf_counter()
            cur.execute(sql, batch_size, last_id)
            rows = cur.fetchall()
            log.info("[3] Pool batch %d fetched: %s rows after id '%s' (%.1fs)",
                     batch_no, f"{len(rows):,}", last_id, time.perf_counter() - t)
            if not rows:
                break
            yield batch_no, last_id, [(r[0], r[1]) for r in rows]
            last_id = str(rows[-1][0])
            if len(rows) < batch_size:
                break
    finally:
        conn.close()


def _file_batches(path: str, batch_size: int):
    """Same as _sql_batches but from a CSV/Excel file (offline tests)."""
    p = Path(path)
    df = (pd.read_excel(p, dtype=str) if p.suffix.lower() in (".xlsx", ".xls")
          else pd.read_csv(p, dtype=str, encoding="utf-8-sig"))
    df = df.rename(columns=lambda c: str(c).strip().lower().replace(" ", "_"))
    if "nativename" in df.columns and "native_name" not in df.columns:
        df = df.rename(columns={"nativename": "native_name"})
    rows = list(zip(df["id"], df["native_name"]))
    for i in range(0, len(rows), batch_size):
        chunk = rows[i:i + batch_size]
        log.info("[3] Pool batch %d read from file: %s rows", i // batch_size + 1, f"{len(chunk):,}")
        yield i // batch_size + 1, (rows[i - 1][0] if i else ""), chunk


# ---------------------------------------------------------------- matching
def match_against_pool(entries: pd.DataFrame, pool_file: str | None = None) -> tuple:
    """
    entries must carry columns id and _key.

    Returns (pairs, pool_ids):
        pairs    DataFrame OriginalId / MatchedId, after the ex-id dedupe
        pool_ids sorted list of matched pool ids
    """
    key_to_ids = (entries.dropna(subset=["_key"])
                  .groupby("_key")["id"].apply(list).to_dict())
    log.info("[3] Matching %s distinct entry keys against the pool",
             f"{len(key_to_ids):,}")

    batch_size = getattr(config, "POOL_BATCH_SIZE", 2_500_000)
    batches = _file_batches(pool_file, batch_size) if pool_file else _sql_batches(batch_size)

    pairs, total_rows, t_all = [], 0, time.perf_counter()
    for batch_no, _last_id, rows in batches:
        t = time.perf_counter()
        found = 0
        for pid, raw in rows:
            if pid is None:
                continue
            pid = str(pid).strip()
            if pid[3:4] == "*":                 # never a direct entry on the pool side
                continue
            native, _flag = decode_bytes(raw)
            key = match_key(display_name(native))
            if key is None:
                continue
            for oid in key_to_ids.get(key, ()):
                if oid != pid:
                    pairs.append((oid, pid))
                    found += 1
        total_rows += len(rows)
        log.info("[3] Pool batch %d matched: %s rows -> %s pairs | running total %s pairs, "
                 "%s pool rows (%.1fs)", batch_no, f"{len(rows):,}", f"{found:,}",
                 f"{len(pairs):,}", f"{total_rows:,}", time.perf_counter() - t)

    log.info("[3] Pool scan done: %s rows, %s raw pairs in %.1f min",
             f"{total_rows:,}", f"{len(pairs):,}", (time.perf_counter() - t_all) / 60)

    df = pd.DataFrame(pairs, columns=PAIR_COLS).drop_duplicates()
    df = dedupe_ex_ids(df)
    return df, sorted(df["MatchedId"].unique().tolist())


def dedupe_ex_ids(pairs: pd.DataFrame) -> pd.DataFrame:
    """
    When one OriginalId matches both CN123 and CN123! keep the current id.
    An ex-id ('!') with no current counterpart is kept.
    """
    if pairs.empty:
        return pairs
    work = pairs.copy()
    work["_base"] = work["MatchedId"].str.rstrip("!")
    work["_is_ex"] = work["MatchedId"].str.endswith("!")
    before = len(work)
    work = (work.sort_values(["OriginalId", "_base", "_is_ex"], kind="stable")
                .drop_duplicates(subset=["OriginalId", "_base"], keep="first"))
    log.info("[4] Ex-id dedupe: %s pairs -> %s (%s ex-ids dropped)",
             f"{before:,}", f"{len(work):,}", f"{before - len(work):,}")
    return work[PAIR_COLS].sort_values(PAIR_COLS).reset_index(drop=True)


# ---------------------------------------------------------------- matched pool rows
def load_pool_rows(ids: list, pool_file: str | None = None) -> pd.DataFrame:
    """Full rows (id, name, native_name, address, pccity, postcode) for the matched pool ids."""
    if not ids:
        return pd.DataFrame(columns=["id", "name", "native_name", "address", "pccity",
                                     "postcode", "encoding_flag"])
    if pool_file:
        p = Path(pool_file)
        df = (pd.read_excel(p, dtype=str) if p.suffix.lower() in (".xlsx", ".xls")
              else pd.read_csv(p, dtype=str, encoding="utf-8-sig"))
        df = df.rename(columns=lambda c: str(c).strip().lower().replace(" ", "_"))
        if "nativename" in df.columns and "native_name" not in df.columns:
            df = df.rename(columns={"nativename": "native_name"})
        df = df[df["id"].isin(set(ids))]
        from_sql = False
    else:
        log.info("[5] Fetching full rows for %s matched pool ids via #TempIds", f"{len(ids):,}")
        df = fetch(config.POOL_BY_IDS_QUERY, ids=ids)
        from_sql = True

    df = _rename(df)
    df = _fix_encoding(df, from_sql)
    for c in ["id", "name", "postcode"] + TEXT_COLS:
        df[c] = df[c].astype("string").str.strip().replace({"": pd.NA})
    log.info("[5] Matched pool rows loaded: %s", f"{len(df):,}")
    return df.drop_duplicates(subset=["id"]).reset_index(drop=True)
