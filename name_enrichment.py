"""Name columns: Simplified Chinese, Pinyin, English translation."""
import logging

import pandas as pd

from src.code.text_utils import normalise_width, to_pinyin, to_simplified
from src.code.translator import translate_names

log = logging.getLogger(__name__)


def enrich_names(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    simp = df["native_name"].map(to_simplified)
    df["simplified_name"] = simp.map(lambda s: s if pd.isna(s) else normalise_width(s))
    log.info("Pinyin for %d names", df["simplified_name"].notna().sum())
    df["pinyin_name"] = df["simplified_name"].map(to_pinyin)

    mapping = translate_names(df["simplified_name"].dropna().tolist())
    df["english_name"] = df["simplified_name"].map(lambda s: mapping.get(s, pd.NA) if pd.notna(s) else pd.NA)
    df["english_name"] = df["english_name"].replace({"": pd.NA})
    return df
