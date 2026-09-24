"""Gemini calls over the REST API (stdlib only).

Three jobs:
  transcribe(audio)  -> plain text
  score(note)        -> {score, reason, category, topic_keywords}
  draft(note, hook)  -> Meera-voice draft in the skill's output format
  revise(draft, ...) -> revised draft
"""
import json
import time
import base64
import urllib.request
import urllib.error

import config

_URL = ("https://generativelanguage.googleapis.com/v1beta/models/"
        "{model}:generateContent?key={key}")

# Transient statuses worth retrying (overload / rate limit / gateway).
_RETRY_CODES = {429, 500, 502, 503, 504}
_RETRIES_PER_MODEL = 3


def _post_once(model, body_bytes, timeout=120):
    url = _URL.format(model=model, key=config.GEMINI_API_KEY)
    req = urllib.request.Request(
        url, data=body_bytes, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _call(parts, system_instruction=None, want_json=False, temperature=0.7):
    body = {
        "contents": [{"parts": parts}],
        "generationConfig": {"temperature": temperature},
    }
    if system_instruction:
        body["systemInstruction"] = {"parts": [{"text": system_instruction}]}
    if want_json:
        body["generationConfig"]["responseMimeType"] = "application/json"
    body_bytes = json.dumps(body).encode("utf-8")

    # Try the primary model, then each fallback. Each gets a few retries with
    # backoff for transient overload before we roll to the next model.
    models = [config.GEMINI_MODEL] + [
        m for m in config.GEMINI_FALLBACK_MODELS if m != config.GEMINI_MODEL
    ]
    payload = None
    last_err = "no models tried"
    for model in models:
        for attempt in range(_RETRIES_PER_MODEL):
            try:
                payload = _post_once(model, body_bytes)
                break
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")[:300]
                last_err = f"HTTP {e.code} on {model}: {detail}"
                if e.code in _RETRY_CODES and attempt < _RETRIES_PER_MODEL - 1:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                break  # non-retryable, or out of retries -> try next model
            except urllib.error.URLError as e:
                last_err = f"connection error on {model}: {e}"
                if attempt < _RETRIES_PER_MODEL - 1:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                break
        if payload is not None:
            break
    if payload is None:
        raise RuntimeError(f"Gemini unavailable ({last_err})")

    try:
        cand = payload["candidates"][0]
        return "".join(
            p.get("text", "") for p in cand["content"]["parts"]
        ).strip()
    except (KeyError, IndexError):
        raise RuntimeError(f"Unexpected Gemini response: {json.dumps(payload)[:400]}")


# --------------------------------------------------------------------------- #

def transcribe(audio_bytes, mime_type="audio/ogg"):
    parts = [
        {"inline_data": {"mime_type": mime_type,
                         "data": base64.b64encode(audio_bytes).decode()}},
        {"text": "Transcribe this voice note verbatim into text. "
                 "Return only the transcript, no commentary."},
    ]
    return _call(parts, temperature=0.0)


_SCORE_SYSTEM = """You are a ruthless editorial filter for Meera Pillai, founder of
Skinstinct, a science-led D2C skincare brand. Meera drops raw notes and wants only
the ones worth developing into a LinkedIn post in her voice turned into drafts.

Score the note from 0 to 10 on whether it can become a strong 400-600 word post.
Reward: a specific insight or mechanism, a formulation / ingredient / label-claim
angle, something only an ex-pharma formulator would notice, a concrete scene, data
or a customer question. Penalise: pure logistics, private/operational chatter, vague
motivation, anything with no teachable point, anything not publishable in any form.

Also choose ONE category from: Ingredient Deep-Dive, Formulation Science, Founder
Story, India-Specific Context, Industry Transparency, Brand Philosophy, Consumer
Education.

Also extract 2-4 short topic_keywords for a news search (e.g. "niacinamide",
"sunscreen SPF India", "cosmetics labelling"). Keep them concrete and searchable.

Return JSON only:
{"score": <int 0-10>, "reason": "<one sentence>", "category": "<category>",
 "topic_keywords": ["...", "..."]}"""


def score(note_text):
    raw = _call(
        [{"text": "NOTE:\n" + note_text}],
        system_instruction=_SCORE_SYSTEM,
        want_json=True,
        temperature=0.2,
    )
    data = json.loads(raw)
    return {
        "score": int(data.get("score", 0)),
        "reason": str(data.get("reason", "")).strip(),
        "category": str(data.get("category", "")).strip(),
        "topic_keywords": [str(k).strip() for k in data.get("topic_keywords", []) if k],
    }


def _draft_prompt(note_text, hook, skill_text):
    hook_block = "none"
    if hook:
        hook_block = (
            f'{hook["headline"]} (source: {hook["source"]}, '
            f'{hook.get("published", "")}) {hook["url"]}'
        )
    return (
        skill_text
        + "\n\n=== END OF VOICE SKILL ===\n\n"
        "Write ONE LinkedIn post following every rule above. "
        "Use the note as the substance and the news hook as a way in (drop it if it "
        "does not connect naturally, and say so in NOTES FOR MEERA). "
        "Never invent numbers or facts; use [VERIFY: ...] where a figure is needed.\n\n"
        f"MEERA'S NOTE:\n{note_text}\n\n"
        f"NEWS HOOK:\n{hook_block}\n\n"
        "Return exactly in the output format from section 10 of the skill."
    )


def draft(note_text, hook, skill_text):
    return _call([{"text": _draft_prompt(note_text, hook, skill_text)}],
                 temperature=0.8)


def revise(current_draft, instructions, skill_text):
    prompt = (
        skill_text
        + "\n\n=== END OF VOICE SKILL ===\n\n"
        "Here is a current draft. Revise it according to Meera's instructions while "
        "keeping every rule of her voice. Do not invent facts; keep [VERIFY: ...] "
        "markers where needed. Return in the same section 10 output format.\n\n"
        f"CURRENT DRAFT:\n{current_draft}\n\n"
        f"MEERA'S EDIT INSTRUCTIONS:\n{instructions}"
    )
    return _call([{"text": prompt}], temperature=0.7)
