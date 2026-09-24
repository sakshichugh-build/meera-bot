"""Fetch a recent, relevant news hook from Google News RSS (no API key needed).

Google News treats a multi-word query as an AND of every term, so joining all
of a note's keywords into one string returns almost nothing. Instead we OR the
keyword phrases together and cascade to broader fallbacks until something hits.
"""
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import datetime as dt
import email.utils

import config

_RSS = "https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en"


def _parse_date(text):
    try:
        return email.utils.parsedate_to_datetime(text)
    except Exception:
        return None


def _run_query(query):
    """Fetch one query; return the best item dict or None."""
    url = _RSS.format(q=urllib.parse.quote(query))
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            xml_bytes = resp.read()
        root = ET.fromstring(xml_bytes)
    except Exception:
        return None

    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=config.NEWS_WINDOW_DAYS)
    fallback = None
    for item in root.findall("./channel/item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if not title or not link:
            continue
        source_el = item.find("{*}source")
        source = source_el.text.strip() if source_el is not None and source_el.text else ""
        headline = title
        if source and title.endswith(" - " + source):
            headline = title[: -(len(source) + 3)].strip()
        elif " - " in title and not source:
            headline, _, source = title.rpartition(" - ")

        pub_dt = _parse_date(item.findtext("pubDate") or "")
        result = {
            "headline": headline,
            "source": source or "Google News",
            "url": link,
            "published": pub_dt.date().isoformat() if pub_dt else "",
        }
        if fallback is None:
            fallback = result
        # Google returns items in relevance order; take the first recent one.
        if pub_dt and pub_dt >= cutoff:
            return result
    return fallback


def _candidate_queries(keywords):
    """Queries from most-relevant/recent to broadest, in try order."""
    phrases = [k.strip() for k in keywords if k.strip()]
    if not phrases:
        return []
    n = config.NEWS_WINDOW_DAYS
    or_phrases = " OR ".join(f'"{p}"' for p in phrases)          # exact phrases
    or_words = " OR ".join(sorted({w for p in phrases for w in p.split()}, key=len, reverse=True)[:8])
    return [
        f"{or_phrases} when:{n}d",   # recent + relevant
        f"{phrases[0]} when:{n}d",   # main topic, recent
        or_phrases,                  # relevant, any date
        or_words,                    # broadest, any date
    ]


def fetch(keywords):
    """Return the best recent item {headline, source, url, published} or None."""
    for query in _candidate_queries(keywords):
        hit = _run_query(query)
        if hit:
            return hit
    return None
