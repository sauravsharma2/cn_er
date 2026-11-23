"""Chinese company name -> English, fully local and free.

Backends (utils.config.TRANSLATOR):
  ollama : local LLM (default qwen3:8b) - best quality, needs Ollama running
  marian : Helsinki-NLP/opus-mt-zh-en on CPU - lower quality fallback
  none   : skip
A legal-form dictionary enforces consistent suffixes regardless of backend,
and every result is cached on disk so re-runs only translate new names.
"""
import json
import logging
import re

import requests

from src.code.text_utils import CJK_RE
from utils import config

log = logging.getLogger(__name__)

# Chinese legal-form ending -> canonical English ending (longest first)
LEGAL_FORMS = [
    ("集团股份有限公司", "Group Co., Ltd."),
    ("集团有限公司", "Group Co., Ltd."),
    ("股份有限公司", "Co., Ltd."),
    ("有限责任公司", "Co., Ltd."),
    ("有限公司", "Co., Ltd."),
    ("(有限合伙)", "(Limited Partnership)"),
    ("分公司", "Branch"),
    ("集团公司", "Group Corporation"),
    ("总公司", "Corporation"),
    ("公司", "Company"),
]

# variants the model may produce for the same ending
_EN_VARIANTS = re.compile(
    r"[\s,]*(?:"
    r"(?:Joint[- ]Stock\s+)?(?:Co(?:mpany)?\.?\s*,?\s*(?:Ltd|Limited)\.?)|"
    r"(?:Limited\s+(?:Liability\s+)?Company)|"
    r"(?:Company\s+Limited)|"
    r"(?:Ltd\.?|Limited)|"
    r"(?:Co\.?)"
    r")\s*$",
    re.IGNORECASE,
)

SYSTEM_PROMPT = """You translate Chinese company names into natural, professional English as used in business registries.
Rules:
- Romanise place names in pinyin without tones (深圳 -> Shenzhen, 浦东 -> Pudong). Drop 市/省 after a place name.
- Translate descriptive and industry words (科技 -> Technology, 贸易 -> Trading, 电器 -> Electric, 新能源 -> New Energy).
- Brand/trade names: use the well-known English brand only if you are certain (腾讯 -> Tencent, 华为 -> Huawei, 字节跳动 -> ByteDance); otherwise romanise in pinyin.
- Legal forms: 有限公司/有限责任公司/股份有限公司 -> Co., Ltd.; 集团 -> Group; 分公司 -> Branch.
- Keep brackets: 阿里巴巴（中国）有限公司 -> Alibaba (China) Co., Ltd.
- Output only the translation. No explanations.
Return JSON: {"1": "...", "2": "...", ...} with one entry per input number."""


def normalise_suffix(en: str, zh: str) -> str:
    """Force the English legal ending to match the Chinese one."""
    if not en:
        return en
    zh = zh.replace("（", "(").replace("）", ")")
    for zh_end, en_end in LEGAL_FORMS:
        if zh.endswith(zh_end):
            if en_end.endswith("Co., Ltd."):
                core = _EN_VARIANTS.sub("", en).strip().rstrip(",")
                if en_end.startswith("Group") and core.lower().endswith("group"):
                    core = core[: -len("group")].strip()
                return f"{core} {en_end}".strip()
            break
    return en.strip()


class _Cache:
    def __init__(self, path):
        self.path = path
        try:
            self.data = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            self.data = {}

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=0), encoding="utf-8")


class OllamaTranslator:
    def __init__(self):
        self.url, self.model = config.OLLAMA_URL, config.OLLAMA_MODEL
        try:
            requests.get(self.url.replace("/api/chat", "/api/tags"), timeout=5).raise_for_status()
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(
                f"Ollama not reachable at {self.url}. Start it and run `ollama pull {self.model}`."
            ) from e

    def _call(self, names):
        payload = {
            "model": self.model,
            "stream": False,
            "think": False,
            "format": "json",
            "options": {"temperature": 0},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": "\n".join(f"{i}. {n}" for i, n in enumerate(names, 1))},
            ],
        }
        r = requests.post(self.url, json=payload, timeout=config.OLLAMA_TIMEOUT)
        r.raise_for_status()
        content = r.json()["message"]["content"]
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()
        data = json.loads(content)
        return [str(data.get(str(i), "")).strip() for i in range(1, len(names) + 1)]

    def translate(self, names):
        try:
            out = self._call(names)
            if all(out):
                return out
        except Exception as e:  # noqa: BLE001
            log.warning("Batch translation failed (%s); retrying one by one", e)
        result = []
        for n in names:
            try:
                result.append(self._call([n])[0])
            except Exception as e:  # noqa: BLE001
                log.warning("Could not translate %s: %s", n, e)
                result.append("")
        return result


class MarianTranslator:
    def __init__(self):
        from transformers import pipeline
        self.pipe = pipeline("translation", model=config.MARIAN_MODEL)

    def translate(self, names):
        return [r["translation_text"] for r in self.pipe(list(names), batch_size=16)]


def translate_names(names):
    """names: iterable of Simplified Chinese names -> dict {zh: en}."""
    unique = sorted({n for n in names if n})
    if config.TRANSLATOR == "none" or not unique:
        return {}

    cache = _Cache(config.TRANSLATION_CACHE)
    key = f"{config.TRANSLATOR}:{config.OLLAMA_MODEL if config.TRANSLATOR == 'ollama' else config.MARIAN_MODEL}"
    store = cache.data.setdefault(key, {})
    todo = [n for n in unique if n not in store]
    log.info("Translation: %d unique names, %d cached, %d to translate",
             len(unique), len(unique) - len(todo), len(todo))

    if todo:
        engine = OllamaTranslator() if config.TRANSLATOR == "ollama" else MarianTranslator()
        step = config.TRANSLATE_BATCH_SIZE
        for i in range(0, len(todo), step):
            batch = todo[i:i + step]
            for zh, en in zip(batch, engine.translate(batch)):
                if en and not CJK_RE.search(en):      # still Chinese = failed translation
                    store[zh] = normalise_suffix(en, zh)
            if (i // step) % 20 == 0:
                cache.save()
                log.info("  translated %d/%d", min(i + step, len(todo)), len(todo))
        cache.save()

    return {n: store.get(n, "") for n in unique}
