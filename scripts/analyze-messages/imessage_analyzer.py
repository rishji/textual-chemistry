#!/usr/bin/env python3
"""Chunked local analysis for a copied macOS Messages database.

This script is intentionally local-first:
- reads only a copied chat.db under data/private/messages by default
- writes derived summaries under data/private/processed
- processes bounded date/month ranges so expensive work is easy to stop
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import math
import re
import sqlite3
import string
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = PROJECT_ROOT / "data/private/messages/chat.db"
DEFAULT_WHATSAPP_DB = PROJECT_ROOT / "data/private/messages/whatsapp.db"
DEFAULT_OUT = PROJECT_ROOT / "data/private/processed"
APPLE_EPOCH_OFFSET = 978_307_200
DEFAULT_CHAT_ID = 34
DEFAULT_WHATSAPP_CHAT_ID = 1

STOP_WORDS = {
    "a",
    "about",
    "after",
    "all",
    "also",
    "am",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "been",
    "but",
    "by",
    "can",
    "com",
    "did",
    "didn",
    "do",
    "does",
    "don",
    "for",
    "from",
    "get",
    "going",
    "got",
    "had",
    "has",
    "have",
    "he",
    "her",
    "here",
    "him",
    "his",
    "how",
    "i",
    "if",
    "im",
    "in",
    "is",
    "it",
    "its",
    "just",
    "like",
    "me",
    "my",
    "no",
    "not",
    "now",
    "of",
    "oh",
    "ok",
    "okay",
    "on",
    "one",
    "or",
    "our",
    "she",
    "so",
    "some",
    "that",
    "the",
    "they",
    "then",
    "there",
    "this",
    "to",
    "too",
    "u",
    "up",
    "was",
    "we",
    "were",
    "what",
    "when",
    "with",
    "www",
    "you",
    "your",
}

ARCHIVE_TERMS = {
    "attribute",
    "archiver",
    "streamtyped",
    "nsattributedstring",
    "nsstring",
    "nsobject",
    "nsdictionary",
    "nscolor",
    "nsfont",
    "nsparagraphstyle",
    "nskeyedarchiver",
    "icloud",
    "com.apple",
    "kim",
    "version",
    "objects",
    "class",
    "topx",
    "aloved",
    "locationzns",
    "rangeval",
    "rangevalue",
    "url",
    "uuid",
}

TOPIC_PHRASES = {
    "girlfriend": ["girlfriend"],
    "wedding": ["wedding", "weddings"],
    "engagement": ["engagement", "engaged"],
    "proposal": ["proposal", "propose", "proposed", "proposing"],
    "ring": ["ring", "rings"],
    "marry": ["marry", "married", "marriage"],
    "fiance": ["fiance", "fiancée", "fiancee"],
    "venue": ["venue", "venues"],
    "guest": ["guest", "guests"],
    "invite": ["invite", "invites", "invited", "invitation", "invitations"],
    "honeymoon": ["honeymoon"],
    "family": ["family", "families"],
    "parents": ["parents", "mom", "dad", "mother", "father"],
    "home": ["home", "apartment", "house", "place"],
    "travel": ["flight", "flights", "airport", "airports", "hotel", "hotels", "trip", "trips", "travel"],
    "cutie": ["cutie"],
    "baby": ["baby"],
    "love": ["love", "loved", "lovely"],
    "babe": ["babe"],
    "honey": ["honey"],
    "ctp": ["ctp"],
    "hb": ["hb"],
    "ctphb": ["ctphb", "ctp hb"],
    "cutie_pie": ["cutie pie"],
    "qtpi": ["qtpi", "qt pi"],
}

CATEGORY_PHRASES = {
    "affection": [
        "cutie",
        "baby",
        "love",
        "loved",
        "babe",
        "honey",
        "ctp",
        "hb",
        "cutie pie",
        "qtpi",
        "miss you",
        "proud of you",
    ],
    "wedding": [
        "wedding",
        "engagement",
        "engaged",
        "proposal",
        "propose",
        "ring",
        "marry",
        "fiance",
        "fiancee",
        "venue",
        "guest",
        "invite",
        "honeymoon",
    ],
    "travel": ["flight", "airport", "hotel", "trip", "travel", "passport", "luggage"],
    "humor": ["lol", "haha", "funny", "lmao", "hehe", "joke"],
    "logistics": ["call", "meeting", "calendar", "book", "reservation", "time", "schedule"],
}

CATEGORY_ORDER = ["affection", "wedding", "travel", "humor", "logistics"]


def connect(db_path: Path) -> sqlite3.Connection:
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def apple_ns_to_datetime(value: int) -> dt.datetime:
    seconds = value / 1_000_000_000 + APPLE_EPOCH_OFFSET
    return dt.datetime.fromtimestamp(seconds)


def month_bounds(month: str) -> tuple[str, str]:
    start = dt.date.fromisoformat(f"{month}-01")
    if start.month == 12:
        end = dt.date(start.year + 1, 1, 1)
    else:
        end = dt.date(start.year, start.month + 1, 1)
    return start.isoformat(), end.isoformat()


def iter_messages(
    conn: sqlite3.Connection,
    chat_id: int,
    start_day: str | None,
    end_day: str | None,
) -> list[sqlite3.Row]:
    where = ["cmj.chat_id = ?"]
    params: list[Any] = [chat_id]
    if start_day:
        where.append("datetime(m.date / 1000000000 + 978307200, 'unixepoch', 'localtime') >= ?")
        params.append(start_day)
    if end_day:
        where.append("datetime(m.date / 1000000000 + 978307200, 'unixepoch', 'localtime') < ?")
        params.append(end_day)

    query = f"""
        select
          m.rowid,
          m.date,
          m.is_from_me,
          m.text,
          m.attributedBody,
          m.cache_has_attachments,
          m.associated_message_type,
          m.associated_message_emoji
        from chat_message_join cmj
        join message m on m.rowid = cmj.message_id
        where {" and ".join(where)}
        order by m.date
    """
    return list(conn.execute(query, params))


def count_chat_attachments(conn: sqlite3.Connection, chat_id: int) -> int:
    query = """
        select count(distinct maj.attachment_id)
        from chat_message_join cmj
        join message_attachment_join maj on maj.message_id = cmj.message_id
        where cmj.chat_id = ?
    """
    return int(conn.execute(query, [chat_id]).fetchone()[0] or 0)


def clean_archive_text(blob: bytes | None) -> str:
    """Best-effort rich-text extraction from attributedBody.

    Apple stores modern Messages text as archived rich text. A full decoder is a
    separate concern; this heuristic extracts readable runs and filters obvious
    archive metadata. It is good enough for aggregate word/emoji discovery, then
    candidate snippets can be manually reviewed in private files.
    """
    if not blob:
        return ""

    decoded = blob.decode("utf-8", errors="ignore")
    decoded = decoded.replace("\ufffc", " ")
    runs = re.findall(r"[^\x00-\x1f\x7f]{2,}", decoded)
    candidates: list[str] = []

    for run in runs:
        lowered = run.lower()
        if any(term in lowered for term in ARCHIVE_TERMS):
            continue
        cleaned = "".join(ch if ch.isprintable() else " " for ch in run)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if len(cleaned) < 2:
            continue
        alpha_count = sum(ch.isalpha() for ch in cleaned)
        emojiish_count = sum(ord(ch) > 10_000 for ch in cleaned)
        if alpha_count == 0 and emojiish_count == 0:
            continue
        if cleaned in string.punctuation:
            continue
        candidates.append(cleaned)

    # The actual message text is usually the most human-looking retained run.
    candidates.sort(key=lambda value: (score_human_text(value), len(value)), reverse=True)
    return candidates[0] if candidates else ""


def score_human_text(value: str) -> float:
    letters = sum(ch.isalpha() for ch in value)
    spaces = value.count(" ")
    archive_penalty = sum(value.lower().count(term) for term in ARCHIVE_TERMS) * 10
    return letters + spaces * 1.5 - archive_penalty


def message_text(row: sqlite3.Row) -> str:
    direct = row["text"]
    if direct:
        return str(direct)
    return clean_archive_text(row["attributedBody"])


def tokenize(text: str) -> list[str]:
    text = re.sub(r"https?://\S+|www\.\S+", " ", text)
    return [
        token
        for token in re.findall(r"[a-zA-Z][a-zA-Z']{1,}", text.lower())
        if is_content_token(token)
    ]


def is_content_token(token: str) -> bool:
    if token in STOP_WORDS or len(token) <= 2:
        return False
    if any(term in token for term in ARCHIVE_TERMS):
        return False
    if token.startswith(("ns", "ck", "im")) and len(token) > 6:
        return False
    return True


def emoji_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    index = 0
    while index < len(text):
        ch = text[index]
        codepoint = ord(ch)
        if ch in {"\ufe0f", "\ufffc"}:
            index += 1
            continue
        if codepoint <= 10_000 and ch not in {"❤"}:
            index += 1
            continue

        token = ch
        index += 1
        while index < len(text):
            modifier = text[index]
            modifier_codepoint = ord(modifier)
            if modifier == "\ufe0f" or 0x1F3FB <= modifier_codepoint <= 0x1F3FF:
                token += modifier
                index += 1
                continue
            break
        tokens.append(token.replace("\ufe0f", ""))
    return [token for token in tokens if token]


def normalized_search_text(text: str) -> str:
    lowered = text.lower().replace("fiancée", "fiancee")
    return re.sub(r"\s+", " ", lowered)


def contains_phrase(text: str, phrase: str) -> bool:
    normalized = normalized_search_text(text)
    escaped = re.escape(phrase.lower())
    pattern = rf"(?<![a-z0-9]){escaped}(?![a-z0-9])"
    return re.search(pattern, normalized) is not None


def semantic_topic_allowed(text: str, topic: str) -> bool:
    normalized = normalized_search_text(text)
    if topic == "proposal" and re.search(r"\bi propose (we|that|to)\b|\bproposing (a|an|the)? ?(plan|time|idea)\b", normalized):
        return False
    if topic == "ring" and re.search(r"\b(phone|doorbell|alarm|bell|ringtone)\b|\brings?\b.*\b(call|phone|doorbell)\b", normalized):
        return False
    if topic == "baby" and re.search(r"\b(their|his|her|your|a|the) baby\b|\bbaby (photo|picture|shower|name|names)\b", normalized):
        return False
    if topic == "wedding" and re.search(r"\b(varun|friend|friends|cousin|cousins|their|his|her|someone else)(?:'s)? wedding\b", normalized):
        return False
    return True


def find_topic_hits(text: str) -> list[str]:
    hits: list[str] = []
    for topic, phrases in TOPIC_PHRASES.items():
        if any(contains_phrase(text, phrase) for phrase in phrases) and semantic_topic_allowed(text, topic):
            hits.append(topic)
    return hits


def semantic_category_phrase_allowed(text: str, category: str, phrase: str) -> bool:
    if category == "affection" and phrase == "baby":
        return semantic_topic_allowed(text, "baby")
    if category == "wedding":
        phrase_topics = {
            "wedding": "wedding",
            "proposal": "proposal",
            "propose": "proposal",
            "ring": "ring",
        }
        topic = phrase_topics.get(phrase)
        if topic:
            return semantic_topic_allowed(text, topic)
    return True


def classify_message(text: str) -> list[str]:
    categories = []
    for category in CATEGORY_ORDER:
        phrases = CATEGORY_PHRASES[category]
        if any(contains_phrase(text, phrase) and semantic_category_phrase_allowed(text, category, phrase) for phrase in phrases):
            categories.append(category)
    return categories


def count_term_mentions(text: str, phrases: list[str]) -> int:
    normalized = normalized_search_text(text)
    count = 0
    for phrase in sorted(phrases, key=len, reverse=True):
        escaped = re.escape(phrase.lower())
        pattern = rf"(?<![a-z0-9]){escaped}(?![a-z0-9])"
        if phrase == "cutie":
            pattern = r"(?<![a-z0-9])cutie(?!\s*pie|pie|[a-z0-9])"
        elif phrase == "ctp":
            pattern = r"(?<![a-z0-9])ctp(?!\s*hb|[a-z0-9])"
        elif phrase == "hb":
            pattern = r"(?<![a-z0-9])(?<!ctp )hb(?![a-z0-9])"
        matches = list(re.finditer(pattern, normalized))
        count += len(matches)
        normalized = re.sub(pattern, " ", normalized)
    return count


def summarize_metadata(rows: list[sqlite3.Row]) -> dict[str, Any]:
    by_day: collections.Counter[str] = collections.Counter()
    by_hour: collections.Counter[str] = collections.Counter()
    by_weekday: collections.Counter[str] = collections.Counter()
    by_sender: collections.Counter[str] = collections.Counter()

    for row in rows:
        when = apple_ns_to_datetime(row["date"])
        sender = "Rishi" if row["is_from_me"] else "Esha"
        by_day[when.date().isoformat()] += 1
        by_hour[f"{when.hour:02d}"] += 1
        by_weekday[when.strftime("%A")] += 1
        by_sender[sender] += 1

    days = sorted(by_day)
    total_days = 0
    active_pct = None
    if days:
        start = dt.date.fromisoformat(days[0])
        end = dt.date.fromisoformat(days[-1])
        total_days = (end - start).days + 1
        active_pct = round(100 * len(days) / total_days, 1)

    return {
        "messageCount": len(rows),
        "dateRange": {"first": days[0] if days else None, "last": days[-1] if days else None},
        "activeDays": len(days),
        "totalCalendarDays": total_days,
        "quietDays": total_days - len(days) if days else 0,
        "activeDayPct": active_pct,
        "senderBreakdown": dict(by_sender),
        "byHour": dict(sorted(by_hour.items())),
        "byWeekday": dict(by_weekday.most_common()),
        "busiestDays": by_day.most_common(10),
    }


def row_value(row: sqlite3.Row | dict[str, Any], key: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row[key]
    except (IndexError, KeyError):
        return default


def weekday_occurrences(start: dt.date, end: dt.date) -> dict[int, int]:
    counts = {day: 0 for day in range(7)}
    current = start
    while current <= end:
        # Site heatmap uses Sunday as 0.
        site_weekday = (current.weekday() + 1) % 7
        counts[site_weekday] += 1
        current += dt.timedelta(days=1)
    return counts


def summarize_site_message_sources(sources: dict[str, list[sqlite3.Row | dict[str, Any]]]) -> dict[str, Any]:
    by_day: collections.Counter[str] = collections.Counter()
    by_month: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    by_year: collections.Counter[str] = collections.Counter()
    by_heat: collections.Counter[tuple[int, int]] = collections.Counter()
    by_weekday: collections.Counter[int] = collections.Counter()
    by_sender: collections.Counter[str] = collections.Counter()
    by_source: collections.Counter[str] = collections.Counter()
    attachments = 0

    for source, rows in sources.items():
        for row in rows:
            when = apple_ns_to_datetime(row_value(row, "date"))
            sender = "Rishi" if row_value(row, "is_from_me") else "Esha"
            day = when.date().isoformat()
            month_key = when.strftime("%Y-%m")
            year = when.strftime("%Y")
            site_weekday = int(when.strftime("%w"))
            by_day[day] += 1
            by_month[month_key][source] += 1
            by_year[year] += 1
            by_heat[(site_weekday, when.hour)] += 1
            by_weekday[site_weekday] += 1
            by_sender[sender] += 1
            by_source[source] += 1
            attachments += int(row_value(row, "cache_has_attachments", 0) or 0)

    days = sorted(by_day)
    total_days = 0
    active_pct = None
    weekday_averages = [0 for _ in range(7)]
    if days:
        start = dt.date.fromisoformat(days[0])
        end = dt.date.fromisoformat(days[-1])
        total_days = (end - start).days + 1
        active_pct = round(100 * len(days) / total_days, 1)
        weekday_counts = weekday_occurrences(start, end)
        weekday_averages = [
            round(by_weekday[day] / max(1, weekday_counts[day]), 1)
            for day in range(7)
        ]

    months = []
    for month_key in sorted(by_month):
        month_date = dt.date.fromisoformat(f"{month_key}-01")
        month_sources = dict(by_month[month_key])
        month_days = {day for day in by_day if day.startswith(month_key)}
        months.append(
            {
                "month": month_date.strftime("%b %y"),
                "monthKey": month_key,
                "messages": sum(month_sources.values()),
                "activeDays": len(month_days),
                "sourceBreakdown": month_sources,
            }
        )

    return {
        "schemaVersion": 1,
        "generatedAt": dt.datetime.now().isoformat(timespec="seconds"),
        "totals": {
            "messageCount": sum(by_source.values()),
            "activeDays": len(days),
            "totalCalendarDays": total_days,
            "quietDays": total_days - len(days) if days else 0,
            "activeDayPct": active_pct,
            "senderBreakdown": dict(by_sender),
            "sourceBreakdown": dict(by_source),
            "attachments": attachments,
        },
        "years": [{"year": year, "messages": count} for year, count in sorted(by_year.items())],
        "months": months,
        "weekdayAverages": weekday_averages,
        "heatmap": [[day, hour, count] for (day, hour), count in sorted(by_heat.items())],
    }


def summarize_text(rows: list[sqlite3.Row]) -> dict[str, Any]:
    words: collections.Counter[str] = collections.Counter()
    emojis: collections.Counter[str] = collections.Counter()
    extracted = 0
    empty = 0
    by_sender_words: dict[str, collections.Counter[str]] = {
        "Rishi": collections.Counter(),
        "Esha": collections.Counter(),
    }

    for row in rows:
        text = message_text(row)
        if not text:
            empty += 1
            continue
        extracted += 1
        sender = "Rishi" if row["is_from_me"] else "Esha"
        row_words = tokenize(text)
        row_emojis = emoji_tokens(text)
        words.update(row_words)
        emojis.update(row_emojis)
        by_sender_words[sender].update(row_words)

    signature_words = []
    for word, total in words.most_common(250):
        rishi = by_sender_words["Rishi"][word]
        esha = by_sender_words["Esha"][word]
        if total >= 3 and rishi and esha:
            balance = min(rishi, esha) / max(rishi, esha)
            signature_words.append({"word": word, "total": total, "rishi": rishi, "esha": esha, "balance": round(balance, 2)})

    return {
        "extractedTextRows": extracted,
        "emptyTextRows": empty,
        "extractionRatePct": round(100 * extracted / max(1, extracted + empty), 1),
        "topWords": words.most_common(75),
        "topEmojis": emojis.most_common(50),
        "sharedSignatureWords": signature_words[:50],
    }


def snippet_object(row: sqlite3.Row, text: str, topics: list[str], categories: list[str]) -> dict[str, Any]:
    when = apple_ns_to_datetime(row["date"])
    return {
        "date": when.isoformat(timespec="seconds"),
        "month": when.strftime("%Y-%m"),
        "sender": "Rishi" if row["is_from_me"] else "Esha",
        "text": text[:900],
        "topics": topics,
        "categories": categories,
        "emojis": emoji_tokens(text),
    }


def snippet_score(snippet: dict[str, Any]) -> float:
    text = snippet["text"]
    score = len(snippet["topics"]) * 5 + len(snippet["categories"]) * 3 + len(snippet["emojis"]) * 2
    if 25 <= len(text) <= 350:
        score += 5
    if any(category in snippet["categories"] for category in ["affection", "wedding", "humor"]):
        score += 4
    return score


def summarize_topic_snippets(rows: list[sqlite3.Row]) -> dict[str, Any]:
    topic_counts: dict[str, collections.Counter[str]] = {
        topic: collections.Counter() for topic in TOPIC_PHRASES
    }
    category_counts: dict[str, collections.Counter[str]] = {
        category: collections.Counter() for category in CATEGORY_ORDER
    }
    first_mentions: dict[str, dict[str, Any]] = {}
    topic_examples: dict[str, list[dict[str, Any]]] = {topic: [] for topic in TOPIC_PHRASES}
    category_examples: dict[str, list[dict[str, Any]]] = {category: [] for category in CATEGORY_ORDER}
    emoji_highlights: list[dict[str, Any]] = []
    interesting_snippets: list[dict[str, Any]] = []

    for row in rows:
        text = message_text(row)
        if not text:
            continue
        topics = find_topic_hits(text)
        categories = classify_message(text)
        emojis = emoji_tokens(text)
        if not topics and not categories and len(emojis) < 2:
            continue

        snippet = snippet_object(row, text, topics, categories)
        month = snippet["month"]
        for topic in topics:
            topic_counts[topic][month] += 1
            if topic not in first_mentions:
                first_mentions[topic] = snippet
            if len(topic_examples[topic]) < 12:
                topic_examples[topic].append(snippet)
        for category in categories:
            category_counts[category][month] += 1
            if len(category_examples[category]) < 30:
                category_examples[category].append(snippet)
        if len(emojis) >= 2 and len(emoji_highlights) < 150:
            emoji_highlights.append(snippet)
        interesting_snippets.append(snippet)

    topic_summary = {}
    for topic, counts in topic_counts.items():
        total = sum(counts.values())
        if total == 0:
            continue
        peak_month, peak_count = counts.most_common(1)[0]
        topic_summary[topic] = {
            "total": total,
            "firstMention": first_mentions.get(topic),
            "peakMonth": peak_month,
            "peakMonthCount": peak_count,
            "byMonth": dict(sorted(counts.items())),
            "examples": topic_examples[topic],
        }

    category_summary = {}
    for category, counts in category_counts.items():
        total = sum(counts.values())
        category_summary[category] = {
            "total": total,
            "byMonth": dict(sorted(counts.items())),
            "examples": sorted(category_examples[category], key=snippet_score, reverse=True)[:20],
        }

    return {
        "schemaVersion": 1,
        "generatedAt": dt.datetime.now().isoformat(timespec="seconds"),
        "topics": topic_summary,
        "categories": category_summary,
        "emojiHighlights": sorted(emoji_highlights, key=snippet_score, reverse=True)[:75],
        "interestingSnippets": sorted(interesting_snippets, key=snippet_score, reverse=True)[:250],
        "conversationEras": propose_conversation_eras(topic_summary, category_summary),
    }


def propose_conversation_eras(topic_summary: dict[str, Any], category_summary: dict[str, Any]) -> list[dict[str, Any]]:
    wedding_months = topic_summary.get("wedding", {}).get("byMonth", {})
    cutie_months = topic_summary.get("cutie", {}).get("byMonth", {})
    travel_months = topic_summary.get("travel", {}).get("byMonth", {})
    affection_months = category_summary.get("affection", {}).get("byMonth", {})
    return [
        {
            "label": "Early Traces",
            "range": "2024-03 to 2024-05",
            "evidence": "Sparse start, including the Vipassana silence, before the daily cadence locks in.",
        },
        {
            "label": "Daily Ignition",
            "range": "2024-06 to 2024-08",
            "evidence": "June jumps to near-daily contact, July becomes the highest-volume month, and August sustains it.",
        },
        {
            "label": "The Shared Routine",
            "range": "2024-09 to 2025-01",
            "evidence": "The conversation becomes a steady rhythm of calls, plans, affection, and everyday coordination.",
        },
        {
            "label": "Travel And Terms Of Endearment",
            "range": "2025-02 to 2025-08",
            "evidence": (
                f"Travel peaks around {max(travel_months, key=travel_months.get) if travel_months else 'the middle'} "
                f"while cutie becomes a recurring motif by {max(cutie_months, key=cutie_months.get) if cutie_months else 'later months'}."
            ),
        },
        {
            "label": "Wedding Moves To The Foreground",
            "range": "2025-12 to 2026-01",
            "evidence": (
                f"Wedding language peaks in {max(wedding_months, key=wedding_months.get) if wedding_months else 'this era'}, "
                "after the relationship language has already become stable."
            ),
        },
        {
            "label": "Locked-In Near Daily",
            "range": "2026-02 to 2026-05",
            "evidence": (
                f"Affection remains present through the latest months, with category hits peaking in "
                f"{max(affection_months, key=affection_months.get) if affection_months else 'the recent period'}."
            ),
        },
    ]


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def aggregate_monthly_summaries(summary_dir: Path, chat_id: int) -> dict[str, Any]:
    paths = sorted(summary_dir.glob(f"chat-{chat_id}-????-??-text.json"))
    summaries = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    words: collections.Counter[str] = collections.Counter()
    emojis: collections.Counter[str] = collections.Counter()
    sender_breakdown: collections.Counter[str] = collections.Counter()
    message_count = 0
    active_days = 0
    total_calendar_days = 0
    first_day: dt.date | None = None
    last_day: dt.date | None = None
    months: list[dict[str, Any]] = []

    for summary in summaries:
        metadata = summary["metadata"]
        text = summary.get("text", {})
        label = summary["range"]["label"]
        message_count += metadata["messageCount"]
        active_days += metadata["activeDays"]
        total_calendar_days += metadata["totalCalendarDays"]
        sender_breakdown.update(metadata.get("senderBreakdown", {}))
        date_range = metadata.get("dateRange", {})
        if date_range.get("first") and date_range.get("last"):
            month_first = dt.date.fromisoformat(date_range["first"])
            month_last = dt.date.fromisoformat(date_range["last"])
            first_day = month_first if first_day is None else min(first_day, month_first)
            last_day = month_last if last_day is None else max(last_day, month_last)
        words.update(dict(text.get("topWords", [])))
        emojis.update(dict(text.get("topEmojis", [])))
        months.append(
            {
                "month": label,
                "messages": metadata["messageCount"],
                "activeDays": metadata["activeDays"],
                "activeDayPct": metadata.get(
                    "activeDayPct",
                    round(100 * metadata["activeDays"] / max(1, metadata["totalCalendarDays"]), 1),
                ),
                "senderBreakdown": metadata.get("senderBreakdown", {}),
                "topWords": text.get("topWords", [])[:10],
            }
        )

    if first_day and last_day:
        total_calendar_days = (last_day - first_day).days + 1

    return {
        "schemaVersion": 1,
        "generatedAt": dt.datetime.now().isoformat(timespec="seconds"),
        "chatId": chat_id,
        "sourceFiles": len(paths),
        "totals": {
            "messageCount": message_count,
            "activeDays": active_days,
            "totalCalendarDays": total_calendar_days,
            "quietDays": total_calendar_days - active_days,
            "activeDayPct": round(100 * active_days / max(1, total_calendar_days), 1),
            "senderBreakdown": dict(sender_breakdown),
        },
        "topWords": [[word, count] for word, count in words.most_common(100)],
        "topEmojis": [[emoji, count] for emoji, count in emojis.most_common(75)],
        "monthsByMessageCount": sorted(months, key=lambda month: month["messages"], reverse=True),
        "monthsChronological": months,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze copied iMessage chat data in bounded chunks.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--chat-id", type=int, default=DEFAULT_CHAT_ID)
    parser.add_argument("--month", help="Limit to YYYY-MM.")
    parser.add_argument("--start-day")
    parser.add_argument("--end-day")
    parser.add_argument("--include-text", action="store_true", help="Decode attributedBody for word/emoji aggregates.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--aggregate-monthly", action="store_true", help="Aggregate existing monthly text summaries.")
    parser.add_argument("--topic-snippets", action="store_true", help="Write topic origins, categories, eras, and private snippets.")
    parser.add_argument("--site-summary", action="store_true", help="Write aggregate public-safe site data from iMessage and WhatsApp.")
    parser.add_argument("--whatsapp-db", type=Path, default=DEFAULT_WHATSAPP_DB)
    parser.add_argument("--whatsapp-chat-id", type=int, default=DEFAULT_WHATSAPP_CHAT_ID)
    args = parser.parse_args()

    if args.site_summary:
        imessage_conn = connect(args.db)
        whatsapp_conn = connect(args.whatsapp_db)
        imessage_attachments = count_chat_attachments(imessage_conn, args.chat_id)
        whatsapp_attachments = count_chat_attachments(whatsapp_conn, args.whatsapp_chat_id)
        sources = {
            "iMessage": iter_messages(imessage_conn, args.chat_id, None, None),
            "WhatsApp": iter_messages(whatsapp_conn, args.whatsapp_chat_id, None, None),
        }
        payload = summarize_site_message_sources(sources)
        payload["totals"]["attachments"] = imessage_attachments + whatsapp_attachments
        payload["totals"]["sourceAttachmentBreakdown"] = {
            "iMessage": imessage_attachments,
            "WhatsApp": whatsapp_attachments,
        }
        output_path = args.out / "site-message-summary.json"
        write_json(output_path, payload)
        print(json.dumps({"output": str(output_path), "messages": payload["totals"]["messageCount"]}, indent=2))
        return 0

    if args.aggregate_monthly:
        payload = aggregate_monthly_summaries(args.out, args.chat_id)
        output_path = args.out / f"chat-{args.chat_id}-aggregate.json"
        write_json(output_path, payload)
        print(json.dumps({"output": str(output_path), "sourceFiles": payload["sourceFiles"]}, indent=2))
        return 0

    start_day = args.start_day
    end_day = args.end_day
    label = "all"
    if args.month:
        start_day, end_day = month_bounds(args.month)
        label = args.month
    elif start_day or end_day:
        label = f"{start_day or 'begin'}_{end_day or 'end'}"

    conn = connect(args.db)
    rows = iter_messages(conn, args.chat_id, start_day, end_day)

    if args.topic_snippets:
        payload = summarize_topic_snippets(rows)
        payload["chatId"] = args.chat_id
        payload["range"] = {"label": label, "startDay": start_day, "endDayExclusive": end_day}
        output_path = args.out / f"chat-{args.chat_id}-{label}-topic-snippets.json"
        write_json(output_path, payload)
        print(json.dumps({"output": str(output_path), "messages": len(rows)}, indent=2))
        return 0

    metadata = summarize_metadata(rows)
    payload: dict[str, Any] = {
        "schemaVersion": 1,
        "generatedAt": dt.datetime.now().isoformat(timespec="seconds"),
        "chatId": args.chat_id,
        "range": {"label": label, "startDay": start_day, "endDayExclusive": end_day},
        "metadata": metadata,
    }

    if args.include_text:
        payload["text"] = summarize_text(rows)

    suffix = "text" if args.include_text else "metadata"
    output_path = args.out / f"chat-{args.chat_id}-{label}-{suffix}.json"
    write_json(output_path, payload)
    print(json.dumps({"output": str(output_path), "messages": len(rows), "includeText": args.include_text}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
