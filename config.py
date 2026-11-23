"""Run configuration for the China direct entries enrichment pipeline."""
from pathlib import Path

PROJECT_NAME = "china_direct_entries"

# ---------------------------------------------------------------- paths
ROOT_DIR = Path(__file__).resolve().parents[1]
QUERIES_DIR = ROOT_DIR / "queries"
OUTPUT_DIR = ROOT_DIR / "output"
CACHE_DIR = ROOT_DIR / "cache"
OUTPUT_FILE = OUTPUT_DIR / "china_direct_entries_enriched.xlsx"

# ---------------------------------------------------------------- database
# Windows authentication (Trusted_Connection) - no user/password needed.
DB_DRIVER = "ODBC Driver 17 for SQL Server"
DB_SERVER = "YOUR_SERVER_NAME"
DB_DATABASE = "YOUR_DATABASE_NAME"

GET_CASES_QUERY = "get_cases.sql"
GET_CASES_BY_IDS_QUERY = "get_cases_by_ids.sql"
TEMP_IDS_CHUNK_SIZE = 1000          # rows per INSERT batch into #TempIds

# Limit rows for a quick test run (None = everything)
TEST_LIMIT = None

# ---------------------------------------------------------------- translation
# "ollama"  -> local LLM through Ollama (best quality)       [default]
# "marian"  -> Helsinki-NLP/opus-mt-zh-en via transformers (CPU fallback)
# "none"    -> skip translation (column left empty)
TRANSLATOR = "ollama"
OLLAMA_URL = "http://localhost:11434/api/chat"
OLLAMA_MODEL = "qwen3:8b"           # smaller/faster: "qwen3:4b"
OLLAMA_TIMEOUT = 300
TRANSLATE_BATCH_SIZE = 10           # names per LLM request
MARIAN_MODEL = "Helsinki-NLP/opus-mt-zh-en"
TRANSLATION_CACHE = CACHE_DIR / "translation_cache.json"

# ---------------------------------------------------------------- address
CNLOC_YEAR = 2025                   # admin-division vintage used by cnloc
CNLOC_WORKERS = 4

# ---------------------------------------------------------------- output
EXCEL_MAX_ROWS = 1_000_000          # split sheets above this
