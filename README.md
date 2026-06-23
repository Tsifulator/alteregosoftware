# ALTER EGO — Multilingual Candidate Intake

A small, 24/7 web app that ends the **paper → re-typing** loop in HR.

A walk-in candidate (or an HR staffer helping them) picks their language, fills a
short form in that language, and on **Submit** the record is pushed **straight into
Workable** — already filled in. No handwriting, no double entry, no transcription
mistakes.

Third app in the family alongside [`alteregoscraper`](../alteregoscraper) (IFM lead
scraper) and [`alteregohr`](../alteregohr) (staffing lead scraper) — same Python /
env / free-first conventions, reuses the **same Workable credentials**.

```
language picker  →  intake form (15 languages, RTL-aware)  →  Workable candidate
                                                            ↘  local log + retry queue
```

## Why it helps

Many candidates for cleaning/frontline roles aren't literate in Greek or English.
Today their details are captured on paper, then re-keyed into Workable later — slow
and error-prone. This app lets them self-serve in **their own language** and lands a
clean, structured candidate in Workable instantly. Everything the candidate enters is
also summarized **in Greek** so HR reads one consistent record regardless of language.

## Languages (23)

Greek 🇬🇷 · English 🇬🇧 · Albanian 🇦🇱 · Arabic 🇸🇦 · Urdu 🇵🇰 · Bengali 🇧🇩 ·
Russian 🇷🇺 · Bulgarian 🇧🇬 · Georgian 🇬🇪 · Romanian 🇷🇴 · Ukrainian 🇺🇦 ·
Tagalog 🇵🇭 · Hindi 🇮🇳 · Farsi/Dari 🇮🇷 · Polish 🇵🇱 · Turkish 🇹🇷 · French 🇫🇷 ·
Punjabi 🇮🇳 · Nepali 🇳🇵 · Tamil 🇱🇰 · Sinhala 🇱🇰 · Amharic 🇪🇹 · Pashto 🇦🇫

Chosen to match the labour pools that actually staff frontline/cleaning roles in
Greece. Arabic / Urdu / Farsi / Pashto render right-to-left automatically. Each
language is one file
in [`translations/`](translations) — add or edit one to change a language; no code
change. **Greek & English are hand-authored; the rest are machine translations
flagged `needs_review` — have a native speaker check them before full rollout.**

Add a new language with the local LLM:

```bash
python tools/gen_translations.py de "Deutsch" "German"        # LTR
python tools/gen_translations.py he "עברית" "Hebrew" rtl "🇮🇱"  # RTL
```

## Run it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # fill in (copy WORKABLE_* from ../alteregohr/.env)

# Try it safely first — writes the would-be Workable payload to logs/, sends nothing:
DRY_RUN=true uvicorn app:app --reload --port 8080
#  → open http://localhost:8080

# For real:
uvicorn app:app --port 8080
```

### As an office kiosk

```bash
./run_kiosk.sh                  # serves on :8080 and opens fullscreen
```
The thank-you screen auto-resets to the language picker for the next person
(`KIOSK_MODE`, `KIOSK_RESET_SECONDS`).

### On Railway (public link to text candidates)

[`railway.json`](railway.json) starts `uvicorn app:app`. Set the env vars, and point
`SUBMISSIONS_PATH` / `QUEUE_PATH` at a mounted volume so data survives redeploys.

## How a submission maps to Workable

`POST https://{subdomain}.workable.com/spi/v3/jobs/{shortcode}/candidates`

| Form field | Workable |
|---|---|
| first/last name, phone, email, area | `firstname` / `lastname` / `phone` / `email` / `address` |
| desired role | `headline` (+ tag `role:…`) |
| previous experience | `experience_entries[]` (with Greek translation) |
| everything else (Greek level, availability, shifts, permit, AMKA/AFM, notes) | composed into `summary`, in Greek |

- **No email?** Workable requires one, so a non-deliverable placeholder is
  synthesized from the phone and the record is tagged **`no-email`** — HR calls instead.
- Free-text answers are translated to Greek (best-effort, local Ollama) so HR reads
  one language. Translation never blocks a submission.

## Never loses a candidate

Every submission is written to `submissions.json` **before** the Workable call. If
Workable is unreachable, the record goes to `queue.json` and the candidate still sees
a thank-you (never an error). Retry from the PIN-gated **`/admin`** page (set
`ADMIN_PIN`) — it shows recent submissions and a **Retry failed** button.

## Privacy

This handles personal data. A consent line is shown on every form; `submissions.json`,
`queue.json` and `logs/` are git-ignored — **no personal data is ever committed**.

## Test

```bash
pytest -q          # offline: payload building, email synth, RTL, queue/retry
```

## Config

See [`.env.example`](.env.example). Key vars: `WORKABLE_SUBDOMAIN`,
`WORKABLE_API_TOKEN`, `WORKABLE_INTAKE_JOB`, `DRY_RUN`, `KIOSK_MODE`, `ADMIN_PIN`,
`TRANSLATE_FREETEXT`, `LLM_BACKEND`.
