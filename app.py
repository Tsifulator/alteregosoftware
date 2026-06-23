"""ALTER EGO candidate-intake web app (FastAPI).

Flow:
  GET  /                 language picker (kiosk landing)
  GET  /form/{lang}      the intake form in that language (RTL-aware)
  POST /submit           validate -> persist -> push to Workable -> /thanks
  GET  /thanks/{lang}    confirmation; in kiosk mode auto-resets to /
  GET  /admin            PIN-gated: recent submissions + retry the failed queue
  POST /admin/retry      drain the retry queue

Mirrors the FastAPI + uvicorn style of alteregohr/reminder/app.py.
"""
from __future__ import annotations

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path

import i18n
import store
from config import (
    ADMIN_PIN,
    DRY_RUN,
    KIOSK_MODE,
    KIOSK_RESET_SECONDS,
    ORG_NAME,
    workable_configured,
)
from datetime import datetime

import signed_pdf
from fields import (FIELDS, REQUIRED_KEYS, BY_KEY, SECTIONS, fields_in,
                    EXPERIENCE_ROWS, EXPERIENCE_COLS)
from config import ATTACH_SIGNATURE_PDF
from workable_client import build_candidate, post_candidate

BASE = Path(__file__).resolve().parent
app = FastAPI(title="ALTER EGO Intake")
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE / "templates"))


def _ctx(request: Request, lang: str, **extra) -> dict:
    """Common template context: translator, direction, org name, field schema."""
    lang = i18n.safe_lang(lang)
    ctx = {
        "request": request,
        "lang": lang,
        "dir": i18n.direction(lang),
        "rtl": i18n.is_rtl(lang),
        "t": lambda key, default=None: i18n.t(lang, key, default),
        "label": lambda k: i18n.label(lang, k),
        "option_label": i18n.option_label,
        "org": ORG_NAME,
        "fields": FIELDS,
        "sections": SECTIONS,
        "fields_in": fields_in,
        "section_title": lambda s: i18n.section_title(lang, s),
        "exp_label": lambda c: i18n.exp_label(lang, c),
        "exp_rows": range(1, EXPERIENCE_ROWS + 1),
        "exp_cols": EXPERIENCE_COLS,
        "kiosk": KIOSK_MODE,
    }
    ctx.update(extra)
    return ctx


@app.get("/", response_class=HTMLResponse)
def pick_language(request: Request):
    return templates.TemplateResponse(
        request, "language.html",
        _ctx(request, "el", languages=i18n.languages()),
    )


@app.get("/form/{lang}", response_class=HTMLResponse)
def show_form(request: Request, lang: str, error: int = 0):
    return templates.TemplateResponse(
        request, "form.html",
        _ctx(request, lang, error=bool(error)),
    )


@app.post("/submit")
async def submit(request: Request):
    form = await request.form()
    lang = i18n.safe_lang(form.get("_lang"))

    # Collect values per the canonical schema (multiselect -> list).
    data: dict = {}
    for f in FIELDS:
        key = f["key"]
        if f["kind"] == "multiselect":
            data[key] = form.getlist(key)
        else:
            data[key] = (form.get(key) or "").strip()

    # Previous-experience table: exp_<row>_<col> -> list of {company,position,period,reason}.
    rows = []
    for n in range(1, EXPERIENCE_ROWS + 1):
        row = {c: (form.get(f"exp_{n}_{c}") or "").strip() for c in EXPERIENCE_COLS}
        if any(row.values()):
            rows.append(row)
    data["experience_rows"] = rows

    # Server-side required check: required fields + consent + a drawn signature.
    signature = (form.get("signature") or "").strip()
    missing = [k for k in REQUIRED_KEYS if not data.get(k)]
    if missing or not form.get("consent") or not store.is_signature(signature):
        return RedirectResponse(url=f"/form/{lang}?error=1", status_code=303)

    data["signed"] = True   # noted in the Workable summary; the image is stored separately

    # 1) Persist FIRST so the candidate's data is never lost.
    candidate, meta = build_candidate(lang, data)
    record = store.record_submission(lang, data, candidate)
    store.save_signature(record["id"], signature)

    # Attach the signature to Workable as a signed-consent PDF (the resume slot is
    # free here — candidates have no CV). Posted on a copy so submissions.json stays
    # lean. Best-effort: a PDF failure never blocks the submission.
    post_obj = candidate
    if ATTACH_SIGNATURE_PDF:
        png = signed_pdf.decode_data_url(signature)
        pdf_b64 = signed_pdf.build_pdf_b64(
            f"{candidate['firstname']} {candidate['lastname']}".strip(),
            datetime.now().strftime("%d/%m/%Y"), png) if png else None
        if pdf_b64:
            post_obj = {**candidate, "resume": {"name": f"alterego-signature-{record['id']}.pdf",
                                                "data": pdf_b64}}

    # 2) Try Workable. 3) Never show the candidate an error — queue on failure.
    ok, workable_id, err = post_candidate(post_obj)
    if ok:
        store.mark_submitted(record["id"], workable_id, dry_run=DRY_RUN)
    else:
        store.enqueue_failure(record, err or "unknown error")
        print(f"  ⚠ queued submission {record['id']} for retry: {err}")

    return RedirectResponse(url=f"/thanks/{lang}", status_code=303)


@app.get("/thanks/{lang}", response_class=HTMLResponse)
def thanks(request: Request, lang: str):
    return templates.TemplateResponse(
        request, "thanks.html",
        _ctx(request, lang, reset_seconds=KIOSK_RESET_SECONDS),
    )


# ── Admin (PIN-gated oversight) ──────────────────────────────────────────────

def _admin_ok(pin: str | None) -> bool:
    return bool(ADMIN_PIN) and pin == ADMIN_PIN


@app.get("/admin", response_class=HTMLResponse)
def admin(request: Request, pin: str = ""):
    if not ADMIN_PIN:
        return HTMLResponse("<h2>Admin disabled — set ADMIN_PIN to enable.</h2>", status_code=403)
    if not _admin_ok(pin):
        return HTMLResponse(
            "<form method='get' style='font-family:sans-serif;max-width:320px;margin:80px auto'>"
            "<h2>ALTER EGO Intake — Admin</h2>"
            "<input name='pin' type='password' placeholder='PIN' autofocus "
            "style='width:100%;padding:12px;font-size:18px'>"
            "<button style='margin-top:12px;padding:12px 20px;font-size:16px'>Enter</button></form>"
        )
    return templates.TemplateResponse(
        request, "admin.html",
        _ctx(
            request, "en",
            pin=pin,
            submissions=store.recent_submissions(100),
            queue=store.load_queue(),
            dry_run=DRY_RUN,
            configured=workable_configured(),
        ),
    )


@app.get("/admin/signature/{record_id}")
def admin_signature(record_id: str, pin: str = ""):
    """Serve a candidate's signature PNG (PIN-gated)."""
    if not _admin_ok(pin):
        return HTMLResponse("unauthorized", status_code=401)
    p = store.signature_path(record_id)
    if not p:
        return HTMLResponse("not found", status_code=404)
    return FileResponse(str(p), media_type="image/png")


@app.post("/admin/retry")
def admin_retry(pin: str = Form("")):
    if not _admin_ok(pin):
        return RedirectResponse(url="/admin", status_code=303)
    summary = store.retry_failed(lambda cand: post_candidate(cand))
    print(f"  retry summary: {summary}")
    return RedirectResponse(url=f"/admin?pin={pin}", status_code=303)


@app.get("/healthz")
def healthz():
    return {"ok": True, "workable_configured": workable_configured(), "dry_run": DRY_RUN,
            "languages": len(i18n.available_codes())}
