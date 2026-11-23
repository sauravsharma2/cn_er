"""Recover Chinese text stored as UTF-8 bytes in VARCHAR (Latin) columns.

SQL path : columns arrive as VARBINARY bytes -> decode_bytes()
CSV path : columns arrive as garbled strings ("æœ‰é™å…¬å¸") -> fix_mojibake()
Each returns (text, flag); flag is "" when nothing needed fixing.
"""
import re

import pandas as pd

_CJK = re.compile(r"[㐀-鿿]")
_WIDE = re.compile(r"[　-〿㐀-鿿＀-￯]")   # CJK + full-width punctuation
_MOJIBAKE_HINT =re.compile(r"[À-ÿ][\u0080-ÿŒ-˜–-™]")


def _clean(text: str):
    text = text.replace("\x00", "").strip()
    return text or pd.NA


_BAD = re.compile(r"[\x00-\x08\x0a-\x1f\x7f\ue000-\uf8ff\ufffd]")   # controls, private use


def _looks_ok(text: str) -> bool:
    return not _BAD.search(text)


def decode_bytes(value):
    """VARBINARY from SQL Server -> (text, flag).
    VARCHAR columns hold UTF-8 (sometimes GBK); NVARCHAR columns cast to UTF-16-LE."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return pd.NA, ""
    if isinstance(value, str):                     # already text
        return fix_mojibake(value)
    b = bytes(value)
    if not b:
        return pd.NA, ""
    try:
        text = b.decode("utf-8")
        if _looks_ok(text):
            return _clean(text), ("utf8_decoded" if _CJK.search(text) else "")
    except UnicodeDecodeError:
        text = None
    if len(b) % 2 == 0:
        try:
            t16 = b.decode("utf-16-le")
            if _looks_ok(t16):
                return _clean(t16), ""
        except UnicodeDecodeError:
            pass
    if text is not None:                           # valid UTF-8 with odd control chars
        return _clean(text), ("utf8_decoded" if _CJK.search(text) else "")
    try:
        return _clean(b.decode("gb18030")), "gbk_decoded"
    except UnicodeDecodeError:
        return _clean(b.decode("utf-8", errors="replace")), "unrecoverable"


def _to_cp1252_bytes(text: str) -> bytes:
    out = bytearray()
    for ch in text:
        if ord(ch) < 256:
            out.append(ord(ch))                    # incl. the 5 bytes cp1252 leaves undefined
        else:
            out += ch.encode("cp1252")             # € ‚ ƒ „ … † ‡ ˆ ‰ Š ‹ Œ Ž ‘ ’ “ ” • – — ˜ ™ š › œ ž Ÿ
    return bytes(out)


def fix_mojibake(text):
    """Garbled string -> (text, flag). Leaves good text untouched."""
    if text is None or (isinstance(text, float) and pd.isna(text)) or text is pd.NA:
        return pd.NA, ""
    text = str(text)
    if _CJK.search(text) or not _MOJIBAKE_HINT.search(text):
        return _clean(text), ""
    try:
        fixed = _to_cp1252_bytes(text).decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return _clean(text), "unrecoverable"
    return (_clean(fixed), "mojibake_fixed") if _WIDE.search(fixed) else (_clean(text), "")
