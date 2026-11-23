"""Address enrichment: parse, re-segregate, validate and fill missing fields.

Sources, in priority order:
  1. address column    (cnloc)  - any province/city/county text in it is moved out
  2. pccity column     (cnloc)  - fills gaps, conflicts are flagged
  3. postcode column   (reverse lookup) - fills gaps, mismatches flagged
  4. native name       (cnloc)  - last resort, most names start with a place
Postcodes are validated against the province and filled from a county/city table.
Everything is offline: cnloc + the china-region postcode table.
"""
import logging
import os
import re
from collections import Counter, defaultdict

import cnloc
import pandas as pd

from src.code.text_utils import (has_cjk, is_blank, normalise_width, place_en,
                                 short_name, to_simplified)
from utils import config

log = logging.getLogger(__name__)

MUNICIPALITIES = {"北京市", "上海市", "天津市", "重庆市"}
_PLACEHOLDER_CITY = {"市辖区", "县", "省直辖县级行政区划", "自治区直辖县级行政区划"}
_COUNTRY_PREFIX = re.compile(r"^(中华人民共和国|中国)")
_LEADING_JUNK = re.compile(r"^[\s,，、;；:：\-\.。()]+")
_ROAD_CHARS = tuple("路街道巷弄号里村大")   # 天河路 is a road, not 天河区
_EMPTY = {"province": None, "city": None, "county": None}


# ---------------------------------------------------------------- postcode table
class PostcodeTable:
    def __init__(self):
        import china_region
        path = os.path.join(os.path.dirname(china_region.__file__), "region.csv")
        t = pd.read_csv(path, dtype=str).fillna("")
        t = t[t["zipCode"].str.fullmatch(r"\d{6}")]

        self.by_county, self.by_prov_county, self.by_city = {}, {}, {}
        self.prov_prefixes = defaultdict(set)
        self.zip_exact = defaultdict(list)
        pre4, pre2 = defaultdict(Counter), defaultdict(Counter)
        city_rows = defaultdict(list)

        for r in t.itertuples(index=False):
            rec = (r.zipCode, r.longitude, r.latitude)
            self.by_county[(r.province, r.city, r.county)] = rec
            self.by_prov_county.setdefault((r.province, r.county), rec)
            city_rows[(r.province, r.city)].append((r.county == r.city, r.zipCode, rec))
            self.prov_prefixes[r.province].add(r.zipCode[:2])
            self.zip_exact[r.zipCode].append((r.province, r.city, r.county))
            pre4[r.zipCode[:4]][(r.province, r.city)] += 1
            pre2[r.zipCode[:2]][r.province] += 1

        for key, rows in city_rows.items():
            rows.sort(key=lambda x: (not x[0], x[1]))  # the "city itself" row first, else lowest zip
            self.by_city[key] = rows[0][2]
        self.pre4 = {k: v.most_common(1)[0][0] for k, v in pre4.items()}
        self.pre2 = {k: v.most_common(1)[0][0] for k, v in pre2.items()}

        # pinyin -> place, for English/pinyin addresses
        from src.code.text_utils import place_py
        cities, provs = defaultdict(set), defaultdict(set)
        for (p, c) in city_rows:
            cities[re.sub(r"[^a-z]", "", place_py(short_name(c)).lower())].add((p, c))
            provs[re.sub(r"[^a-z]", "", place_py(short_name(p)).lower())].add(p)
        self.pinyin_city = {k: next(iter(v)) for k, v in cities.items() if len(v) == 1 and len(k) >= 4}
        self.pinyin_prov = {k: next(iter(v)) for k, v in provs.items() if len(v) == 1 and len(k) >= 4}

    def lookup(self, loc):
        """-> (zip, lon, lat, level) for the most specific level available."""
        p, c, k = loc["province"], loc["city"], loc["county"]
        if p and k:
            rec = self.by_county.get((p, c, k)) or self.by_prov_county.get((p, k))
            if rec:
                return (*rec, "county")
        if p and c and (p, c) in self.by_city:
            return (*self.by_city[(p, c)], "city")
        return None

    def reverse(self, zipcode):
        if zipcode in self.zip_exact and len(self.zip_exact[zipcode]) == 1:
            p, c, k = self.zip_exact[zipcode][0]
            return {"province": p, "city": c, "county": k if k != c else None}
        if zipcode[:4] in self.pre4:
            p, c = self.pre4[zipcode[:4]]
            return {"province": p, "city": c, "county": None}
        if zipcode[:2] in self.pre2:
            return {"province": self.pre2[zipcode[:2]], "city": None, "county": None}
        return dict(_EMPTY)

    def from_pinyin(self, text):
        words = set(re.findall(r"[a-z]+", text.lower()))
        joined = re.sub(r"[^a-z]", "", text.lower())
        for py, (p, c) in self.pinyin_city.items():
            if py in words or (len(py) >= 6 and py in joined):
                return {"province": p, "city": c, "county": None}
        for py, p in self.pinyin_prov.items():
            if py in words:
                return {"province": p, "city": None, "county": None}
        return dict(_EMPTY)


# ---------------------------------------------------------------- helpers
def _clean(text):
    if is_blank(text):
        return None
    t = normalise_width(to_simplified(text)).replace(" ", "") if has_cjk(text) else normalise_width(text)
    t = _COUNTRY_PREFIX.sub("", t)
    return t or None


def _val(x):
    return None if is_blank(x) else str(x)


def _parse(texts):
    """cnloc on unique CJK strings -> {text: loc}"""
    uniq = sorted({t for t in texts if t and has_cjk(t)})
    if not uniq:
        return {}
    res = cnloc.getlocation(uniq, year=config.CNLOC_YEAR, mode=1, max_workers=config.CNLOC_WORKERS)
    out = {}
    for text, r in zip(uniq, res.itertuples(index=False)):
        p, c, k = _val(r.province_name), _val(r.city_name), _val(r.county_name)
        if c in _PLACEHOLDER_CITY or (c is None and p in MUNICIPALITIES):
            c = p if p in MUNICIPALITIES else None
        out[text] = {"province": p, "city": c, "county": k}
    return out


def _merge(base, extra, flags, tag, flag_conflicts=True):
    """Fill gaps in base from extra when they agree; record conflicts."""
    if not extra.get("province"):
        return base
    if not base.get("province"):
        return dict(extra)
    if base["province"] != extra["province"]:
        if flag_conflicts:
            flags.append(f"province_conflict_{tag}")
        return base
    out = dict(base)
    if not out["city"]:
        out["city"], out["county"] = extra["city"], out["county"] or extra["county"]
    elif extra["city"] and extra["city"] != out["city"]:
        if flag_conflicts:
            flags.append(f"city_conflict_{tag}")
    elif not out["county"] and extra["county"]:
        out["county"] = extra["county"]
    return out


def _strip_admin(text, loc, extra_prefixes=()):
    """Remove leading province/city/county (full or short) -> street part."""
    if not text:
        return None
    names = [n for n in (loc["province"], loc["city"], loc["county"]) if n]
    cands = set(names) | {short_name(n) for n in names} | {"市辖区"} | {p for p in extra_prefixes if p}
    shorts = {short_name(n) for n in names} - set(names)
    cands = sorted((c for c in cands if c), key=len, reverse=True)
    changed = True
    while changed and text:
        changed = False
        for c in cands:
            if text.startswith(c):
                if c in shorts and text[len(c):len(c) + 1].startswith(_ROAD_CHARS):
                    continue
                text = _LEADING_JUNK.sub("", text[len(c):])
                changed = True
                break
    return text or None


# ---------------------------------------------------------------- main entry
def enrich_addresses(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    table = PostcodeTable()

    addr = [_clean(x) for x in df["address"]]
    city_raw = [_clean(x) for x in df["pccity"]]
    name_s = [_clean(x) for x in df["native_name"]]
    # an address that sits in the city column (address blank, "city" is long)
    addr = [c if (a is None and c and len(c) > 8) else a for a, c in zip(addr, city_raw)]

    log.info("cnloc parsing: address / pccity / native name")
    p_addr, p_city, p_name = _parse(addr), _parse(city_raw), _parse(name_s)

    rows = []
    for a, c, n, pc in zip(addr, city_raw, name_s, df["postcode"]):
        flags, source = [], None
        la = p_addr.get(a, dict(_EMPTY)) if a else dict(_EMPTY)
        if a and not has_cjk(a):
            flags.append("non_chinese_address")
            la = table.from_pinyin(a)
        lc = p_city.get(c, dict(_EMPTY)) if c and has_cjk(c) else (table.from_pinyin(c) if c else dict(_EMPTY))

        zip_raw = re.sub(r"\D", "", str(pc)) if not is_blank(pc) else ""
        zip_ok = len(zip_raw) == 6
        if zip_raw and not zip_ok:
            flags.append("postcode_invalid")
        lp = table.reverse(zip_raw) if zip_ok else dict(_EMPTY)

        loc = dict(_EMPTY)
        for tag, extra, conflicts in (("address", la, True), ("pccity", lc, True),
                                      ("postcode", lp, True), ("name", p_name.get(n, _EMPTY), False)):
            before = loc["province"], loc["city"], loc["county"]
            loc = _merge(loc, extra, flags, tag, flag_conflicts=conflicts and any(before))
            if (loc["province"], loc["city"], loc["county"]) != before:
                source = source or tag
                if tag != "address" and any(before):
                    flags.append(f"filled_from_{tag}")

        # ---- postcode
        hit = table.lookup(loc)
        lon = lat = None
        if hit:
            lon, lat = hit[1], hit[2]
        if zip_ok:
            postcode = zip_raw
            if loc["province"] and zip_raw[:2] not in table.prov_prefixes.get(loc["province"], {zip_raw[:2]}):
                if hit and loc["city"]:
                    postcode = hit[0]
                    flags.append("postcode_replaced")
                else:
                    flags.append("postcode_province_mismatch")
        elif hit:
            postcode = hit[0]
            flags.append(f"postcode_filled_{hit[3]}")
        else:
            postcode = None

        # ---- street
        if a and has_cjk(a):
            street = _strip_admin(a, loc, extra_prefixes=[c])
        else:
            street = a

        rows.append({
            "street_address": street,
            "county_cn": loc["county"], "city_cn": loc["city"], "province_cn": loc["province"],
            "county": place_en(loc["county"], "county"), "city": place_en(loc["city"]),
            "province": place_en(loc["province"]),
            "postcode_enriched": postcode, "latitude": lat, "longitude": lon,
            "location_source": source,
            "enrich_flags": ";".join(dict.fromkeys(flags)) or "ok",
        })

    out = pd.concat([df, pd.DataFrame(rows, index=df.index)], axis=1)
    log.info("Address enrichment flags:\n%s",
             out["enrich_flags"].str.split(";").explode().value_counts().to_string())
    return out
