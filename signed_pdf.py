"""Wrap a candidate's drawn signature into a small signed-consent PDF.

Workable's `resume` file slot accepts PDF (not images) and is free in this flow
(candidates have no CV), so we attach a one-page "application signature & consent"
PDF there — a real signed document on the Workable profile. Text is ASCII-only
(romanized) so the core PDF font renders it on any platform; the signature itself
is the drawn image. Best-effort: returns None on any problem, never raises.
"""
from __future__ import annotations

import base64
import io


def decode_data_url(data_url: str) -> bytes | None:
    """'data:image/png;base64,…' -> PNG bytes (None if invalid)."""
    if not data_url or "," not in data_url or not data_url.startswith("data:image"):
        return None
    try:
        raw = base64.b64decode(data_url.split(",", 1)[1], validate=True)
        return raw or None
    except Exception:
        return None


def _ascii(text: str) -> str:
    """Latin-1-safe text for the core PDF font (romanize, then drop anything left)."""
    try:
        from unidecode import unidecode
        text = unidecode(text or "")
    except Exception:
        pass
    return (text or "").encode("latin-1", "replace").decode("latin-1")


def build_pdf(name: str, when: str, png_bytes: bytes) -> bytes | None:
    """Return a one-page PDF (header + name/date + consent + signature image)."""
    if not png_bytes:
        return None
    try:
        from fpdf import FPDF
        pdf = FPDF(format="A4")
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()

        pdf.set_font("Helvetica", "B", 16)
        pdf.cell(0, 10, "ALTER EGO - Facilities Management", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 11)
        pdf.cell(0, 7, "Candidate application - signature & consent", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)

        pdf.set_font("Helvetica", "", 11)
        pdf.cell(0, 7, f"Name: {_ascii(name)}", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 7, f"Date: {_ascii(when)}", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)

        pdf.set_font("Helvetica", "", 9)
        pdf.multi_cell(0, 5,
            "I have read ALTER EGO's notice on the processing of personal data and I "
            "consent to the processing of my data for recruitment purposes (EU Reg. "
            "2016/679). I declare that the information I submitted is true.")
        pdf.ln(5)

        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(0, 7, "Signature:", new_x="LMARGIN", new_y="NEXT")
        pdf.image(io.BytesIO(png_bytes), w=95)   # drawn signature

        return bytes(pdf.output())
    except Exception as e:                       # missing dep / bad image — skip, never break
        print(f"  ⚠ signature PDF skipped: {e}")
        return None


def build_pdf_b64(name: str, when: str, png_bytes: bytes) -> str | None:
    pdf = build_pdf(name, when, png_bytes)
    return base64.b64encode(pdf).decode() if pdf else None
