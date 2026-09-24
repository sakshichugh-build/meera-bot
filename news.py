"""Fetch a recent, relevant news hook from Google News RSS (no API key needed)."""
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


def fetch(keywords):
    """Return the best recent item {headline, source, url, published} or None."""
    if not keywords:
        return None

    # Bias toward recent results with Google News' `when:` operator.
    query = " ".join(keywords) + f" when:{config.NEWS_WINDOW_DAYS}d"
    url = _RSS.format(q=urllib.parse.quote(query))

    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            xml_bytes = resp.read()
    except Exception:
        return None

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return None

    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=config.NEWS_WINDOW_DAYS)
    items = root.findall("./channel/item")

    # Google returns items in relevance order. Take the first that is recent
    # enough; fall back to the very first item if none carry a fresh date.
    fallback = None
    for item in items:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if not title or not link:
            continue
        source_el = item.find("{*}source")
        source = source_el.text.strip() if source_el is not None and source_el.text else ""
        # Google often formats title as "Headline - Source".
        headline = title
        if source and title.endswith(" - " + source):
            headline = title[: -(len(source) + 3)].strip()
        elif " - " in title and not source:
            headline, _, source = title.rpartition(" - ")

        pub_raw = item.findtext("pubDate") or ""
        pub_dt = _parse_date(pub_raw)
        result = {
            "headline": headline,
            "source": source or "Google News",
            "url": link,
            "published": pub_dt.date().isoformat() if pub_dt else "",
        }
        if fallback is None:
            fallback = result
        if pub_dt and pub_dt >= cutoff:
            return result

    return fallback
