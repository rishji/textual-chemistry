import unittest
import datetime as dt
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import imessage_analyzer as analyzer


class CleanupTests(unittest.TestCase):
    def apple_ns(self, timestamp: str) -> int:
        when = dt.datetime.fromisoformat(timestamp)
        return int((when.timestamp() - analyzer.APPLE_EPOCH_OFFSET) * 1_000_000_000)

    def test_tokenize_removes_urls_archive_noise_and_filler(self):
        text = (
            "Cutie https://example.com/path?utm_source=x "
            "kimMessagePartAttributeName rangeVal locationZNS aloved "
            "now also one they some good flight"
        )

        self.assertEqual(analyzer.tokenize(text), ["cutie", "good", "flight"])

    def test_tokenize_normalizes_common_contraction_fragments(self):
        text = "I don know why she didn call but it was okay"

        self.assertEqual(analyzer.tokenize(text), ["know", "why", "call"])

    def test_emoji_tokens_drop_placeholders_and_join_modifiers(self):
        text = "Yay 👏🏽 ️ ❤ ￼ 🎉"

        self.assertEqual(analyzer.emoji_tokens(text), ["👏🏽", "❤", "🎉"])

    def test_aggregate_monthly_summaries_combines_private_outputs(self):
        monthly = [
            {
                "range": {"label": "2024-07"},
                "metadata": {
                    "messageCount": 10,
                    "activeDays": 5,
                    "totalCalendarDays": 5,
                    "senderBreakdown": {"Rishi": 4, "Esha": 6},
                },
                "text": {
                    "topWords": [["cutie", 3], ["flight", 2]],
                    "topEmojis": [["👏🏽", 2]],
                },
            },
            {
                "range": {"label": "2024-08"},
                "metadata": {
                    "messageCount": 20,
                    "activeDays": 10,
                    "totalCalendarDays": 12,
                    "senderBreakdown": {"Rishi": 9, "Esha": 11},
                },
                "text": {
                    "topWords": [["cutie", 4], ["home", 3]],
                    "topEmojis": [["👏🏽", 1], ["❤", 1]],
                },
            },
        ]

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for summary in monthly:
                label = summary["range"]["label"]
                analyzer.write_json(tmp_path / f"chat-34-{label}-text.json", summary)

            aggregate = analyzer.aggregate_monthly_summaries(tmp_path, 34)

        self.assertEqual(aggregate["totals"]["messageCount"], 30)
        self.assertEqual(aggregate["totals"]["activeDays"], 15)
        self.assertEqual(aggregate["totals"]["activeDayPct"], 88.2)
        self.assertEqual(aggregate["totals"]["senderBreakdown"], {"Rishi": 13, "Esha": 17})
        self.assertEqual(aggregate["topWords"][0], ["cutie", 7])
        self.assertEqual(aggregate["topEmojis"][0], ["👏🏽", 3])

    def test_find_topic_hits_matches_variants_and_phrases(self):
        text = "When did you become my girlfriend, cutie pie? QTPI forever."

        hits = analyzer.find_topic_hits(text)

        self.assertIn("girlfriend", hits)
        self.assertIn("cutie_pie", hits)
        self.assertIn("qtpi", hits)

    def test_classify_message_groups_relationship_signals(self):
        text = "baby this ring proposal thing is funny but we need to book the flight"

        categories = analyzer.classify_message(text)

        self.assertEqual(categories, ["affection", "wedding", "travel", "humor", "logistics"])

    def test_find_topic_hits_filters_obvious_non_relationship_uses(self):
        examples = [
            ("I propose we meet at 7 and then call after", "proposal"),
            ("The phone is ringing but I cannot pick up", "ring"),
            ("Their baby is so cute in that photo", "baby"),
            ("Varun's wedding looks fun", "wedding"),
        ]

        for text, topic in examples:
            with self.subTest(topic=topic, text=text):
                self.assertNotIn(topic, analyzer.find_topic_hits(text))

    def test_find_topic_hits_keeps_relationship_uses_after_filtering(self):
        examples = [
            ("Parents meeting will accelerate the timeline to proposal", "proposal"),
            ("Should I bring my ring?", "ring"),
            ("Good night baby", "baby"),
            ("Can I create a wedding planning WhatsApp group with our parents?", "wedding"),
        ]

        for text, topic in examples:
            with self.subTest(topic=topic, text=text):
                self.assertIn(topic, analyzer.find_topic_hits(text))

    def test_classify_message_filters_wedding_and_affection_false_positives(self):
        text = "I propose we call after Varun's wedding because their baby is crying"

        self.assertEqual(analyzer.classify_message(text), ["logistics"])

    def test_count_term_mentions_counts_phrases_without_double_counting_components(self):
        text = "cutie cutie pie ctp, hb, ctp hb cutiepie"

        self.assertEqual(analyzer.count_term_mentions(text, ["cutie"]), 1)
        self.assertEqual(analyzer.count_term_mentions(text, ["cutie pie", "cutiepie"]), 2)
        self.assertEqual(analyzer.count_term_mentions(text, ["ctp"]), 1)
        self.assertEqual(analyzer.count_term_mentions(text, ["hb"]), 1)
        self.assertEqual(analyzer.count_term_mentions(text, ["ctphb", "ctp hb"]), 1)

    def test_summarize_site_message_sources_combines_imessage_and_whatsapp(self):
        sources = {
            "iMessage": [
                {"date": self.apple_ns("2024-06-01T09:00:00"), "is_from_me": 1, "cache_has_attachments": 0},
                {"date": self.apple_ns("2024-06-01T10:00:00"), "is_from_me": 0, "cache_has_attachments": 1},
            ],
            "WhatsApp": [
                {"date": self.apple_ns("2024-06-01T11:00:00"), "is_from_me": 0, "cache_has_attachments": 0},
                {"date": self.apple_ns("2024-07-02T12:00:00"), "is_from_me": 1, "cache_has_attachments": 1},
            ],
        }

        summary = analyzer.summarize_site_message_sources(sources)

        self.assertEqual(summary["totals"]["messageCount"], 4)
        self.assertEqual(summary["totals"]["activeDays"], 2)
        self.assertEqual(summary["totals"]["totalCalendarDays"], 32)
        self.assertEqual(summary["totals"]["quietDays"], 30)
        self.assertEqual(summary["totals"]["senderBreakdown"], {"Rishi": 2, "Esha": 2})
        self.assertEqual(summary["totals"]["sourceBreakdown"], {"iMessage": 2, "WhatsApp": 2})
        self.assertEqual(summary["months"][0]["sourceBreakdown"], {"iMessage": 2, "WhatsApp": 1})
        self.assertEqual(summary["months"][1]["sourceBreakdown"], {"WhatsApp": 1})


if __name__ == "__main__":
    unittest.main()
