"""Configuration for the ALTER EGO multilingual candidate-intake app.

Third app in the family alongside alteregoscraper (IFM leads) and alteregohr
(staffing leads). A candidate picks their language, fills a short form, and on
submit the record is pushed straight into Workable — no paper, no re-typing.

Same env conventions as the siblings: python-dotenv + os.getenv(..., default),
a DRY_RUN flag, and overridable persistence paths for Railway volumes.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent
LOGS_DIR = PROJECT_ROOT / "logs"
LOGS_DIR.mkdir(exist_ok=True)

# --- Persistence (overridable so they can live on a Railway volume) ---
# Every submission is logged here first, so a candidate's data is never lost
# even if Workable is unreachable.
SUBMISSIONS_PATH = Path(os.getenv("SUBMISSIONS_PATH", str(PROJECT_ROOT / "submissions.json")))
# Submissions that failed to reach Workable wait here for a retry.
QUEUE_PATH = Path(os.getenv("QUEUE_PATH", str(PROJECT_ROOT / "queue.json")))

# ─────────────────────────────────────────────────────────────────────────────
# Workable API — credentials are shared with alteregohr (copy them from
# alteregohr/.env). Candidates are created at:
#   POST https://{SUBDOMAIN}.workable.com/spi/v3/jobs/{INTAKE_JOB}/candidates
# ─────────────────────────────────────────────────────────────────────────────
WORKABLE_SUBDOMAIN = os.getenv("WORKABLE_SUBDOMAIN", "").strip()
WORKABLE_API_TOKEN = os.getenv("WORKABLE_API_TOKEN", "").strip()
# Shortcode of the Workable job new walk-in candidates attach to. Find it in the
# job URL or via GET /spi/v3/jobs. MUST be set before going live.
WORKABLE_INTAKE_JOB = os.getenv("WORKABLE_INTAKE_JOB", "").strip()
# Whether new candidates land in the "sourced" (True) or "applied" (False) stage.
WORKABLE_SOURCED = os.getenv("WORKABLE_SOURCED", "true").lower() == "true"

# Workable requires an email on every candidate, but many walk-ins don't have one.
# When the email field is blank we synthesize one on this domain and tag the
# record "no-email" so HR knows to use the phone instead. ".invalid" is a
# reserved, non-deliverable TLD (RFC 2606) — nothing ever gets mailed to it.
PLACEHOLDER_EMAIL_DOMAIN = os.getenv("PLACEHOLDER_EMAIL_DOMAIN", "candidates.alterego.invalid")

# --- App behaviour ---
# Kiosk mode: no login, and the thank-you screen auto-resets to the language
# picker for the next candidate after KIOSK_RESET_SECONDS.
KIOSK_MODE = os.getenv("KIOSK_MODE", "true").lower() == "true"
KIOSK_RESET_SECONDS = int(os.getenv("KIOSK_RESET_SECONDS", "8"))
# PIN that gates the /admin oversight page. Empty = admin page disabled.
ADMIN_PIN = os.getenv("ADMIN_PIN", "").strip()
SESSION_SECRET = os.getenv("SESSION_SECRET", "alterego-intake-dev-secret-change-in-prod")
ORG_NAME = os.getenv("ORG_NAME", "ALTER EGO")

# Default country code prepended to phone numbers entered without one.
DEFAULT_PHONE_CC = os.getenv("DEFAULT_PHONE_CC", "+30")

# If true, never call Workable — write the would-be payload to logs/ instead.
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"

# --- Optional free-text translation (best-effort; never blocks a submission) ---
# When true, free-text fields written in the candidate's language are also
# translated to Greek so HR can read them. Uses the local-first LLM backend below.
TRANSLATE_FREETEXT = os.getenv("TRANSLATE_FREETEXT", "true").lower() == "true"

# --- LLM backend (hybrid, free-first) — same scheme as the sibling repos ---
# "auto": Ollama if reachable, else Groq (free), else Gemini, else Claude.
LLM_BACKEND = os.getenv("LLM_BACKEND", "auto").lower()

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma3")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5")


def workable_configured() -> bool:
    """True when we have everything needed to actually post to Workable."""
    return bool(WORKABLE_SUBDOMAIN and WORKABLE_API_TOKEN and WORKABLE_INTAKE_JOB)
