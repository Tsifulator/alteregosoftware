"""Tests for the intake app: schema, payload building, email synth, romanization, queue.

Run from the project root:  pytest -q
Network is never touched — DRY_RUN + a stubbed LLM keep these offline & deterministic.
"""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ["DRY_RUN"] = "true"

import i18n                       # noqa: E402
import llm                        # noqa: E402
import workable_client as wc      # noqa: E402
from fields import REQUIRED_KEYS, SECTIONS, EXPERIENCE_COLS  # noqa: E402


@pytest.fixture(autouse=True)
def _offline_llm(monkeypatch):
    """Force the offline transliterator (unidecode) instead of hitting a local Ollama."""
    def _boom(*_a, **_k):
        raise RuntimeError("LLM disabled in tests")
    monkeypatch.setattr(llm, "generate", _boom)


# ── translations / i18n ──────────────────────────────────────────────────────

def test_all_shipped_languages_load():
    codes = set(i18n.available_codes())
    assert {"el", "en", "ar", "ka", "tl", "am", "ta", "si", "pa", "ne", "tr", "fr", "ps", "vi"} <= codes
    assert len(codes) >= 24


def test_rtl_flagged():
    for c in ("ar", "ur", "fa", "ps"):
        assert i18n.is_rtl(c)
    assert not i18n.is_rtl("el")


def test_unknown_language_falls_back_to_english():
    assert i18n.safe_lang("zz") == "en"
    assert i18n.t("zz", "submit") == i18n.t("en", "submit")


def test_section_titles_present():
    assert SECTIONS == ["personal", "education", "experience", "other"]
    for s in SECTIONS:
        assert i18n.section_title("el", s) and i18n.section_title("en", s)
    for col in EXPERIENCE_COLS:
        assert i18n.exp_label("el", col)


# ── required fields ──────────────────────────────────────────────────────────

def test_required_keys():
    assert set(REQUIRED_KEYS) == {"first_name", "last_name", "mobile", "desired_role"}


# ── phone normalization ──────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("6971234567", "+306971234567"),
    ("06971234567", "+306971234567"),
    ("+306971234567", "+306971234567"),
    ("0030 697 123 4567", "+306971234567"),
])
def test_phone_normalization(raw, expected):
    assert wc._normalize_phone(raw) == expected


# ── email synthesis ──────────────────────────────────────────────────────────

def test_email_synthesized_when_missing():
    cand, meta = wc.build_candidate("ar", {
        "first_name": "Ahmad", "last_name": "Khan", "mobile": "6971234567",
        "email": "", "desired_role": "cleaner"})
    assert meta["no_email"] and cand["email"].endswith("@candidates.alterego.invalid")
    assert "no-email" in cand["tags"]
    assert cand["email"].split("@")[0].isascii()


def test_real_email_kept():
    cand, meta = wc.build_candidate("el", {
        "first_name": "Maria", "last_name": "Papa", "mobile": "6971234567",
        "email": "maria@example.com", "desired_role": "helper"})
    assert not meta["no_email"] and cand["email"] == "maria@example.com"


# ── full payload from the official-form fields ───────────────────────────────

def _full_form():
    return {
        "first_name": "Besnik", "last_name": "Hoxha", "mobile": "6971234567", "email": "",
        "amka": "12345678901", "address": "Πατησίων", "address_number": "12",
        "area": "Κυψέλη", "city": "Αθήνα", "postal_code": "11257",
        "home_phone": "2101234567", "birth_year": "1995", "birth_place": "Tirana",
        "nationality": "Albanian", "education_level": "lyceum", "school": "2ο Λύκειο",
        "languages": "Greek, Albanian", "greek_level": "good", "computer_use": "moderate",
        "driving_license": "yes", "car_owner": "no", "desired_role": "cleaner",
        "desired_schedule": ["morning", "weekend"], "referred_by": "Maria", "referrer_profession": "supervisor",
        "how_found": "facebook",
        "experience_rows": [
            {"company": "Hotel X", "position": "Cleaner", "period": "2020-2022", "reason": "relocation"},
        ],
    }


def test_summary_is_greek_and_complete():
    cand, _ = wc.build_candidate("sq", _full_form())
    s = cand["summary"]
    assert "Καθαριστής/τρια" in cand["headline"]
    assert "Επίπεδο ελληνικών: Καλά" in s
    assert "Δίπλωμα οδήγησης: Ναι" in s
    assert "Εκπαίδευση: Λύκειο" in s
    assert "Πρωινό" in s and "Σαββατοκύριακο" in s        # multiselect schedule → Greek
    assert "12345678901" in s                              # AMKA passed through
    assert "intake-app" in cand["tags"]


def test_address_composed_from_parts():
    cand, _ = wc.build_candidate("el", _full_form())
    # street + number, area, city, postal — joined
    assert "Πατησίων 12" in cand["address"]
    assert "Αθήνα" in cand["address"] and "11257" in cand["address"]


def test_experience_rows_become_entries():
    cand, _ = wc.build_candidate("en", _full_form())
    e = cand["experience_entries"][0]
    assert e["title"] == "Cleaner" and e["company"] == "Hotel X"
    assert "2020-2022" in e["summary"] and "relocation" in e["summary"]


def test_empty_experience_rows_omitted():
    data = _full_form()
    data["experience_rows"] = [{"company": "", "position": "", "period": "", "reason": ""}]
    cand, _ = wc.build_candidate("el", data)
    assert "experience_entries" not in cand


def test_dry_run_post_writes_no_network(tmp_path, monkeypatch):
    monkeypatch.setattr(wc, "LOGS_DIR", tmp_path)
    cand, _ = wc.build_candidate("en", {
        "first_name": "Test", "last_name": "User", "mobile": "6971234567", "desired_role": "cleaner"})
    ok, wid, err = wc.post_candidate(cand)
    assert ok and err is None and list(tmp_path.glob("dryrun-*.json"))


# ── name romanization ────────────────────────────────────────────────────────

def test_non_latin_name_romanized_and_original_kept():
    cand, _ = wc.build_candidate("ru", {
        "first_name": "Мария", "last_name": "Иванова", "mobile": "6971234567",
        "desired_role": "cleaner"})
    assert cand["firstname"].isascii() and cand["firstname"] != "Мария"
    assert "Мария Иванова" in cand["summary"]


def test_greek_names_left_in_greek():
    cand, _ = wc.build_candidate("el", {
        "first_name": "Μαρία", "last_name": "Παπά", "mobile": "6971234567", "desired_role": "helper"})
    assert cand["firstname"] == "Μαρία"


# ── queue / retry resilience ─────────────────────────────────────────────────

def test_queue_and_retry(tmp_path, monkeypatch):
    import importlib
    monkeypatch.setenv("SUBMISSIONS_PATH", str(tmp_path / "subs.json"))
    monkeypatch.setenv("QUEUE_PATH", str(tmp_path / "queue.json"))
    import config, store
    importlib.reload(config)
    importlib.reload(store)

    rec = store.record_submission("el", {"first_name": "A", "last_name": "B"}, {"email": "x@y.z"})
    store.enqueue_failure(rec, "Workable down")
    assert len(store.load_queue()) == 1

    calls = {"n": 0}
    def flaky(_c):
        calls["n"] += 1
        return (calls["n"] >= 2, "wk_1" if calls["n"] >= 2 else None, None if calls["n"] >= 2 else "down")

    assert store.retry_failed(flaky)["succeeded"] == 0
    assert store.retry_failed(flaky)["succeeded"] == 1
    assert store.load_queue() == []
    importlib.reload(config); importlib.reload(store)


# ── digital signature ────────────────────────────────────────────────────────

# a 1x1 transparent PNG as a data URL
_PNG = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4"
        "2mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=")


def test_is_signature_validation():
    import store
    assert store.is_signature(_PNG)
    assert not store.is_signature("")
    assert not store.is_signature("hello")
    assert not store.is_signature("data:image/png;base64,")   # too short / empty


def test_save_signature_writes_png(tmp_path, monkeypatch):
    import importlib
    monkeypatch.setenv("SUBMISSIONS_PATH", str(tmp_path / "subs.json"))
    monkeypatch.setenv("QUEUE_PATH", str(tmp_path / "queue.json"))
    monkeypatch.setenv("SIGNATURES_DIR", str(tmp_path / "sigs"))
    import config, store
    importlib.reload(config); importlib.reload(store)

    rec = store.record_submission("el", {"first_name": "A", "last_name": "B"}, {})
    assert rec["signed"] is False
    fname = store.save_signature(rec["id"], _PNG)
    assert fname == f"{rec['id']}.png"
    assert store.signature_path(rec["id"]).exists()
    assert store.load_submissions()[0]["signed"] is True
    assert store.save_signature(rec["id"], "not-an-image") is None
    importlib.reload(config); importlib.reload(store)


def test_signed_flag_noted_in_summary():
    cand, _ = wc.build_candidate("el", {
        "first_name": "Μαρία", "last_name": "Παπά", "mobile": "6971234567",
        "desired_role": "cleaner", "signed": True})
    assert "Υπογραφή: ✔" in cand["summary"]
