"""Offline smoke test: imports, DB round-trip, chunking, news, Gemini reachability.

Run:  python3 selftest.py
Exercises everything that does not require a live chat. Gemini is only pinged if
a real-looking key is present.
"""
import config, store, news, gemini, bot


def ok(label):
    print("  ok  -", label)


def main():
    print("1. config")
    assert config.TELEGRAM_TOKEN
    ok(f"threshold={config.SCORE_THRESHOLD} model={config.GEMINI_MODEL}")

    print("2. db round-trip")
    store.init()
    nid = store.add_note(123, 1, False, "test note about niacinamide pH")
    store.set_score(nid, 8, 6, "specific mechanism", "Formulation Science",
                    ["niacinamide", "pH"])
    store.set_news(nid, {"headline": "H", "source": "S", "url": "http://x",
                         "published": "2026-09-20"})
    store.set_draft(nid, "DRAFT:\nbody\nNOTES FOR MEERA:\n- x", 999)
    store.set_decision(nid, "approved")
    row = store.get_note(nid)
    assert row["score"] == 8 and row["decision"] == "approved"
    ok(f"note #{nid} stored, approved_this_week={store.approved_this_week()}")

    print("3. draft-body extraction")
    body = bot._extract_draft_body("CATEGORY: x\nHOOK USED: y\n\nDRAFT:\nHello.\n\nNOTES FOR MEERA:\n- z")
    assert body == "Hello.", repr(body)
    ok("extracted clean body")

    print("4. chunker")
    chunks = bot._chunk("para\n\n" * 3000)
    assert all(len(c) <= bot.TG_LIMIT for c in chunks)
    ok(f"{len(chunks)} chunks, all <= limit")

    print("5. news (live Google News RSS)")
    hook = news.fetch(["niacinamide", "skincare"])
    if hook:
        ok(f"{hook['source']}: {hook['headline'][:60]} ({hook['published']})")
    else:
        print("  --  no items returned (network?) - not fatal")

    print("6. gemini reachability")
    key = config.GEMINI_API_KEY
    if not key or "PASTE" in key:
        print("  --  skipped: no GEMINI_API_KEY set in .env")
    else:
        try:
            r = gemini.score("At the trade fair a supplier couldn't tell me the pH "
                             "of their vitamin C serum. That tells you something.")
            ok(f"score={r['score']} cat={r['category']} kw={r['topic_keywords']}")
        except Exception as e:
            print("  !!  gemini error:", e)

    print("\nDone.")


if __name__ == "__main__":
    main()
