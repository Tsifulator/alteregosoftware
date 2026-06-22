#!/usr/bin/env python3
"""Generate a translations/<code>.json from the English base via the local-first LLM.

Use this to ADD a new language (or regenerate a machine one) without hand-typing.
It walks translations/en.json, translates each string value into the target
language (keeping brand/keys intact), and writes the file flagged needs_review.

  python tools/gen_translations.py de "Deutsch" "German"            # LTR
  python tools/gen_translations.py he "עברית" "Hebrew" rtl "🇮🇱"     # RTL + flag

Honest defaults: the output is machine translation — keep "needs_review": true
until a native speaker checks it. el.json and en.json are hand-authored; don't
overwrite them with this.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from llm import generate  # noqa: E402

TRANS = ROOT / "translations"
KEEP_VERBATIM = ["ALTER EGO", "Workable", "AMKA", "AFM"]


def translate(text: str, english_name: str, cache: dict) -> str:
    if not text.strip():
        return text
    if text in cache:
        return cache[text]
    prompt = (
        f"Translate the following UI text into {english_name}. "
        f"Keep these terms unchanged: {', '.join(KEEP_VERBATIM)}. "
        "Keep any emoji and the leading/trailing punctuation. "
        "Output ONLY the translation on a single line, nothing else.\n\n" + text
    )
    out = generate(prompt).strip().strip('"')
    cache[text] = out or text
    return cache[text]


def walk(node, english_name: str, cache: dict):
    if isinstance(node, str):
        return translate(node, english_name, cache)
    if isinstance(node, dict):
        return {k: walk(v, english_name, cache) for k, v in node.items()}
    if isinstance(node, list):
        return [walk(v, english_name, cache) for v in node]
    return node


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(1)
    code, native, english = sys.argv[1], sys.argv[2], sys.argv[3]
    direction = sys.argv[4] if len(sys.argv) > 4 else "ltr"
    flag = sys.argv[5] if len(sys.argv) > 5 else "🏳"

    if code in ("el", "en"):
        print(f"Refusing to overwrite hand-authored {code}.json"); sys.exit(1)

    base = json.loads((TRANS / "en.json").read_text(encoding="utf-8"))
    cache: dict = {}
    out = {
        "_meta": {"name": native, "english_name": english, "dir": direction,
                  "flag": flag, "needs_review": True},
        "ui": walk(base["ui"], english, cache),
        "labels": walk(base["labels"], english, cache),
        "options": walk(base["options"], english, cache),
    }
    dest = TRANS / f"{code}.json"
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"✓ wrote {dest} ({len(cache)} strings translated) — review before production use.")


if __name__ == "__main__":
    main()
