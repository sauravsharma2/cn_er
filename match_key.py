"""Native-name normalisation for exact matching.

    display name : brackets removed -> Simplified (OpenCC t2s, only if Chinese) -> NFKC,
                   spaces kept. Written to the output as simplified_chinese_name.
    match key    : display name with every space removed, upper-cased (so English
                   names compare case-insensitively). Internal only, never written.

Only the bracket characters are removed; the text inside them stays.
"""
import re

import pandas as pd

from src.code.text_utils import has_cjk, is_blank, normalise_width, to_simplified

# every bracket type, half- and full-width
_BRACKETS = re.compile(r"[()（）\[\]［］【】{}｛｝〔〕〖〗《》〈〉<>＜＞「」『』]")
# a key must hold at least one letter, digit or Chinese character
_CONTENT = re.compile(r"[0-9A-Za-z㐀-鿿]")


def remove_brackets(text: str) -> str:
    return _BRACKETS.sub("", text)


def display_name(native):
    """Native name -> simplified_chinese_name (spaces kept)."""
    if is_blank(native):
        return pd.NA
    text = remove_brackets(str(native))
    if has_cjk(text):
        text = to_simplified(text)
    # NFKC can turn some characters into brackets (e.g. ⑴ -> (1)), so strip again
    text = normalise_width(remove_brackets(normalise_width(text)))
    return text or pd.NA


def match_key(display):
    """simplified_chinese_name -> exact-match key, or None when there is nothing to match on."""
    if is_blank(display):
        return None
    key = str(display).replace(" ", "").upper()
    return key if _CONTENT.search(key) else None


def key_kind(key) -> str:
    """chinese / english / blank - for the console counts."""
    if is_blank(key):
        return "blank"
    return "chinese" if has_cjk(key) else "english"
