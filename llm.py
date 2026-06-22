"""Hybrid LLM backend: local Ollama (free) or a cloud API (Groq / Gemini / Claude).

Copied from the sibling repos (alteregohr / alteregoscraper) so the family shares
one mental model. Here it is used only for OPTIONAL, best-effort translation of a
candidate's free-text answers into Greek — it must never block a submission.

Selection is controlled by LLM_BACKEND:
  - "auto" (default): Ollama if reachable, else Groq (free), else Gemini, else Claude.
  - "ollama" / "groq" / "gemini" / "claude": force that backend.

The backend is resolved once per process and reused for every call.
"""
import json
import urllib.request

from config import (
    LLM_BACKEND,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    ANTHROPIC_API_KEY,
    ANTHROPIC_MODEL,
    GEMINI_API_KEY,
    GEMINI_MODEL,
    GROQ_API_KEY,
    GROQ_MODEL,
)

_resolved: str | None = None
_anthropic_client = None


# --- Ollama ------------------------------------------------------------------
def _ollama_available(timeout: int = 2) -> bool:
    try:
        req = urllib.request.Request(f"{OLLAMA_BASE_URL}/api/tags")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def _ollama_generate(prompt: str, timeout: int = 120) -> str:
    payload = json.dumps({
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.2},
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA_BASE_URL}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read()).get("response", "")


# --- Claude ------------------------------------------------------------------
def _get_anthropic():
    global _anthropic_client
    if _anthropic_client is None:
        import anthropic  # lazy: only needed when the Claude backend is used
        _anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY or None)
    return _anthropic_client


def _claude_generate(prompt: str) -> str:
    resp = _get_anthropic().messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in resp.content if b.type == "text")


# --- Gemini (free tier) ------------------------------------------------------
_last_gemini_call = 0.0
_GEMINI_MIN_INTERVAL = 4.5


def _gemini_generate(prompt: str) -> str:
    import time
    import requests
    global _last_gemini_call
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{GEMINI_MODEL}:generateContent")
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1024},
    }
    backoff = 5
    r = None
    for _ in range(6):
        wait = _GEMINI_MIN_INTERVAL - (time.time() - _last_gemini_call)
        if wait > 0:
            time.sleep(wait)
        _last_gemini_call = time.time()
        r = requests.post(url, params={"key": GEMINI_API_KEY}, json=body, timeout=90)
        if r.status_code in (429, 503):
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)
            continue
        r.raise_for_status()
        parts = r.json()["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts)
    raise RuntimeError(f"Gemini rate-limited after retries (last status {r.status_code})")


# --- Groq (free tier) --------------------------------------------------------
def _groq_generate(prompt: str) -> str:
    import time
    import requests
    backoff = 5
    r = None
    for _ in range(6):
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            json={
                "model": GROQ_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
                "max_tokens": 1024,
            },
            timeout=90,
        )
        if r.status_code in (429, 503):
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)
            continue
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    raise RuntimeError(f"Groq rate-limited after retries (last status {r.status_code})")


# --- Dispatch ----------------------------------------------------------------
def active_backend() -> str:
    """Resolve (once) which backend to use, printing the choice on first call."""
    global _resolved
    if _resolved:
        return _resolved

    if LLM_BACKEND == "ollama":
        _resolved = "ollama"
    elif LLM_BACKEND == "groq":
        if not GROQ_API_KEY:
            raise RuntimeError("LLM_BACKEND=groq but GROQ_API_KEY is unset.")
        _resolved = "groq"
    elif LLM_BACKEND == "gemini":
        if not GEMINI_API_KEY:
            raise RuntimeError("LLM_BACKEND=gemini but GEMINI_API_KEY is unset.")
        _resolved = "gemini"
    elif LLM_BACKEND == "claude":
        if not ANTHROPIC_API_KEY:
            raise RuntimeError("LLM_BACKEND=claude but ANTHROPIC_API_KEY is unset.")
        _resolved = "claude"
    else:  # auto: free local Ollama, then free Groq, then Gemini, then paid Claude
        if _ollama_available():
            _resolved = "ollama"
        elif GROQ_API_KEY:
            _resolved = "groq"
        elif GEMINI_API_KEY:
            _resolved = "gemini"
        elif ANTHROPIC_API_KEY:
            _resolved = "claude"
        else:
            raise RuntimeError(
                "No LLM backend available: Ollama unreachable and no GROQ_API_KEY / "
                "GEMINI_API_KEY / ANTHROPIC_API_KEY set."
            )

    detail = {"ollama": OLLAMA_MODEL, "groq": GROQ_MODEL, "gemini": GEMINI_MODEL,
              "claude": ANTHROPIC_MODEL}[_resolved]
    print(f"  LLM backend: {_resolved} ({detail})")
    return _resolved


def generate(prompt: str) -> str:
    """Return the model's raw text response from the active backend."""
    b = active_backend()
    if b == "ollama":
        return _ollama_generate(prompt)
    if b == "groq":
        return _groq_generate(prompt)
    if b == "gemini":
        return _gemini_generate(prompt)
    return _claude_generate(prompt)
