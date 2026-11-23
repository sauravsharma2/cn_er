"""Shared Chinese text helpers: Traditional->Simplified, pinyin, English place names."""
import logging
import math
import re
import unicodedata

import jieba
import jieba.posseg as _pseg
import pandas as pd
from opencc import OpenCC
from pypinyin import Style, lazy_pinyin

jieba.setLogLevel(logging.WARNING)
_cc = OpenCC("t2s")

CJK_RE = re.compile(r"[㐀-鿿]")

# compound tokens jieba keeps whole that read better split
_SPLITS = {
    "股份有限公司": ["股份", "有限", "公司"],
    "有限责任公司": ["有限", "责任", "公司"],
    "有限公司": ["有限", "公司"],
    "集团公司": ["集团", "公司"],
    "分公司": ["分", "公司"],
}
_ADMIN_TAIL = ("省", "市", "区", "县")

# ordered longest first so "壮族自治区" wins over "区"
ADMIN_SUFFIXES = [
    "特别行政区", "维吾尔自治区", "壮族自治区", "回族自治区", "自治区",
    "自治州", "自治县", "地区", "新区", "省", "市", "区", "县", "盟", "旗",
]

_PROVINCE_EN = {
    "陕西": "Shaanxi", "内蒙古": "Inner Mongolia", "西藏": "Tibet",
    "香港": "Hong Kong", "澳门": "Macau", "台湾": "Taiwan",
}
_COUNTY_KIND = [("新区", "New Area"), ("区", "District"), ("县", "County"),
                ("市", "City"), ("旗", "Banner")]


def is_blank(x) -> bool:
    return x is None or (isinstance(x, float) and pd.isna(x)) or x is pd.NA or str(x).strip() == ""


def has_cjk(text) -> bool:
    return not is_blank(text) and bool(CJK_RE.search(str(text)))


def to_simplified(text):
    if is_blank(text):
        return pd.NA
    return _cc.convert(str(text))


def normalise_width(text: str) -> str:
    """Full-width -> half-width (（）-> (), ０-９ -> 0-9), collapse spaces."""
    text = unicodedata.normalize("NFKC", str(text))
    return re.sub(r"\s+", " ", text).strip()


def short_name(name) -> str:
    """深圳市 -> 深圳, 广西壮族自治区 -> 广西, 浦东新区 -> 浦东."""
    if is_blank(name):
        return ""
    name = str(name)
    for suf in ADMIN_SUFFIXES:
        if name.endswith(suf) and len(name) - len(suf) >= 2:
            return name[: -len(suf)]
    return name


# Words pypinyin reads wrongly (polyphonic characters in place names).
# Applied wherever pinyin is built: names, place names, pinyin address lookup.
_PY_OVERRIDE = {
    "朝阳": "chaoyang", "长治": "changzhi", "长宁": "changning", "长葛": "changge",
    "长子": "zhangzi",                      # the one 长 county read zhang
    "漯河": "luohe", "洪洞": "hongtong", "单县": "shanxian", "涡阳": "guoyang",
    "解州": "xiezhou", "什邡": "shifang", "浚县": "xunxian", "繁峙": "fanshi",
    "六安": "lu'an", "东阿": "dong'e", "西安": "xi'an", "延安": "yan'an",
    "宁都": "ningdu", "郫都": "pidu", "江都": "jiangdu", "花都": "huadu",
    "丰都": "fengdu", "新都": "xindu", "酆都": "fengdu", "望都": "wangdu",
    "铅山": "yanshan", "乐亭": "laoting", "乐清": "yueqing", "蚌埠": "bengbu",
    "番禺": "panyu", "亳州": "bozhou", "莘县": "shenxian", "尉犁": "yuli",
    "蔚县": "yuxian", "犍为": "qianwei", "枞阳": "zongyang", "大埔": "dabu",
    "柏乡": "baixiang", "句容": "jurong", "冠县": "guanxian", "茌平": "chiping",
    "筠连": "junlian", "牟平": "muping", "黄陂": "huangpi", "瑷珲": "aihui",
}


def _py(word: str) -> str:
    if word in _PY_OVERRIDE:
        return _PY_OVERRIDE[word]
    return "".join(lazy_pinyin(word, style=Style.NORMAL, errors="default", v_to_u=True))


def place_py(base: str) -> str:
    """Pinyin of a place name (short form). Adds two place-name rules on top of
    _py: a leading 长 reads chang (长沙, 长垣), a trailing 都 reads du (成都, 宁都)."""
    if not base or base in _PY_OVERRIDE:
        return _py(base)
    head, body, tail = "", base, ""
    if body.startswith("长") and len(body) >= 2:
        head, body = "chang", body[1:]
    if body.endswith("都") and len(body) >= 2:
        body, tail = body[:-1], "du"
    return head + (_py(body) if body else "") + tail


_PROPER = {"nr", "nrt", "nrfg"}   # transliterated names (阿里巴巴) stay whole


def _pos(tok: str) -> str:
    pairs = list(_pseg.cut(tok))
    return pairs[0].flag if len(pairs) == 1 else ""


def _split_long(tok: str):
    """Break long dictionary compounds (计算机系统, 华为技术有限公司) into 2-3 char words."""
    if len(tok) < 4 or not has_cjk(tok):
        return [tok]
    if len(tok) == 4 and _pos(tok) in _PROPER:      # 阿里巴巴 stays whole
        return [tok]
    jieba.dt.check_initialized()
    freq = jieba.dt.FREQ
    n = len(tok)
    best = [None] * (n + 1)          # (pieces, singles, split)
    best[0] = (0, 0, [], 0.0)
    for i in range(n):
        if best[i] is None:
            continue
        for L in (3, 2, 1):
            w = tok[i:i + L]
            if len(w) != L or (L > 1 and not freq.get(w)):
                continue
            cand = (best[i][0] + 1, best[i][1] + (L == 1), best[i][2] + [w],
                    best[i][3] + math.log(freq.get(w, 1) or 1))
            j = i + L
            if best[j] is None or (cand[1], cand[0], -cand[3]) < (best[j][1], best[j][0], -best[j][3]):
                best[j] = cand
    return best[n][2]


def _tokens(text: str):
    for tok in (p for t in jieba.lcut(text) for p in _split_long(t)):
        if tok in _SPLITS:
            yield from _SPLITS[tok]
        elif len(tok) > 2 and tok.endswith(_ADMIN_TAIL) and has_cjk(tok):
            yield tok[:-1]
            yield tok[-1]
        else:
            yield tok


def to_pinyin(text):
    """Word-level, capitalised pinyin: 深圳市腾讯有限公司 -> Shenzhen Shi Tengxun Youxian Gongsi."""
    if is_blank(text):
        return pd.NA
    text = normalise_width(text)
    parts = []
    for tok in _tokens(text):
        if not tok.strip():
            continue
        parts.append(_py(tok).capitalize() if has_cjk(tok) else tok)
    out = " ".join(parts)
    out = re.sub(r"\(\s+", "(", out)
    out = re.sub(r"\s+\)", ")", out)
    out = re.sub(r"\s+([,.;:])", r"\1", out)
    return out


def place_en(name, level: str = "city"):
    """English/pinyin form of an admin-division name."""
    if is_blank(name):
        return pd.NA
    name = str(name)
    base = short_name(name)
    if base in _PROVINCE_EN:
        return _PROVINCE_EN[base]
    en = place_py(base).capitalize()
    if level == "county":
        for suf, kind in _COUNTY_KIND:
            if name.endswith(suf) and base != name:
                return f"{en} {kind}"
    return en
