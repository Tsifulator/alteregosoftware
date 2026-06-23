"""Tests for the intake app: payload building, email synth, translations, queue.

Run from the project root:  pytest -q
Network is never touched — DRY_RUN + monkeypatched post keep these offline.
"""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Keep tests fully offline/deterministic regardless of the developer's .env.
os.environ["DRY_RUN"] = "true"
os.environ["TRANSLATE_FREETEXT"] = "false"

import i18n                       # noqa: E402
import llm                        # noqa: E402
import workable_client as wc      # noqa: E402
from fields import REQUIRED_KEYS  # noqa: E402


@pytest.fixture(autouse=True)
def _offline_llm(monkeypatch):
    """Keep tests fast + deterministic: force the offline transliterator (unidecode)
    by making the LLM unavailable, instead of hitting a local Ollama if one is up."""
    def _boom(*_a, **_k):
        raise RuntimeError("LLM disabled in tests")
    monkeypatch.setattr(llm, "generate", _boom)


# ── translations / i18n ──────────────────────────────────────────────────────

def test_all_shipped_languages_load():
    codes = set(i18n.available_codes())
    # baseline + a spread of the labour-pool languages, incl. the newer batch
    assert {"el", "en", "ar", "ka", "tl", "am", "ta", "si", "pa", "ne", "tr", "fr", "ps", "vi"} <= codes
    assert len(codes) >= 24


def test_rtl_flagged_for_arabic_urdu_farsi():
    for c in ("ar", "ur", "fa", "ps"):
        assert i18n.is_rtl(c), f"{c} should be RTL"
    assert not i18n.is_rtl("el")


# ── name romanization (Greek HR needs readable Latin/Greek names) ────────────

def test_non_latin_name_romanized_to_ascii_and_original_preserved():
    # Cyrillic name from a Russian-speaking applicant -> Latin in Workable fields,
    # original script kept in the Greek summary. (LLM is offline here -> unidecode.)
    data = {"first_name": "Мария", "last_name": "Иванова", "phone": "6971234567",
            "desired_role": "cleaner"}
    cand, _ = wc.build_candidate("ru", data)
    assert cand["firstname"].isascii() and cand["firstname"] != "Мария"
    assert cand["lastname"].isascii()
    assert "Мария Иванова" in cand["summary"]      # original preserved


def test_greek_names_left_in_greek():
    data = {"first_name": "Μαρία", "last_name": "Παπά", "phone": "6971234567",
            "desired_role": "helper"}
    cand, _ = wc.build_candidate("el", data)
    assert cand["firstname"] == "Μαρία"            # Greek HR reads Greek — untouched


def test_latin_names_passed_through_unchanged():
    data = {"first_name": "Besnik", "last_name": "Hoxha", "phone": "6971234567",
            "desired_role": "cleaner"}
    cand, _ = wc.build_candidate("sq", data)
    assert cand["firstname"] == "Besnik" and cand["lastname"] == "Hoxha"


def test_unknown_language_falls_back_to_english():
    assert i18n.safe_lang("zz") == "en"
    assert i18n.t("zz", "submit") == i18n.t("en", "submit")


def test_greek_and_english_not_flagged_for_review():
    assert not i18n.needs_review("el")
    assert not i18n.needs_review("en")
    assert i18n.needs_review("ar")


# ── phone normalization ──────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("6971234567", "+306971234567"),     # bare Greek mobile -> +30
    ("06971234567", "+306971234567"),    # leading trunk zero dropped
    ("+306971234567", "+306971234567"),  # already international -> untouched
    ("0030 697 123 4567", "+306971234567"),  # 00 prefix -> +
])
def test_phone_normalization(raw, expected):
    assert wc._normalize_phone(raw) == expected


# ── email synthesis (Workable requires an email) ─────────────────────────────

def test_email_synthesized_when_missing():
    data = {"first_name": "Ahmad", "last_name": "Khan", "phone": "6971234567",
            "email": "", "desired_role": "cleaner"}
    cand, meta = wc.build_candidate("ar", data)
    assert meta["no_email"] is True
    assert cand["email"].endswith("@candidates.alterego.invalid")
    assert "no-email" in cand["tags"]
    # local part must be pure ASCII even though the name is not
    local = cand["email"].split("@")[0]
    assert local.isascii()


def test_real_email_kept():
    data = {"first_name": "Maria", "last_name": "Papa", "phone": "6971234567",
            "email": "maria@example.com", "desired_role": "helper"}
    cand, meta = wc.build_candidate("el", data)
    assert meta["no_email"] is False
    assert cand["email"] == "maria@example.com"
    assert "no-email" not in cand["tags"]


# ── candidate payload shape ──────────────────────────────────────────────────

def test_summary_is_greek_and_contains_all_fields():
    data = {
        "first_name": "Besnik", "last_name": "Hoxha", "phone": "6971234567",
        "email": "", "desired_role": "cleaner", "area": "Peristeri",
        "greek_level": "basic", "availability": "immediate",
        "shifts": ["morning", "weekends"], "work_permit": "yes",
        "amka": "12345678901", "afm": "098765432", "other_languages": "Albanian, Italian",
        "experience": "2 years hotel cleaning",
    }
    cand, _ = wc.build_candidate("sq", data)
    s = cand["summary"]
    # Greek option labels rendered, not the raw keys
    assert "Καθαριστής/τρια" in cand["headline"]
    assert "Άμεση έναρξη" in s          # availability=immediate -> Greek
    assert "Πρωί" in s and "Σαββατοκύριακα" in s   # multiselect shifts -> Greek
    assert "12345678901" in s           # AMKA passed through
    assert "intake-app" in cand["tags"]
    assert cand["address"] == "Peristeri"
    # free-text experience becomes a Workable experience_entry
    assert cand["experience_entries"][0]["summary"].startswith("2 years")


def test_dry_run_post_writes_no_network_and_returns_ok(tmp_path, monkeypatch):
    # build a candidate and ensure DRY_RUN path returns success without requests
    monkeypatch.setattr(wc, "LOGS_DIR", tmp_path)
    cand, _ = wc.build_candidate("en", {
        "first_name": "Test", "last_name": "User", "phone": "6971234567",
        "desired_role": "cleaner",
    })
    ok, wid, err = wc.post_candidate(cand)
    assert ok and err is None
    assert list(tmp_path.glob("dryrun-*.json")), "DRY_RUN should write a payload file"


# ── queue / retry resilience ─────────────────────────────────────────────────

def test_queue_and_retry(tmp_path, monkeypatch):
    import importlib
    monkeypatch.setenv("SUBMISSIONS_PATH", str(tmp_path / "subs.json"))
    monkeypatch.setenv("QUEUE_PATH", str(tmp_path / "queue.json"))
    import config, store
    importlib.reload(config)
    importlib.reload(store)

    rec = store.record_submission("el", {"first_name": "A", "last_name": "B"},
                                  {"email": "x@y.z"})
    store.enqueue_failure(rec, "Workable down")
    assert len(store.load_queue()) == 1

    # First retry fails, second succeeds.
    calls = {"n": 0}
    def flaky(_cand):
        calls["n"] += 1
        return (calls["n"] >= 2, "wk_123" if calls["n"] >= 2 else None, None if calls["n"] >= 2 else "still down")

    assert store.retry_failed(flaky)["succeeded"] == 0
    assert len(store.load_queue()) == 1            # still queued after a failure
    res = store.retry_failed(flaky)
    assert res["succeeded"] == 1
    assert store.load_queue() == []                # drained after success
    importlib.reload(config); importlib.reload(store)   # restore module state


def test_required_keys_are_the_three_essentials():
    assert set(REQUIRED_KEYS) == {"first_name", "last_name", "phone", "desired_role"}


# ── interview date/time → summary + reminder client ──────────────────────────

def test_interview_time_appears_in_greek_summary():
    cand, _ = wc.build_candidate("ar", {
        "first_name": "Ali", "last_name": "Hassan", "phone": "6971234567",
        "desired_role": "cleaner", "interview_at": "2026-06-28T14:30",
    })
    assert "Συνέντευξη: 28/06 14:30" in cand["summary"]


def test_format_interview_handles_blank_and_bad():
    assert wc.format_interview("") == ""
    assert wc.format_interview(None) == ""
    assert wc.format_interview("2026-06-28T09:05") == "28/06 09:05"
    assert wc.format_interview("not-a-date") == "not-a-date"   # never raises


def test_reminder_client_dry_run_builds_payload(tmp_path, monkeypatch):
    import reminder_client as rc
    monkeypatch.setattr(rc, "DRY_RUN", True)
    monkeypatch.setattr(rc, "LOGS_DIR", tmp_path)
    ok, appt_id, status, detail = rc.schedule_interview(
        name="Maria Ivanova", first_name="Maria", phone="+306971234567",
        interview_at="2026-06-28T14:00", lang="ru")
    assert ok and status == "dry" and appt_id is None
    files = list(tmp_path.glob("reminder-*.json"))
    assert files, "DRY_RUN should write a reminder payload"
    import json
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert payload["preferred_language"] == "ru"
    assert payload["datetime_iso"].startswith("2026-06-28T14:00")
    assert payload["phone"] == "+306971234567"


def test_reminder_client_skips_when_no_interview():
    import reminder_client as rc
    ok, appt_id, status, _ = rc.schedule_interview("A B", "A", "+306971234567", "", "el")
    assert not ok and status == "no_interview"


def test_to_iso_parsing():
    import reminder_client as rc
    assert rc.to_iso("2026-06-28T14:00").startswith("2026-06-28T14:00")
    assert rc.to_iso("") is None
    assert rc.to_iso("garbage") is None
