"""Local persistence — the "never lose a candidate" safety net.

Two JSON files (mirrors the siblings' sent_log.py approach):

  submissions.json  every submission ever made, with status — the audit trail.
  queue.json        only the submissions that failed to reach Workable and are
                    waiting for a retry.

Flow on submit: record_submission() writes to submissions.json FIRST (so the data
exists no matter what happens next); then the caller tries Workable and calls
mark_submitted() or enqueue_failure() with the outcome. retry_failed() drains the
queue later (from /admin or a scheduled sweep).

Writes are atomic (temp file + os.replace) and guarded by a process lock so a
double-tap on the kiosk can't corrupt the file.
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone

from config import SUBMISSIONS_PATH, QUEUE_PATH

_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def _read(path) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _write(path, rows: list[dict]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)   # atomic on POSIX — no half-written file is ever read


def load_submissions() -> list[dict]:
    return _read(SUBMISSIONS_PATH)


def load_queue() -> list[dict]:
    return _read(QUEUE_PATH)


def record_submission(lang: str, data: dict, candidate: dict) -> dict:
    """Persist a new submission as 'pending' and return the stored record."""
    record = {
        "id": new_id(),
        "ts": _now_iso(),
        "lang": lang,
        "name": f"{data.get('first_name', '')} {data.get('last_name', '')}".strip(),
        "data": data,
        "candidate": candidate,
        "status": "pending",
        "workable_id": None,
        "error": None,
        "attempts": 0,
        # Interview reminder (set later if the form carried an interview date/time).
        "interview_at": (data.get("interview_at") or None),
        "reminder_status": None,
        "appointment_id": None,
        "reminder_detail": None,
    }
    with _lock:
        rows = _read(SUBMISSIONS_PATH)
        rows.append(record)
        _write(SUBMISSIONS_PATH, rows)
    return record


def _update(record_id: str, **changes) -> None:
    with _lock:
        rows = _read(SUBMISSIONS_PATH)
        for r in rows:
            if r["id"] == record_id:
                r.update(changes)
                break
        _write(SUBMISSIONS_PATH, rows)


def mark_submitted(record_id: str, workable_id: str | None, dry_run: bool = False) -> None:
    _update(
        record_id,
        status="dry_run" if dry_run else "submitted",
        workable_id=workable_id,
        error=None,
        attempts=_bump_attempts(record_id),
    )
    _dequeue(record_id)


def set_reminder(record_id: str, status: str, appointment_id=None, detail: str = "") -> None:
    """Record the outcome of pushing the interview to the reminder app."""
    _update(record_id, reminder_status=status, appointment_id=appointment_id,
            reminder_detail=detail)


def enqueue_failure(record: dict, error: str) -> None:
    """Mark a submission failed and add it to the retry queue (idempotent)."""
    rid = record["id"]
    _update(rid, status="queued", error=error, attempts=_bump_attempts(rid))
    with _lock:
        q = _read(QUEUE_PATH)
        if not any(r["id"] == rid for r in q):
            q.append({"id": rid, "lang": record["lang"], "candidate": record["candidate"],
                      "name": record.get("name", ""), "queued_at": _now_iso()})
            _write(QUEUE_PATH, q)


def _bump_attempts(record_id: str) -> int:
    rows = _read(SUBMISSIONS_PATH)
    for r in rows:
        if r["id"] == record_id:
            return r.get("attempts", 0) + 1
    return 1


def _dequeue(record_id: str) -> None:
    with _lock:
        q = _read(QUEUE_PATH)
        new_q = [r for r in q if r["id"] != record_id]
        if len(new_q) != len(q):
            _write(QUEUE_PATH, new_q)


def retry_failed(post_fn) -> dict:
    """Re-send every queued submission via post_fn(candidate) -> (ok, workable_id, err).

    Returns a {"retried", "succeeded", "failed"} summary. Successful ones are
    removed from the queue and their submission record is marked submitted.
    """
    queue = load_queue()
    succeeded = 0
    for item in queue:
        ok, workable_id, err = post_fn(item["candidate"])
        if ok:
            mark_submitted(item["id"], workable_id)
            succeeded += 1
        else:
            _update(item["id"], error=err, attempts=_bump_attempts(item["id"]))
    return {"retried": len(queue), "succeeded": succeeded, "failed": len(queue) - succeeded}


def recent_submissions(limit: int = 50) -> list[dict]:
    return list(reversed(load_submissions()))[:limit]
