"""Turns a submitted form into a Workable candidate and posts it.

Endpoint (verified against Workable's API docs):
  POST https://{subdomain}.workable.com/spi/v3/jobs/{shortcode}/candidates
  Authorization: Bearer <token>          (scope: w_candidates)
  body: {"sourced": true, "candidate": {...}}   -> 201 on success

Design choices that match the real-world constraints:
  * Workable REQUIRES an email. Walk-ins often don't have one, so build_candidate
    synthesizes a non-deliverable address and tags the record "no-email".
  * Custom application questions need per-job "answers" keys we can't assume, so
    every extra field is folded into the `summary` (in Greek) — HR sees everything
    regardless of how the job's form is configured.
  * Free-text answers in the candidate's language are (best-effort) translated to
    Greek so HR can read them. Translation never blocks a submission.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime

import i18n
from config import (
    DEFAULT_PHONE_CC,
    DRY_RUN,
    LOGS_DIR,
    PLACEHOLDER_EMAIL_DOMAIN,
    TRANSLITERATE_NAMES,
    WORKABLE_API_TOKEN,
    WORKABLE_INTAKE_JOB,
    WORKABLE_SOURCED,
    WORKABLE_SUBDOMAIN,
    workable_configured,
)
from fields import FIELDS

# ── helpers ──────────────────────────────────────────────────────────────────

def _normalize_phone(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return ""
    if raw.startswith("+"):
        return re.sub(r"(?!^\+)[^\d]", "", raw)
    digits = re.sub(r"\D", "", raw)
    if raw.startswith("00"):
        return "+" + digits[2:]
    digits = digits.lstrip("0")           # drop a national trunk zero before adding CC
    return f"{DEFAULT_PHONE_CC}{digits}" if digits else ""


def _synth_email(phone: str) -> str:
    """A guaranteed-ASCII, non-deliverable placeholder so Workable accepts the record."""
    digits = re.sub(r"\D", "", phone) or "unknown"
    return f"candidate.{digits}@{PLACEHOLDER_EMAIL_DOMAIN}"


def _to_latin(text: str, lang: str) -> str:
    """Romanize a non-Latin name/place to the Latin alphabet for Workable.

    Greek-speaker input is left in Greek (HR reads Greek). Already-Latin text is
    returned untouched. Otherwise: best-effort LLM romanization (best quality),
    then an offline transliterator, then the original — it never raises.
    """
    text = (text or "").strip()
    if not text or text.isascii() or lang == "el" or not TRANSLITERATE_NAMES:
        return text
    try:
        from llm import generate
        out = generate(
            "Romanize (transliterate to the Latin/English alphabet) the following "
            "name or place. Output ONLY the romanized text in Title Case, nothing else.\n\n"
            + text
        ).strip().strip('"')
        if out and out.isascii():
            return out
    except Exception as e:
        print(f"  ⚠ LLM romanization skipped: {e}")
    try:
        from unidecode import unidecode
        out = unidecode(text).strip()
        if out:
            return out.title()
    except Exception:
        pass
    return text   # original script beats nothing


def _display_value(lang: str, f: dict, raw) -> str:
    """Render a field's submitted value as Greek text for the HR-facing summary."""
    kind = f["kind"]
    if kind == "multiselect":
        vals = raw if isinstance(raw, list) else [raw]
        return ", ".join(i18n.option_label("el", f["key"], v) for v in vals if v)
    if kind == "select":
        return i18n.option_label("el", f["key"], raw)
    val = str(raw).strip()
    return _to_latin(val, lang) if f.get("romanize") else val


def _compose_address(lang: str, data: dict) -> str:
    """Compose the Workable address from the street/number/area/city/postal fields."""
    street = " ".join(p for p in [(data.get("address") or "").strip(),
                                   (data.get("address_number") or "").strip()] if p)
    parts = [street, (data.get("area") or "").strip(),
             (data.get("city") or "").strip(), (data.get("postal_code") or "").strip()]
    composed = ", ".join(p for p in parts if p)
    return _to_latin(composed, lang)


def _compose_summary(lang: str, data: dict, no_email: bool, orig_name: str | None = None) -> str:
    """Build the Greek summary block HR reads inside Workable."""
    lang_name = next((l["english_name"] for l in i18n.languages() if l["code"] == lang), lang)
    lines = [f"— Υποβλήθηκε μέσω intake app (γλώσσα υποψηφίου: {lang_name}) —"]
    if no_email:
        lines.append("⚠ Χωρίς email — επικοινωνία μέσω τηλεφώνου.")
    if orig_name:
        lines.append(f"Όνομα (πρωτότυπη γραφή): {orig_name}")
    if data.get("signed"):
        lines.append("Υπογραφή: ✔ ψηφιακή υπογραφή ελήφθη (αρχείο στο intake app)")
    lines.append("")

    for f in FIELDS:
        if f["target"] != "summary":
            continue
        raw = data.get(f["key"])
        if raw in (None, "", []):
            continue
        lines.append(f"{i18n.label('el', f['key'])}: {_display_value(lang, f, raw)}")
    return "\n".join(lines).strip()


def _experience_entries(lang: str, data: dict) -> list[dict]:
    """Map the previous-experience rows to Workable experience_entries."""
    entries = []
    for row in data.get("experience_rows") or []:
        company = _to_latin((row.get("company") or "").strip(), lang)
        position = _to_latin((row.get("position") or "").strip(), lang)
        period = (row.get("period") or "").strip()
        reason = _to_latin((row.get("reason") or "").strip(), lang)
        if not any([company, position, period, reason]):
            continue
        summary_bits = []
        if period:
            summary_bits.append(f"Διάστημα: {period}")
        if reason:
            summary_bits.append(f"Λόγος αποχώρησης: {reason}")
        entries.append({
            "title": position or "—",
            "company": company or "—",
            "summary": " · ".join(summary_bits),
        })
    return entries


# ── public API ───────────────────────────────────────────────────────────────

def build_candidate(lang: str, data: dict) -> tuple[dict, dict]:
    """Map submitted form `data` to a Workable candidate object.

    Returns (candidate, meta) where meta flags whether the email was synthesized.
    """
    first = (data.get("first_name") or "").strip()
    last = (data.get("last_name") or "").strip()
    # Romanize names so Workable's firstname/lastname are readable for Greek HR;
    # keep the original script in the summary so nothing is lost.
    first_latin = _to_latin(first, lang)
    last_latin = _to_latin(last, lang)
    romanized = (first_latin != first) or (last_latin != last)
    orig_name = f"{first} {last}".strip() if romanized else None

    phone = _normalize_phone(data.get("mobile") or "")
    email_raw = (data.get("email") or "").strip()
    no_email = not email_raw
    email = email_raw or _synth_email(phone)

    role = data.get("desired_role") or ""
    role_gr = i18n.option_label("el", "desired_role", role) if role else "Υποψήφιος"

    tags = ["intake-app", f"role:{role or 'unknown'}", f"lang:{lang}"]
    if no_email:
        tags.append("no-email")
    if i18n.needs_review(lang):
        tags.append("lang-unreviewed")

    candidate: dict = {
        "firstname": first_latin or "—",
        "lastname": last_latin or "—",
        "email": email,
        "phone": phone,
        "headline": f"{role_gr} — αίτηση (intake app)",
        "summary": _compose_summary(lang, data, no_email, orig_name),
        "tags": tags,
    }
    address = _compose_address(lang, data)
    if address:
        candidate["address"] = address
    exp = _experience_entries(lang, data)
    if exp:
        candidate["experience_entries"] = exp

    return candidate, {"no_email": no_email, "email": email}


def _friendly_error(resp) -> str:
    body = ""
    try:
        body = json.dumps(resp.json(), ensure_ascii=False)[:300]
    except Exception:
        body = (resp.text or "")[:300]
    mapping = {
        401: "Workable rejected the token (401). Check WORKABLE_API_TOKEN / its w_candidates scope.",
        404: "Workable job not found (404). Check WORKABLE_INTAKE_JOB / WORKABLE_SUBDOMAIN.",
        422: "Workable rejected the candidate data (422).",
    }
    return f"{mapping.get(resp.status_code, f'Workable error {resp.status_code}')} {body}".strip()


def _write_dryrun(payload: dict) -> None:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = re.sub(r"\W+", "-", payload["candidate"].get("lastname", "candidate")).strip("-") or "candidate"
    path = LOGS_DIR / f"dryrun-{ts}-{name}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  [DRY_RUN] wrote {path}")


def post_candidate(candidate: dict) -> tuple[bool, str | None, str | None]:
    """POST a candidate to Workable. Returns (ok, workable_id, error).

    In DRY_RUN (or when creds are absent and DRY_RUN is on) the payload is written
    to logs/ and (True, None, None) is returned. With creds missing but DRY_RUN
    off, returns a failure so the submission is queued for a real retry later.
    """
    payload = {"sourced": WORKABLE_SOURCED, "candidate": candidate}

    if DRY_RUN:
        _write_dryrun(payload)
        return True, None, None
    if not workable_configured():
        return False, None, "Workable not configured (set WORKABLE_SUBDOMAIN / WORKABLE_API_TOKEN / WORKABLE_INTAKE_JOB)."

    url = f"https://{WORKABLE_SUBDOMAIN}.workable.com/spi/v3/jobs/{WORKABLE_INTAKE_JOB}/candidates"
    headers = {
        "Authorization": f"Bearer {WORKABLE_API_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    import requests
    last_err = None
    for attempt in range(3):
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=30)
        except requests.RequestException as e:
            last_err = f"network error: {e}"
            time.sleep(2 * (attempt + 1))
            continue
        if r.status_code in (200, 201):
            wid = None
            try:
                j = r.json()
                wid = (j.get("candidate") or {}).get("id") or j.get("id")
            except Exception:
                pass
            return True, wid, None
        if r.status_code in (429, 500, 502, 503, 504):   # transient — retry
            last_err = _friendly_error(r)
            time.sleep(2 * (attempt + 1))
            continue
        return False, None, _friendly_error(r)            # 4xx — not retryable
    return False, None, last_err or "unknown error after retries"
