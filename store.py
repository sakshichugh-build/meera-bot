"""SQLite logging: every note, score, draft and decision in one row.

The whole point is to be able to track progress toward the 3-posts-a-week
target and to have an audit trail of what the bot did.
"""
import sqlite3
import datetime as dt

import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TEXT NOT NULL,
    chat_id         INTEGER,
    src_message_id  INTEGER,
    is_voice        INTEGER DEFAULT 0,
    raw_text        TEXT,            -- typed text OR voice transcript
    score           INTEGER,
    threshold       INTEGER,
    reason          TEXT,
    category        TEXT,
    topic_keywords  TEXT,            -- comma-joined
    parked          INTEGER DEFAULT 0,
    news_headline   TEXT,
    news_source     TEXT,
    news_url        TEXT,
    news_published  TEXT,
    draft_text      TEXT,
    draft_message_id INTEGER,        -- the message that carries the buttons
    revision_count  INTEGER DEFAULT 0,
    edit_instructions TEXT,
    decision        TEXT DEFAULT 'pending',   -- pending|approved|rejected|parked
    decided_at      TEXT
);
"""


def _conn():
    c = sqlite3.connect(config.DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init():
    with _conn() as c:
        c.executescript(_SCHEMA)


def _now():
    return dt.datetime.now().isoformat(timespec="seconds")


def add_note(chat_id, src_message_id, is_voice, raw_text):
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO notes (created_at, chat_id, src_message_id, is_voice, raw_text)"
            " VALUES (?,?,?,?,?)",
            (_now(), chat_id, src_message_id, 1 if is_voice else 0, raw_text),
        )
        return cur.lastrowid


def set_score(note_id, score, threshold, reason, category, keywords):
    with _conn() as c:
        c.execute(
            "UPDATE notes SET score=?, threshold=?, reason=?, category=?, topic_keywords=?"
            " WHERE id=?",
            (score, threshold, reason, category, ", ".join(keywords or []), note_id),
        )


def mark_parked(note_id):
    with _conn() as c:
        c.execute(
            "UPDATE notes SET parked=1, decision='parked', decided_at=? WHERE id=?",
            (_now(), note_id),
        )


def set_news(note_id, hook):
    with _conn() as c:
        if hook:
            c.execute(
                "UPDATE notes SET news_headline=?, news_source=?, news_url=?, news_published=?"
                " WHERE id=?",
                (hook["headline"], hook["source"], hook["url"],
                 hook.get("published", ""), note_id),
            )


def set_draft(note_id, draft_text, draft_message_id=None):
    with _conn() as c:
        if draft_message_id is not None:
            c.execute(
                "UPDATE notes SET draft_text=?, draft_message_id=? WHERE id=?",
                (draft_text, draft_message_id, note_id),
            )
        else:
            c.execute("UPDATE notes SET draft_text=? WHERE id=?", (draft_text, note_id))


def add_revision(note_id, instructions, new_draft):
    with _conn() as c:
        c.execute(
            "UPDATE notes SET draft_text=?, edit_instructions=?,"
            " revision_count=revision_count+1 WHERE id=?",
            (new_draft, instructions, note_id),
        )


def set_decision(note_id, decision):
    with _conn() as c:
        c.execute(
            "UPDATE notes SET decision=?, decided_at=? WHERE id=?",
            (decision, _now(), note_id),
        )


def get_note(note_id):
    with _conn() as c:
        row = c.execute("SELECT * FROM notes WHERE id=?", (note_id,)).fetchone()
        return dict(row) if row else None


def approved_this_week():
    """Count posts approved since Monday 00:00 (local)."""
    today = dt.date.today()
    monday = today - dt.timedelta(days=today.weekday())
    start = dt.datetime.combine(monday, dt.time.min).isoformat(timespec="seconds")
    with _conn() as c:
        row = c.execute(
            "SELECT COUNT(*) AS n FROM notes WHERE decision='approved' AND decided_at>=?",
            (start,),
        ).fetchone()
        return row["n"]


def stats():
    with _conn() as c:
        rows = c.execute(
            "SELECT decision, COUNT(*) AS n FROM notes GROUP BY decision"
        ).fetchall()
        return {r["decision"]: r["n"] for r in rows}
