"""SQL Server access: load_query, connect_db, #TempIds chunking."""
import logging
import warnings

import pandas as pd

from utils import config

log = logging.getLogger(__name__)


def load_query(name: str) -> str:
    path = config.QUERIES_DIR / name
    return path.read_text(encoding="utf-8")


def connect_db():
    import pyodbc  # imported lazily so CSV mode works without the driver

    conn_str = (
        f"DRIVER={{{config.DB_DRIVER}}};"
        f"SERVER={config.DB_SERVER};"
        f"DATABASE={config.DB_DATABASE};"
        "Trusted_Connection=yes;"
    )
    log.info("Connecting to %s / %s", config.DB_SERVER, config.DB_DATABASE)
    return pyodbc.connect(conn_str)


def _read_sql(sql: str, conn) -> pd.DataFrame:
    with warnings.catch_warnings():
        # pandas warns about non-SQLAlchemy connections; pyodbc works fine
        warnings.simplefilter("ignore", UserWarning)
        return pd.read_sql(sql, conn)


def load_temp_ids(conn, ids) -> None:
    """Create #TempIds and insert ids in chunks."""
    cur = conn.cursor()
    cur.execute("IF OBJECT_ID('tempdb..#TempIds') IS NOT NULL DROP TABLE #TempIds;")
    cur.execute("CREATE TABLE #TempIds (id NVARCHAR(100) PRIMARY KEY);")
    ids = list(dict.fromkeys(str(i).strip() for i in ids if str(i).strip()))
    cur.fast_executemany = True
    step = config.TEMP_IDS_CHUNK_SIZE
    for i in range(0, len(ids), step):
        cur.executemany("INSERT INTO #TempIds (id) VALUES (?)",
                        [(x,) for x in ids[i:i + step]])
    conn.commit()
    log.info("Loaded %d ids into #TempIds", len(ids))


def fetch(query_name: str, ids=None) -> pd.DataFrame:
    conn = connect_db()
    try:
        if ids:
            load_temp_ids(conn, ids)
        return _read_sql(load_query(query_name), conn)
    finally:
        conn.close()
