"""Push a scheduled interview to the alteregohr/reminder app.

When an intake submission carries an interview date/time, we POST it to the
reminder app's `/appointments` endpoint, which saves it to the interview calendar
and schedules the bilingual reminder SMS (Greek + the candidate's language) via
Twilio. This is best-effort: a failure here never blocks the candidate — the
outcome is stored on the submission and shown in /admin for HR to retry or to add
manually in the reminder app's own calendar.
"""
from __future__ import annotations

import json
import re
from datetime import datetime

from config import (
    DRY_RUN,
    LOGS_DIR,
    REMINDER_API_KEY,
    REMINDER_API_URL,
    REMINDER_ENABLED,
)

# Reminder-app statuses that mean "the interview was accepted / reminders planned".
_OK_STATUSES = {"scheduled", "dry", "now", "deferred", "already_scheduled", "past"}


def to_iso(raw: str) -> str | None:
    """Normalize a datetime-local value to ISO the reminder app accepts (no tz —
    it applies Europe/Athens). Returns None if blank/unparseable."""
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw).isoformat()
    except (ValueError, TypeError):
        return None


def _write_dryrun(payload: dict) -> None:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = re.sub(r"\W+", "-", payload.get("name", "candidate")).strip("-") or "candidate"
    path = LOGS_DIR / f"reminder-{ts}-{name}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  [reminder DRY] wrote {path}")


def schedule_interview(name: str, first_name: str, phone: str,
                       interview_at: str, lang: str) -> tuple[bool, int | None, str, str]:
    """POST an appointment to the reminder app. Returns (ok, appointment_id, status, detail).

    No-op (returns disabled) when reminders aren't configured. Writes the payload to
    logs/ instead of calling out when DRY_RUN. Never raises.
    """
    iso = to_iso(interview_at)
    if not iso:
        return False, None, "no_interview", "no interview date/time provided"

    payload = {
        "name": name,
        "first_name": first_name,
        "phone": phone,
        "datetime_iso": iso,
        "preferred_language": (lang or "el").lower(),
    }

    if DRY_RUN:
        _write_dryrun(payload)
        return True, None, "dry", f"[DRY_RUN] would schedule interview {iso} ({payload['preferred_language']})"
    if not REMINDER_ENABLED:
        return False, None, "disabled", "reminders not configured (set REMINDER_API_URL)"

    import requests
    headers = {"Content-Type": "application/json"}
    if REMINDER_API_KEY:
        headers["X-API-Key"] = REMINDER_API_KEY
    try:
        r = requests.post(f"{REMINDER_API_URL}/appointments", json=payload,
                          headers=headers, timeout=10)
    except requests.RequestException as e:
        return False, None, "unreachable", f"reminder app unreachable: {e}"

    if r.status_code == 401:
        return False, None, "unauthorized", "reminder app rejected the API key (401)"
    try:
        data = r.json()
    except ValueError:
        return False, None, "bad_response", f"reminder app returned HTTP {r.status_code}"

    status = data.get("status", "error")
    detail = data.get("detail", "")
    ok = status in _OK_STATUSES
    return ok, data.get("appointment_id"), status, detail
