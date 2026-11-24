"""Ownership labels for matched pairs (same logic as the US project).

One DB trip for every id on the Unique_Matches / Multiple_Matches sheets:
    Links    (Type = 1)  -> parents / children of each id
    UO_links             -> ultimate owner(s) of each id

Two columns are added to each pair sheet - rows are never moved or dropped:
    LinkType       the two ids are directly parent/child of each other, e.g.
                   "Direct→Good (Parent→Child)"; blank when they are not
    OwnershipLink  Same Parent | Same Child | Same UO (joined with " | "),
                   "No shared ownership", or "No ownership data"
Ids are compared without the trailing '!' (links are stored unsuffixed).
"""
import logging
import time
from collections import defaultdict

import pandas as pd

from src.db_connexion.data_extraction import connect_db, load_query
from utils import config

log = logging.getLogger(__name__)

_CHUNK = 1000


# ---------------------------------------------------------------- fetch
def fetch_ownership_links(ids) -> tuple:
    """-> (link_rows [(ParentId, ChildId)], uo_rows [(ChildId, UO)])"""
    clean = sorted({str(x).strip().rstrip("!") for x in ids if pd.notna(x) and str(x).strip()})
    if not clean:
        return [], []

    t = time.perf_counter()
    log.info("[6] Ownership: fetching links for %s ids", f"{len(clean):,}")
    link_rows, uo_rows = [], []
    conn = connect_db()
    try:
        cur = conn.cursor()
        cur.execute("IF OBJECT_ID('tempdb..#TempIds') IS NOT NULL DROP TABLE #TempIds;")
        # VARCHAR (not NVARCHAR) so the joins can seek on Links / UO_links ids
        cur.execute("CREATE TABLE #TempIds (Id VARCHAR(255) NOT NULL PRIMARY KEY);")
        cur.fast_executemany = True
        for i in range(0, len(clean), _CHUNK):
            cur.executemany("INSERT INTO #TempIds (Id) VALUES (?)", [(x,) for x in clean[i:i + _CHUNK]])
        conn.commit()

        try:
            cur.execute(load_query(getattr(config, "OWNERSHIP_LINKS_QUERY", "get_ownership_links.sql")))
            link_rows = [(r[0], r[1]) for r in cur.fetchall()]
        except Exception as e:                       # keep the run alive; rows get "No ownership data"
            log.warning("[6] Ownership: links fetch failed: %s", e)
        try:
            cur.execute(load_query(getattr(config, "UO_LINKS_QUERY", "get_uo_links_by_ids.sql")))
            uo_rows = [(r[0], r[1]) for r in cur.fetchall()]
        except Exception as e:
            log.warning("[6] Ownership: UO links fetch failed: %s", e)
    finally:
        conn.close()

    log.info("[6] Ownership: %s links, %s UO links fetched (%.1fs)",
             f"{len(link_rows):,}", f"{len(uo_rows):,}", time.perf_counter() - t)
    return link_rows, uo_rows


def build_ownership_map(link_rows, uo_rows) -> dict:
    """{id: {"parents": set, "children": set, "uos": set}}"""
    own = defaultdict(lambda: {"parents": set(), "children": set(), "uos": set()})
    for parent, child in link_rows:
        if parent is None or child is None:
            continue
        parent, child = str(parent).strip(), str(child).strip()
        own[parent]["children"].add(child)
        own[child]["parents"].add(parent)
    for child, uo in uo_rows:
        if child is None or uo is None:
            continue
        own[str(child).strip()]["uos"].add(str(uo).strip())
    return dict(own)


# ---------------------------------------------------------------- labels
def direct_link_type(orig_id: str, matched_id: str, own: dict):
    o, m = own.get(orig_id, {}), own.get(matched_id, {})
    if matched_id in o.get("children", ()):
        return "Direct→Good (Parent→Child)"
    if matched_id in o.get("parents", ()):
        return "Direct→Good (Child→Parent)"
    if orig_id in m.get("children", ()):
        return "Good→Direct (Parent→Child)"
    if orig_id in m.get("parents", ()):
        return "Good→Direct (Child→Parent)"
    return None


def ownership_label(o: dict, m: dict) -> str:
    labels = []
    if o["parents"] & m["parents"]:
        labels.append("Same Parent")
    if o["children"] & m["children"]:
        labels.append("Same Child")
    if o["uos"] & m["uos"]:
        labels.append("Same UO")
    return " | ".join(labels) if labels else "No shared ownership"


def stamp(df: pd.DataFrame, own: dict, orig_col="id", match_col="matched_id") -> pd.DataFrame:
    """Add LinkType + OwnershipLink to a pair sheet. No rows are removed."""
    out = df.copy()
    if out.empty:
        out["LinkType"] = pd.Series(dtype=object)
        out["OwnershipLink"] = pd.Series(dtype=object)
        return out
    link_types, labels = [], []
    for a, b in zip(out[orig_col].astype(str), out[match_col].astype(str)):
        a, b = a.strip().rstrip("!"), b.strip().rstrip("!")
        link_types.append(direct_link_type(a, b, own))
        o, m = own.get(a), own.get(b)
        labels.append(ownership_label(o, m) if (o and m) else "No ownership data")
    out["LinkType"] = link_types
    out["OwnershipLink"] = labels
    return out


def apply_ownership(sheets: dict, names=("Unique_Matches", "Multiple_Matches"),
                    ownership: dict | None = None) -> dict:
    """Fetch once for every id on the named sheets, then stamp each sheet.
    Pass `ownership` to skip the DB fetch (offline tests)."""
    if ownership is None:
        ids = set()
        for n in names:
            df = sheets.get(n)
            if df is not None and not df.empty:
                ids.update(df["id"].dropna().astype(str))
                ids.update(df["matched_id"].dropna().astype(str))
        try:
            ownership = build_ownership_map(*fetch_ownership_links(ids))
        except Exception as e:
            log.warning("[6] Ownership pass failed, all rows get 'No ownership data': %s", e)
            ownership = {}

    for n in names:
        if n in sheets:
            sheets[n] = stamp(sheets[n], ownership)
            df = sheets[n]
            if not df.empty:
                log.info("[6] %s ownership: direct=%s | %s", n, f"{df['LinkType'].notna().sum():,}",
                         " | ".join(f"{k}={v:,}" for k, v in df["OwnershipLink"].value_counts().items()))
    return sheets
