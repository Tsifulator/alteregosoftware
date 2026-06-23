"""Canonical intake-form field schema — the single source of truth.

Every field is language-neutral here (just keys + types). The human-readable
label for a field, and for each select option, lives in translations/<lang>.json
under "labels" and "options" keyed by these same keys. Add a field once here and
it shows up in every language automatically (with the key as a fallback label
until translated).

Field "kind":
  text | tel | email | textarea | select | multiselect

"target" tells workable_client how the value reaches Workable:
  direct  -> a first-class Workable candidate field (mapped via WORKABLE_FIELD)
  summary -> folded into the composed `summary` block HR reads
  exp     -> becomes a Workable experience_entry
"""
from __future__ import annotations

# Ordered list of fields as they appear on the form.
FIELDS: list[dict] = [
    {"key": "first_name", "kind": "text", "required": True, "target": "direct", "workable": "firstname", "autocap": True},
    {"key": "last_name", "kind": "text", "required": True, "target": "direct", "workable": "lastname", "autocap": True},
    {"key": "phone", "kind": "tel", "required": True, "target": "direct", "workable": "phone"},
    {"key": "email", "kind": "email", "required": False, "target": "direct", "workable": "email"},
    {"key": "desired_role", "kind": "select", "required": True, "target": "summary",
     "options": ["cleaner", "helper", "supervisor", "driver", "security", "kitchen", "gardening", "other"]},
    {"key": "area", "kind": "text", "required": False, "target": "direct", "workable": "address"},
    {"key": "greek_level", "kind": "select", "required": False, "target": "summary",
     "options": ["none", "basic", "good", "fluent"]},
    {"key": "other_languages", "kind": "text", "required": False, "target": "summary"},
    {"key": "availability", "kind": "select", "required": False, "target": "summary",
     "options": ["immediate", "full_time", "part_time", "flexible"]},
    {"key": "shifts", "kind": "multiselect", "required": False, "target": "summary",
     "options": ["morning", "afternoon", "night", "weekends"]},
    {"key": "work_permit", "kind": "select", "required": False, "target": "summary",
     "options": ["yes", "no", "in_process"]},
    {"key": "amka", "kind": "text", "required": False, "target": "summary"},
    {"key": "afm", "kind": "text", "required": False, "target": "summary"},
    {"key": "experience", "kind": "textarea", "required": False, "target": "exp", "freetext": True},
    {"key": "notes", "kind": "textarea", "required": False, "target": "summary", "freetext": True},
    # Set by HR during an assisted walk-in. If filled, it's pushed to the SMS
    # reminder calendar (and noted in the Workable summary). Not a Workable field.
    {"key": "interview_at", "kind": "datetime", "required": False, "target": "meta"},
]

# Convenience lookups.
BY_KEY: dict[str, dict] = {f["key"]: f for f in FIELDS}
REQUIRED_KEYS: list[str] = [f["key"] for f in FIELDS if f.get("required")]
FREETEXT_KEYS: list[str] = [f["key"] for f in FIELDS if f.get("freetext")]
SELECT_KEYS: list[str] = [f["key"] for f in FIELDS if f["kind"] in ("select", "multiselect")]


def options_for(key: str) -> list[str]:
    return BY_KEY.get(key, {}).get("options", [])
