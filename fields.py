"""Canonical intake-form schema — mirrors ALTER EGO's paper application
(«ΑΙΤΗΣΗ ΕΡΓΑΣΙΑΣ ΥΠΟΨΗΦΙΟΥ ΕΡΓΑΖΟΜΕΝΟΥ», form E 14-3.5).

Candidate-facing sections only (1–4 on the paper form). The HR-internal sections
(evaluation, contact log, hiring approval) are not part of the candidate intake —
those happen in Workable afterwards.

Each field is language-neutral here (key + type + section). Labels and select
options live per-language in translations/<lang>.json under "labels"/"options",
keyed by these keys; section titles under "sections".

"kind":   text | tel | email | select | multiselect
"target": how the value reaches Workable —
  direct   -> a first-class candidate field (mapped via "workable")
  address  -> folded into the composed Workable `address`
  summary  -> folded into the Greek `summary` block HR reads
Experience rows (section "experience") become Workable experience_entries.
"""
from __future__ import annotations

# Section order on the form.
SECTIONS = ["personal", "education", "experience", "other"]

FIELDS: list[dict] = [
    # 1 — ΑΤΟΜΙΚΑ ΣΤΟΙΧΕΙΑ (personal details)
    {"key": "first_name", "section": "personal", "kind": "text", "required": True, "target": "direct", "workable": "firstname"},
    {"key": "last_name", "section": "personal", "kind": "text", "required": True, "target": "direct", "workable": "lastname"},
    {"key": "amka", "section": "personal", "kind": "text", "required": False, "target": "summary"},
    {"key": "address", "section": "personal", "kind": "text", "required": False, "target": "address"},
    {"key": "address_number", "section": "personal", "kind": "text", "required": False, "target": "address"},
    {"key": "area", "section": "personal", "kind": "text", "required": False, "target": "address"},
    {"key": "city", "section": "personal", "kind": "text", "required": False, "target": "address"},
    {"key": "postal_code", "section": "personal", "kind": "text", "required": False, "target": "address"},
    {"key": "mobile", "section": "personal", "kind": "tel", "required": True, "target": "direct", "workable": "phone"},
    {"key": "home_phone", "section": "personal", "kind": "tel", "required": False, "target": "summary"},
    {"key": "birth_year", "section": "personal", "kind": "text", "required": False, "target": "summary"},
    {"key": "birth_place", "section": "personal", "kind": "text", "required": False, "target": "summary", "romanize": True},
    {"key": "nationality", "section": "personal", "kind": "text", "required": False, "target": "summary", "romanize": True},
    {"key": "email", "section": "personal", "kind": "email", "required": False, "target": "direct", "workable": "email"},

    # 2 — ΕΚΠΑΙΔΕΥΣΗ (education)
    {"key": "education_level", "section": "education", "kind": "select", "required": False, "target": "summary",
     "options": ["primary", "gymnasium", "lyceum", "higher", "university"]},
    {"key": "school", "section": "education", "kind": "text", "required": False, "target": "summary", "romanize": True},
    {"key": "languages", "section": "education", "kind": "text", "required": False, "target": "summary", "romanize": True},
    {"key": "greek_level", "section": "education", "kind": "select", "required": False, "target": "summary",
     "options": ["none", "basic", "good", "fluent"]},
    {"key": "computer_use", "section": "education", "kind": "select", "required": False, "target": "summary",
     "options": ["fluent", "moderate", "none"]},
    {"key": "driving_license", "section": "education", "kind": "select", "required": False, "target": "summary",
     "options": ["yes", "no"]},
    {"key": "car_owner", "section": "education", "kind": "select", "required": False, "target": "summary",
     "options": ["yes", "no"]},

    # 4 — ΥΠΟΛΟΙΠΑ ΣΤΟΙΧΕΙΑ (other details)  [section 3 = experience table, below]
    {"key": "desired_role", "section": "other", "kind": "select", "required": True, "target": "summary",
     "options": ["cleaner", "helper", "supervisor", "driver", "security", "kitchen", "gardening", "other"]},
    {"key": "desired_schedule", "section": "other", "kind": "multiselect", "required": False, "target": "summary",
     "options": ["morning", "afternoon", "evening", "weekend"]},
    {"key": "referred_by", "section": "other", "kind": "text", "required": False, "target": "summary", "romanize": True},
    {"key": "referrer_profession", "section": "other", "kind": "text", "required": False, "target": "summary", "romanize": True},
    {"key": "how_found", "section": "other", "kind": "text", "required": False, "target": "summary", "romanize": True},
]

# 3 — ΠΡΟΫΠΗΡΕΣΙΑ (previous experience): a small table → Workable experience_entries.
EXPERIENCE_ROWS = 3
EXPERIENCE_COLS = ["company", "position", "period", "reason"]   # ΕΤΑΙΡΙΑ · ΘΕΣΗ · ΔΙΑΣΤΗΜΑ · ΛΟΓΟΣ ΑΠΟΧΩΡΗΣΗΣ

# Convenience lookups.
BY_KEY: dict[str, dict] = {f["key"]: f for f in FIELDS}
REQUIRED_KEYS: list[str] = [f["key"] for f in FIELDS if f.get("required")]
ADDRESS_KEYS: list[str] = [f["key"] for f in FIELDS if f["target"] == "address"]


def fields_in(section: str) -> list[dict]:
    return [f for f in FIELDS if f["section"] == section]


def options_for(key: str) -> list[str]:
    return BY_KEY.get(key, {}).get("options", [])
