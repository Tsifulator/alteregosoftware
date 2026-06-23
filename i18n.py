"""Loads translations/<lang>.json and serves localized strings.

Every language is one JSON file:

  {
    "_meta": {"name": "Ελληνικά", "english_name": "Greek",
              "dir": "ltr", "flag": "🇬🇷", "needs_review": false},
    "ui":      { "submit": "...", ... },
    "labels":  { "first_name": "...", ... },     # keyed by fields.py keys
    "options": { "desired_role": {"cleaner": "...", ...}, ... }
  }

Lookups fall back to English per-key, and then to the raw key, so a brand-new or
partially-translated language never crashes the form — it just shows English (or
the key) for whatever isn't translated yet. Drop a new JSON in translations/ and
it appears in the picker automatically; no code change needed.
"""
from __future__ import annotations

import json
from pathlib import Path

TRANSLATIONS_DIR = Path(__file__).resolve().parent / "translations"
FALLBACK_LANG = "en"

# el + en lead the picker; everything else follows alphabetically by native name.
_PRIORITY = {"el": 0, "en": 1}

_cache: dict[str, dict] = {}


def _load_all() -> dict[str, dict]:
    global _cache
    if _cache:
        return _cache
    data: dict[str, dict] = {}
    for path in sorted(TRANSLATIONS_DIR.glob("*.json")):
        try:
            data[path.stem] = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            print(f"  ⚠ skipping translations/{path.name}: {e}")
    _cache = data
    return data


def reload() -> None:
    """Drop the cache (used by the admin reload + tests)."""
    global _cache
    _cache = {}


def available_codes() -> list[str]:
    return list(_load_all().keys())


def has(lang: str) -> bool:
    return lang in _load_all()


def safe_lang(lang: str | None) -> str:
    """Return lang if we have it, else the fallback. Never returns an unknown code."""
    return lang if lang and has(lang) else FALLBACK_LANG


def languages() -> list[dict]:
    """Picker data: [{code, name, english_name, dir, flag}], el/en first."""
    out = []
    for code, blob in _load_all().items():
        meta = blob.get("_meta", {})
        out.append({
            "code": code,
            "name": meta.get("name", code),
            "english_name": meta.get("english_name", code),
            "dir": meta.get("dir", "ltr"),
            "flag": meta.get("flag", "🏳"),
        })
    out.sort(key=lambda d: (_PRIORITY.get(d["code"], 99), d["name"]))
    return out


def direction(lang: str) -> str:
    return _load_all().get(safe_lang(lang), {}).get("_meta", {}).get("dir", "ltr")


def is_rtl(lang: str) -> bool:
    return direction(lang) == "rtl"


def needs_review(lang: str) -> bool:
    return bool(_load_all().get(lang, {}).get("_meta", {}).get("needs_review"))


def _lookup(lang: str, section: str, *keys: str):
    """Fetch translations[lang][section][keys...] with English fallback."""
    for code in (lang, FALLBACK_LANG):
        node = _load_all().get(code, {}).get(section)
        ok = True
        for k in keys:
            if isinstance(node, dict) and k in node:
                node = node[k]
            else:
                ok = False
                break
        if ok and isinstance(node, str):
            return node
    return None


def t(lang: str, key: str, default: str | None = None) -> str:
    """A UI string, e.g. t(lang, 'submit')."""
    return _lookup(safe_lang(lang), "ui", key) or (default if default is not None else key)


def label(lang: str, field_key: str) -> str:
    """The label for a form field, falling back to a title-cased key."""
    return _lookup(safe_lang(lang), "labels", field_key) or field_key.replace("_", " ").title()


def option_label(lang: str, field_key: str, option_key: str) -> str:
    """The label for one select option."""
    return _lookup(safe_lang(lang), "options", field_key, option_key) or option_key.replace("_", " ").title()


def section_title(lang: str, section_key: str) -> str:
    """The heading for a form section (personal/education/experience/other)."""
    return _lookup(safe_lang(lang), "sections", section_key) or section_key.title()


def exp_label(lang: str, col_key: str) -> str:
    """A column header in the previous-experience table."""
    return _lookup(safe_lang(lang), "exp", col_key) or col_key.title()
