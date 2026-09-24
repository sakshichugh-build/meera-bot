"""Thin Telegram Bot API wrapper (stdlib only)."""
import json
import urllib.request
import urllib.error

import config

_API = "https://api.telegram.org/bot" + config.TELEGRAM_TOKEN + "/"
_FILE = "https://api.telegram.org/file/bot" + config.TELEGRAM_TOKEN + "/"


def _post(method, params):
    data = json.dumps(params).encode("utf-8")
    req = urllib.request.Request(
        _API + method, data=data, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=70) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": e.read().decode("utf-8", "replace")}


def get_updates(offset, timeout=50):
    return _post("getUpdates", {
        "offset": offset,
        "timeout": timeout,
        "allowed_updates": ["message", "channel_post", "callback_query"],
    })


def send_message(chat_id, text, buttons=None, reply_to=None):
    params = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
    if reply_to:
        params["reply_to_message_id"] = reply_to
    if buttons:
        params["reply_markup"] = {"inline_keyboard": buttons}
    return _post("sendMessage", params)


def edit_reply_markup(chat_id, message_id, buttons=None):
    return _post("editMessageReplyMarkup", {
        "chat_id": chat_id,
        "message_id": message_id,
        "reply_markup": {"inline_keyboard": buttons or []},
    })


def answer_callback(callback_id, text=None):
    params = {"callback_query_id": callback_id}
    if text:
        params["text"] = text
    return _post("answerCallbackQuery", params)


def download_file(file_id):
    """Return raw bytes for a Telegram file (e.g. a voice note)."""
    meta = _post("getFile", {"file_id": file_id})
    if not meta.get("ok"):
        raise RuntimeError("getFile failed: " + json.dumps(meta)[:200])
    path = meta["result"]["file_path"]
    with urllib.request.urlopen(_FILE + path, timeout=70) as resp:
        return resp.read()
