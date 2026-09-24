"""Meera -> LinkedIn draft bot.

Flow:
  1. Note (text or voice) arrives in Telegram.
  2. Voice is transcribed by Gemini.
  3. Gemini scores it. Below threshold -> "Parked (score X/10): reason". Stop.
  4. At/above threshold -> fetch a Google News hook for the note's keywords.
  5. Gemini drafts the post in Meera's voice using skill + note + hook.
  6. Bot sends the draft + score + news source with Approve / Edit / Reject.
  7. Everything is logged to SQLite.
"""
import time
import traceback

import config
import store
import tg
import gemini
import news

# chat_id -> note_id awaiting edit instructions
PENDING_EDIT = {}

TG_LIMIT = 4000  # stay under Telegram's 4096 hard limit


def log(*a):
    print(time.strftime("[%H:%M:%S]"), *a, flush=True)


def load_skill():
    with open(config.SKILL_PATH, "r", encoding="utf-8") as fh:
        return fh.read()


SKILL_TEXT = ""


# --------------------------------------------------------------------------- #
# Sending helpers
# --------------------------------------------------------------------------- #

def _chunk(text):
    out, buf = [], ""
    for para in text.split("\n\n"):
        piece = (buf + "\n\n" + para) if buf else para
        if len(piece) <= TG_LIMIT:
            buf = piece
        else:
            if buf:
                out.append(buf)
            # A single paragraph longer than the limit gets hard-split.
            while len(para) > TG_LIMIT:
                out.append(para[:TG_LIMIT])
                para = para[TG_LIMIT:]
            buf = para
    if buf:
        out.append(buf)
    return out or [""]


def send_review(chat_id, note_id, header, draft_text):
    """Send header + draft, attach the decision buttons to the last message."""
    buttons = [[
        {"text": "✅ Approve", "callback_data": f"approve:{note_id}"},
        {"text": "✏️ Edit", "callback_data": f"edit:{note_id}"},
        {"text": "❌ Reject", "callback_data": f"reject:{note_id}"},
    ]]
    tg.send_message(chat_id, header)
    chunks = _chunk(draft_text)
    last_id = None
    for i, ch in enumerate(chunks):
        is_last = i == len(chunks) - 1
        resp = tg.send_message(chat_id, ch, buttons=buttons if is_last else None)
        if is_last and resp.get("ok"):
            last_id = resp["result"]["message_id"]
    return last_id


# --------------------------------------------------------------------------- #
# Core pipeline
# --------------------------------------------------------------------------- #

def process_note(chat_id, message_id, text, is_voice):
    text = (text or "").strip()
    if not text:
        return
    note_id = store.add_note(chat_id, message_id, is_voice, text)
    log(f"note #{note_id} ({'voice' if is_voice else 'text'}): {text[:60]!r}")

    # 3. Score.
    try:
        sc = gemini.score(text)
    except Exception as e:
        tg.send_message(chat_id, f"Couldn't score that note (Gemini error): {e}")
        log("score error:", e)
        return
    store.set_score(note_id, sc["score"], config.SCORE_THRESHOLD,
                    sc["reason"], sc["category"], sc["topic_keywords"])
    log(f"  score={sc['score']} cat={sc['category']} kw={sc['topic_keywords']}")

    if sc["score"] < config.SCORE_THRESHOLD:
        store.mark_parked(note_id)
        tg.send_message(
            chat_id,
            f"\U0001f17f️ Parked (score {sc['score']}/10): {sc['reason']}",
            reply_to=message_id,
        )
        return

    # 4. News hook.
    hook = None
    try:
        hook = news.fetch(sc["topic_keywords"])
    except Exception as e:
        log("news error:", e)
    store.set_news(note_id, hook)

    # 5. Draft.
    try:
        draft_text = gemini.draft(text, hook, SKILL_TEXT)
    except Exception as e:
        tg.send_message(chat_id, f"Couldn't draft that note (Gemini error): {e}")
        log("draft error:", e)
        return

    # 6. Send for review.
    if hook:
        src = (f"{hook['source']} — {hook['headline']}\n"
               f"{hook['url']}")
    else:
        src = "none (no relevant recent item found)"
    header = (
        f"\U0001f4dd Draft ready  •  score {sc['score']}/10  •  {sc['category']}\n"
        f"News hook: {src}"
    )
    draft_msg_id = send_review(chat_id, note_id, header, draft_text)
    store.set_draft(note_id, draft_text, draft_msg_id)


def process_revision(chat_id, note_id, instructions):
    note = store.get_note(note_id)
    if not note:
        tg.send_message(chat_id, "Can't find that draft any more.")
        return
    try:
        new_draft = gemini.revise(note["draft_text"], instructions, SKILL_TEXT)
    except Exception as e:
        tg.send_message(chat_id, f"Couldn't revise (Gemini error): {e}")
        return
    store.add_revision(note_id, instructions, new_draft)
    header = f"\U0001f501 Revised draft (edit #{note['revision_count'] + 1})"
    draft_msg_id = send_review(chat_id, note_id, header, new_draft)
    store.set_draft(note_id, new_draft, draft_msg_id)


# --------------------------------------------------------------------------- #
# Update handlers
# --------------------------------------------------------------------------- #

def handle_message(msg):
    chat_id = msg["chat"]["id"]
    message_id = msg["message_id"]
    text = msg.get("text", "")

    # Commands.
    if text.startswith("/start") or text.startswith("/help"):
        tg.send_message(chat_id,
            "Send me a note or a voice note. If it's worth developing I'll score "
            "it, find a news hook and draft a LinkedIn post in Meera's voice for "
            "your review.\n\nCommands: /stats")
        return
    if text.startswith("/stats"):
        s = store.stats()
        wk = store.approved_this_week()
        tg.send_message(chat_id,
            f"This week: {wk}/{config.WEEKLY_TARGET} approved.\n"
            f"All time — approved: {s.get('approved',0)}, "
            f"rejected: {s.get('rejected',0)}, parked: {s.get('parked',0)}, "
            f"pending: {s.get('pending',0)}")
        return

    # Awaiting edit instructions?
    if chat_id in PENDING_EDIT and text:
        note_id = PENDING_EDIT.pop(chat_id)
        process_revision(chat_id, note_id, text)
        return

    # Voice note -> transcribe.
    if "voice" in msg or "audio" in msg:
        media = msg.get("voice") or msg.get("audio")
        try:
            audio = tg.download_file(media["file_id"])
            transcript = gemini.transcribe(audio, media.get("mime_type", "audio/ogg"))
        except Exception as e:
            tg.send_message(chat_id, f"Couldn't transcribe that voice note: {e}")
            log("transcribe error:", e)
            return
        tg.send_message(chat_id, f"\U0001f3a4 Transcribed:\n{transcript}",
                        reply_to=message_id)
        process_note(chat_id, message_id, transcript, is_voice=True)
        return

    if text:
        process_note(chat_id, message_id, text, is_voice=False)


def handle_callback(cb):
    data = cb.get("data", "")
    msg = cb.get("message", {})
    chat_id = msg.get("chat", {}).get("id")
    msg_id = msg.get("message_id")
    if ":" not in data:
        tg.answer_callback(cb["id"])
        return
    action, sid = data.split(":", 1)
    try:
        note_id = int(sid)
    except ValueError:
        tg.answer_callback(cb["id"])
        return

    if action == "approve":
        store.set_decision(note_id, "approved")
        tg.answer_callback(cb["id"], "Approved ✅")
        tg.edit_reply_markup(chat_id, msg_id, [[
            {"text": "✅ Approved", "callback_data": "noop:0"}]])
        note = store.get_note(note_id)
        wk = store.approved_this_week()
        # Give her clean, copy-paste-ready text (just the DRAFT body if we can find it).
        body = _extract_draft_body(note.get("draft_text", "")) if note else ""
        tg.send_message(chat_id,
            f"Approved. {wk}/{config.WEEKLY_TARGET} this week.\n\n"
            "Copy-paste ready:\n\n" + (body or "(see draft above)"))

    elif action == "reject":
        store.set_decision(note_id, "rejected")
        tg.answer_callback(cb["id"], "Rejected ❌")
        tg.edit_reply_markup(chat_id, msg_id, [[
            {"text": "❌ Rejected", "callback_data": "noop:0"}]])

    elif action == "edit":
        PENDING_EDIT[chat_id] = note_id
        tg.answer_callback(cb["id"], "Send your edit instructions")
        tg.send_message(chat_id,
            "✏️ What should change? Send your edit instructions as your "
            "next message (e.g. \"make the open a customer question, cut the last "
            "paragraph\").")
    else:
        tg.answer_callback(cb["id"])


def _extract_draft_body(full):
    """Pull just the post body out of the skill's CATEGORY/HOOK/DRAFT/NOTES block."""
    if "DRAFT:" not in full:
        return full.strip()
    body = full.split("DRAFT:", 1)[1]
    for marker in ("NOTES FOR MEERA", "NOTES:"):
        if marker in body:
            body = body.split(marker, 1)[0]
    return body.strip()


# --------------------------------------------------------------------------- #

def main():
    global SKILL_TEXT
    store.init()
    SKILL_TEXT = load_skill()
    log(f"Bot up. model={config.GEMINI_MODEL} threshold={config.SCORE_THRESHOLD}")

    offset = 0
    while True:
        try:
            resp = tg.get_updates(offset)
        except Exception as e:
            log("getUpdates error:", e)
            time.sleep(3)
            continue
        if not resp.get("ok"):
            log("getUpdates not ok:", str(resp)[:200])
            time.sleep(3)
            continue

        for upd in resp["result"]:
            offset = upd["update_id"] + 1
            try:
                if "callback_query" in upd:
                    handle_callback(upd["callback_query"])
                elif "message" in upd:
                    handle_message(upd["message"])
                elif "channel_post" in upd:
                    handle_message(upd["channel_post"])
            except Exception:
                log("handler error:\n" + traceback.format_exc())


if __name__ == "__main__":
    main()
