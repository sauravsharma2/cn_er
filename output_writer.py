"""Excel writing with sheet splitting."""
import logging

import pandas as pd

from utils import config

log = logging.getLogger(__name__)

OUTPUT_COLUMNS = {
    "id": "ID",
    "name": "Name",
    "native_name": "Native Name",
    "simplified_name": "Simplified Chinese Name",
    "pinyin_name": "Pinyin Name",
    "english_name": "English Translated Name",
    "address": "Raw Address",
    "pccity": "Raw City",
    "postcode": "Raw Postcode",
    "street_address": "Company Street Address",
    "county": "Company District / County",
    "city": "Company City",
    "province": "Company State / Province",
    "postcode_enriched": "Company Postcode",
    "county_cn": "District (CN)",
    "city_cn": "City (CN)",
    "province_cn": "Province (CN)",
    "latitude": "Latitude",
    "longitude": "Longitude",
    "location_source": "Location Source",
    "enrich_flags": "Enrich Flags",
    "encoding_flag": "Encoding Flag",
}


def write_output(df: pd.DataFrame, path=None):
    path = path or config.OUTPUT_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    out = df[[c for c in OUTPUT_COLUMNS if c in df.columns]].rename(columns=OUTPUT_COLUMNS)

    flags = (out["Enrich Flags"].str.split(";").explode().value_counts()
             .rename_axis("Flag").reset_index(name="Rows"))

    step = config.EXCEL_MAX_ROWS
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        for i, start in enumerate(range(0, max(len(out), 1), step), 1):
            name = "Entries" if len(out) <= step else f"Entries_{i}"
            out.iloc[start:start + step].to_excel(xw, sheet_name=name, index=False)
            ws = xw.sheets[name]
            ws.freeze_panes = "B2"
            for col in ws.columns:
                width = max(len(str(c.value or "")) for c in list(col)[:200])
                ws.column_dimensions[col[0].column_letter].width = min(max(width + 2, 10), 60)
        flags.to_excel(xw, sheet_name="Flag Summary", index=False)
    log.info("Wrote %d rows -> %s", len(out), path)
    return path
    
