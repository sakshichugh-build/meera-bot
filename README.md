# Meera → LinkedIn draft bot

Turns Meera's raw Telegram notes (text or voice) into LinkedIn drafts in her voice,
for her to review. Python **standard library only** — no `pip install`.

## Flow

1. Note or voice note arrives in Telegram.
2. Voice notes are transcribed by Gemini.
3. Gemini scores the note 0–10. Below the threshold → `🅿️ Parked (score X/10): reason`, stop.
4. At/above the threshold → fetch a recent Google News item for the note's keywords.
5. Gemini drafts the post using `SKILL.md` (Meera's voice) + the note + the news hook.
6. The bot sends the draft with score + news source and **Approve / Edit / Reject** buttons.
7. Every note, score, draft and decision is logged to `meera.db` (SQLite).

## Setup

1. Put a **valid** Gemini key in `.env` (`GEMINI_API_KEY=AIza...`, from
   https://aistudio.google.com/apikey). The Telegram token is already set.
2. Add the bot **@SC_L_Bot** as an **admin** of the channel so it can read posts
   and reply. (In a DM it works with no extra setup.)
3. Smoke test (no chat needed):
   ```bash
   python3 selftest.py
   ```
4. Run it:
   ```bash
   python3 bot.py
   ```

Send a note to the bot (or drop one in the channel) and watch it score, hook and draft.

## Files

| File | Job |
|------|-----|
| `bot.py` | Main long-polling loop, handlers, buttons, edit flow |
| `gemini.py` | Transcribe / score / draft / revise via Gemini REST |
| `news.py` | Google News RSS hook (India edition, recent) |
| `store.py` | SQLite logging + weekly-progress query |
| `tg.py` | Telegram Bot API wrapper |
| `config.py` | Loads `.env` |
| `SKILL.md` | Meera's voice skill (the only voice reference) |
| `selftest.py` | Offline smoke test |

## Config (`.env`)

- `SCORE_THRESHOLD` (default `6`) — notes below this are parked.
- `WEEKLY_TARGET` (default `3`) — used for the "X/3 this week" line on Approve.
- `GEMINI_MODEL` (default `gemini-2.5-flash`).
- `NEWS_WINDOW_DAYS` (default `14`) — how recent a news hook must be.

## Notes / scope

- **No auto-publish to LinkedIn.** The bot stops at the review gate — Approve just
  records the decision and hands back clean copy-paste text. This is deliberate:
  the human review step is the point (Meera passed on end-to-end tools).
- **Editing:** tap *Edit*, then send your instructions as the next message; Gemini
  revises and re-sends with buttons.
- **`/stats`** shows this week's approved count and all-time totals.
- Scoring, news search and drafting all require a working Gemini key.

## Inspect the log

```bash
sqlite3 meera.db "SELECT id, score, decision, category, substr(raw_text,1,40) FROM notes ORDER BY id DESC;"
```
