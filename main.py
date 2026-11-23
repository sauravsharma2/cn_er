"""China direct entries - name & address enrichment pipeline.

    python main.py                          # SQL Server -> Excel
    python main.py --input sample/sample_entries.csv
    python main.py --ids-file ids.txt       # only these IDs (via #TempIds)
    python main.py --translator none        # skip English translation
"""
import argparse
import logging
import time
from pathlib import Path

from src.code.address_enrichment import enrich_addresses
from src.code.get_cases import get_cases
from src.code.name_enrichment import enrich_names
from src.code.output_writer import write_output
from utils import config

log = logging.getLogger(config.PROJECT_NAME)


def run(input_file=None, ids=None, output=None):
    t0 = time.time()
    entries = get_cases(input_file=input_file, ids=ids)
    if entries.empty:
        log.warning("Query returned 0 rows - check the WHERE clause in queries/get_cases.sql")
        return entries, None
    entries = enrich_names(entries)
    entries = enrich_addresses(entries)
    path = write_output(entries, Path(output) if output else None)
    log.info("Done in %.1fs", time.time() - t0)
    return entries, path


def _args():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", help="CSV/Excel with id,name,native_name,address,pccity,postcode (skips SQL)")
    ap.add_argument("--ids-file", help="text file, one id per line")
    ap.add_argument("--output", help="output .xlsx path")
    ap.add_argument("--translator", choices=["hf", "ollama", "marian", "argos", "none"])
    ap.add_argument("--limit", type=int, help="first N rows only")
    return ap.parse_args()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    a = _args()
    if a.translator:
        config.TRANSLATOR = a.translator
    if a.limit:
        config.TEST_LIMIT = a.limit
    ids = Path(a.ids_file).read_text(encoding="utf-8").split() if a.ids_file else None
    run(input_file=a.input, ids=ids, output=a.output)
    
