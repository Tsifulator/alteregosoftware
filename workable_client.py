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
    TRANSLATE_FREETEXT,
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


def _translate_to_greek(text: str) -> str | None:
    """Best-effort translation to Greek. Returns None on any problem — never raises."""
    if not TRANSLATE_FREETEXT or not text.strip():
        return None
    try:
        from llm import generate
        out = generate(
            "Translate the following text to Greek. "
            "Output ONLY the Greek translation, no notes, no quotes.\n\n" + text
        ).strip()
        return out or None
    except Exception as e:                # backend down, no key, timeout — degrade gracefully
        print(f"  ⚠ translation skipped: {e}")
        return None


def _value_in_greek(key: str, raw, kind: str) -> str:
    """Render a field's submitted value as Greek text for the HR-facing summary."""
    if kind == "multiselect":
        vals = raw if isinstance(raw, list) else [raw]
        return ", ".join(i18n.option_label("el", key, v) for v in vals if v)
    if kind == "select":
        return i18n.option_label("el", key, raw)
    return str(raw).strip()


def _compose_summary(lang: str, data: dict, no_email: bool) -> str:
    """Build the Greek summary block HR reads inside Workable."""
    lang_name = next((l["english_name"] for l in i18n.languages() if l["code"] == lang), lang)
    lines = [f"— Υποβλήθηκε μέσω intake app (γλώσσα υποψηφίου: {lang_name}) —"]
    if no_email:
        lines.append("⚠ Χωρίς email — επικοινωνία μέσω τηλεφώνου.")
    lines.append("")

    for f in FIELDS:
        if f["target"] != "summary":
            continue
        key = f["key"]
        raw = data.get(key)
        if raw in (None, "", []):
            continue
        gr_label = i18n.label("el", key)
        if f.get("freetext"):
            lines.append(f"{gr_label}:")
            lines.append(str(raw).strip())
            translated = None if lang == "el" else _translate_to_greek(str(raw))
            if translated:
                lines.append(f"[μετάφραση] {translated}")
        else:
            lines.append(f"{gr_label}: {_value_in_greek(key, raw, f['kind'])}")
    return "\n".join(lines).strip()


def _experience_entries(lang: str, data: dict) -> list[dict]:
    exp = (data.get("experience") or "").strip()
    if not exp:
        return []
    body = exp
    if lang != "el":
        tr = _translate_to_greek(exp)
        if tr:
            body = f"{exp}\n\n[EL] {tr}"
    role = data.get("desired_role") or ""
    title = i18n.option_label("el", "desired_role", role) if role else "Προηγούμενη εμπειρία"
    return [{"title": title or "Προηγούμενη εμπειρία", "summary": body}]


# ── public API ───────────────────────────────────────────────────────────────

def build_candidate(lang: str, data: dict) -> tuple[dict, dict]:
    """Map submitted form `data` to a Workable candidate object.

    Returns (candidate, meta) where meta flags whether the email was synthesized.
    """
    first = (data.get("first_name") or "").strip()
    last = (data.get("last_name") or "").strip()
    phone = _normalize_phone(data.get("phone") or "")
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
        "firstname": first or "—",
        "lastname": last or "—",
        "email": email,
        "phone": phone,
        "headline": f"{role_gr} — αίτηση (intake app)",
        "summary": _compose_summary(lang, data, no_email),
        "tags": tags,
    }
    area = (data.get("area") or "").strip()
    if area:
        candidate["address"] = area
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
