# China direct entries – name & address enrichment

```
├── main.py                       orchestrator; run() is the whole pipeline
├── run_finalize.py               artifact declaration -> output/run_manifest.json
├── requirements.txt
├── descriptor.yaml               run metadata
├── src/
│   ├── code/
│   │   ├── get_cases.py              Entries frame from get_cases.sql (or CSV/Excel)
│   │   ├── name_enrichment.py        Simplified / Pinyin / English name columns
│   │   ├── translator.py             local LLM (Ollama) or Marian, legal-suffix dictionary, cache
│   │   ├── address_enrichment.py     cnloc parsing, re-segregation, postcode validate/fill
│   │   ├── text_utils.py             OpenCC, pinyin segmentation, English place names
│   │   └── output_writer.py          Excel writing, sheet splitting, Flag Summary
│   └── db_connexion/
│       └── data_extraction.py        load_query, connect_db (Windows auth), #TempIds chunking
├── utils/
│   └── config.py                 PROJECT_NAME, run configuration
├── queries/
│   ├── get_cases.sql
│   └── get_cases_by_ids.sql
└── sample/sample_entries.csv     10 test rows (no DB needed)
```

## Setup (Windows PC)

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Translation model (free, runs locally, nothing leaves the PC):
1. Install Ollama: https://ollama.com/download
2. `ollama pull qwen3:8b`   (≈5 GB; on a slow CPU use `qwen3:4b` and set `OLLAMA_MODEL` in config)
3. Ollama runs in the background on `localhost:11434`.

Set `DB_SERVER` / `DB_DATABASE` in `utils/config.py`. Check the table name in `queries/get_cases.sql`.

## Run

```bat
python main.py --input sample\sample_entries.csv --translator none   :: quick test, no model
python main.py --limit 200                                            :: first 200 rows from SQL
python main.py                                                         :: full run
python main.py --ids-file ids.txt                                      :: selected IDs via #TempIds
python run_finalize.py                                                 :: manifest
```

Translations are cached in `cache/translation_cache.json`, so re-runs only translate new names.

## Output columns

| Column | How |
|---|---|
| Simplified Chinese Name | OpenCC t2s + full-width → half-width |
| Pinyin Name | jieba word segmentation + pypinyin, capitalised per word |
| English Translated Name | local LLM, legal form forced by dictionary (有限公司 → Co., Ltd.) |
| Company Street Address | address with province/city/district removed |
| Company District / City / State | cnloc on address → pccity → postcode → native name |
| Company Postcode | raw if valid and matches province, else filled from district/city table |
| Latitude / Longitude | district (or city) centroid |
| Location Source | which column the location came from |
| Enrich Flags | see below |

## Flags

| Flag | Meaning |
|---|---|
| ok | nothing changed or filled |
| postcode_filled_county / _city | postcode was missing, filled at that level |
| postcode_replaced | raw postcode belonged to another province; replaced |
| postcode_province_mismatch | same, but not enough address detail to replace |
| postcode_invalid | raw postcode not 6 digits |
| filled_from_pccity / _postcode / _name | a level missing from the address was filled from that source |
| city_conflict_pccity, province_conflict_pccity | pccity disagrees with the address (address kept) |
| non_chinese_address | English/pinyin address; location matched on pinyin city names |

## Limits
- Postcodes from the table are district-level, not delivery-precise.
- No street-level geocoding: free offline options don't exist for China; Amap/Baidu need an API key and send data outside.
- The English name is a translation, not the official registered English name.
