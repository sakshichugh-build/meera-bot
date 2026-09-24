"""Configuration loader. Reads a local .env file (no external dependency)."""
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_ENV_PATH = os.path.join(_HERE, ".env")


def _load_env():
    """Minimal .env parser: KEY=VALUE per line, # comments, optional quotes."""
    if not os.path.exists(_ENV_PATH):
        return
    with open(_ENV_PATH, "r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            # Only set if not already provided by the real environment.
            os.environ.setdefault(key, val)


_load_env()


def _get(name, default=None, required=False):
    val = os.environ.get(name, default)
    if required and not val:
        raise RuntimeError(
            f"Missing required config '{name}'. Set it in {_ENV_PATH}."
        )
    return val


# --- Credentials ---
TELEGRAM_TOKEN = _get("TELEGRAM_TOKEN", required=True)
GEMINI_API_KEY = _get("GEMINI_API_KEY", required=True)

# Optional: the self-channel id. Notes are answered in whatever chat they arrive
# in, so this is informational / for restricting the bot if you want.
TELEGRAM_CHAT_ID = _get("TELEGRAM_CHAT_ID", "")

# --- Behaviour ---
# Only develop notes that score at or above this (out of 10).
SCORE_THRESHOLD = int(_get("SCORE_THRESHOLD", "6"))

# Weekly publishing target (used for the progress line after Approve).
WEEKLY_TARGET = int(_get("WEEKLY_TARGET", "3"))

# Gemini model. A "flash" model is fast, cheap and supports audio in-line.
GEMINI_MODEL = _get("GEMINI_MODEL", "gemini-3.6-flash")

# If the primary model is overloaded (503), fall back through these in order.
GEMINI_FALLBACK_MODELS = [
    m.strip() for m in
    _get("GEMINI_FALLBACK_MODELS", "gemini-3.5-flash,gemini-flash-lite-latest").split(",")
    if m.strip()
]

# How many days back to look for a news hook.
NEWS_WINDOW_DAYS = int(_get("NEWS_WINDOW_DAYS", "14"))

# File locations.
DB_PATH = os.path.join(_HERE, _get("DB_FILE", "meera.db"))
SKILL_PATH = os.path.join(_HERE, _get("SKILL_FILE", "SKILL.md"))
