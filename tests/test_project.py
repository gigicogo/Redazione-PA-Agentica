import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from common import pack_meta, unpack_meta, config
from research import parse_feed, make_issue_text, build, select_candidate, propose
from approve import handler, approved_revision


class ProjectTests(unittest.TestCase):
    def test_demo_feed(self):
        items = parse_feed((ROOT / "examples/rss-demo.xml").read_bytes(), 5)
        self.assertEqual(len(items), 3)
        self.assertIn("Sportello digitale", items[0]["title"])

    def test_metadata_reversible(self):
        meta = {"source_url": "https://example.org/a?b=1", "draft": "Messaggio pubblico – prova"}
        self.assertEqual(unpack_meta("test " + pack_meta(meta)), meta)
        self.assertIsNone(unpack_meta("Qualsiasi altra Issue"))

    def test_demo_offline(self):
        with patch.dict(os.environ, {"PREVIEW_ONLY": "1", "MODE": "demo"}):
            meta = build("demo")
        self.assertEqual(meta["mode"], "demo")
        self.assertIn("non è stata utilizzata", meta["limitations"])
        self.assertIn("pa-", "pa-" + meta["draft"])

    def test_model_selects_index(self):
        items = [{"title": "A", "summary": "Sommario A", "date": "", "url": "https://example.org/a"},
                 {"title": "B", "summary": "Sommario B", "date": "", "url": "https://example.org/b"}]
        with patch("research.groq_json", return_value={"decision": "inspect", "index": 1, "reason": "B è pertinente"}):
            selection = select_candidate(items, set(), config())
        self.assertEqual(selection["index"], 1)
        with patch("research.groq_json", return_value={"decision": "inspect", "index": 99}):
            with self.assertRaises(ValueError):
                select_candidate(items, set(), config())

    def test_ai_cannot_forge_a_link(self):
        item = {"title": "Titolo", "summary": "Fatto", "url": "https://example.org/test"}
        with patch("research.groq_json", return_value={"decision": "draft", "post": "Leggi qui https://phishing.invalid per scaricare il documento!"}):
            result = propose(item, "fatto", "originale", config())
        self.assertEqual(result["decision"], "skip")

    def test_revision_last_one_wins(self):
        comments = [{"id": 2, "user": {"login": "gigicogo"}, "body": "/rivedi\nPrima revisione"},
                    {"id": 8, "user": {"login": "gigicogo"}, "body": "/rivedi\nNuova revisione"},
                    {"id": 11, "user": {"login": "spammer"}, "body": "/rivedi\nTentativo di cambio"}]
        self.assertEqual(approved_revision(comments, "gigicogo"), "Nuova revisione")

    def test_untrusted_commenter_does_nothing(self):
        with patch.dict(os.environ, {"GITHUB_REPOSITORY": "gigicogo/Redazione-PA-Agentica"}):
            handler({"sender": {"login": "spammer"}, "comment": {"user": {"login": "spammer"}, "body": "/go"}, "issue": {"number": 3}})

    def test_demo_go_is_blocked_and_cannot_call_bluesky(self):
        fake = type("FakeGH", (), {})()
        fake.request = lambda method, path, **kw: {"number": 3, "body": pack_meta({"version": 1, "mode": "demo", "draft": "contenuto", "source_url": "https://example.org/test"}), "state": "open"}
        fake.labels = lambda n: {"pa-bozza"}
        logs = []
        fake.comment = lambda n, msg: logs.append(msg)
        with patch.dict(os.environ, {"GITHUB_REPOSITORY": "gigicogo/Redazione-PA-Agentica"}), \
             patch("approve.GitHub", return_value=fake), patch("approve.atproto_post") as publisher:
            handler({"sender": {"login": "gigicogo"}, "comment": {"user": {"login": "gigicogo"}, "body": "/go"}, "issue": {"number": 3}})
        self.assertIn("DEMO", logs[-1])
        publisher.assert_not_called()

    def test_scarta_closes_without_publishing(self):
        fake = type("FakeGH", (), {})()
        fake.request = lambda method, path, **kw: {"number": 3, "body": pack_meta({"version": 1, "mode": "live", "draft": "contenuto", "source_url": "https://example.org/test"}), "state": "open"}
        fake.labels = lambda n: {"pa-bozza"}
        calls = []
        fake.ensure_label = lambda *args: calls.append("ensure_label")
        fake.add_label = lambda *args: calls.append("add_label")
        fake.comment = lambda *args: calls.append("comment")
        fake.close = lambda *args: calls.append("close")
        with patch.dict(os.environ, {"GITHUB_REPOSITORY": "gigicogo/Redazione-PA-Agentica"}), \
             patch("approve.GitHub", return_value=fake), patch("approve.atproto_post") as publisher:
            handler({"sender": {"login": "gigicogo"}, "comment": {"user": {"login": "gigicogo"}, "body": "/scarta"}, "issue": {"number": 3}})
        self.assertIn("close", calls)
        publisher.assert_not_called()

    def test_review_updates_visible_draft_and_does_not_publish(self):
        meta = {"version": 1, "mode": "live", "draft": "Prima versione del post da aggiornare", "source_url": "https://example.org/test",
                "title": "Titolo", "feed_url": "https://example.org/rss", "created_at": "2026-11-07T09:00:00Z",
                "reason": "Decisione AI", "checks": "Controllare", "limitations": "", "trace": []}
        fake = type("FakeGH", (), {})()
        patches = []
        def request(method, path, **kwargs):
            if method == "GET": return {"number": 3, "body": pack_meta(meta), "state": "open"}
            patches.append(kwargs["json"]["body"])
            return {}
        fake.request = request
        fake.labels = lambda n: {"pa-bozza"}
        fake.ensure_label = lambda *args: None
        fake.add_label = lambda *args: None
        fake.comment = lambda *args: None
        with patch.dict(os.environ, {"GITHUB_REPOSITORY": "gigicogo/Redazione-PA-Agentica"}), \
             patch("approve.GitHub", return_value=fake), patch("approve.atproto_post") as publisher:
            handler({"sender": {"login": "gigicogo"}, "comment": {"user": {"login": "gigicogo"},
               "body": "/rivedi\nNuova versione verificata dal funzionario pubblico"}, "issue": {"number": 3}})
        self.assertIn("Nuova versione verificata", unpack_meta(patches[-1])["draft"])
        self.assertEqual(unpack_meta(patches[-1])["revised_by"], "gigicogo")
        publisher.assert_not_called()

    def test_live_go_blocked_by_default_config(self):
        fake = type("FakeGH", (), {})()
        fake.request = lambda method, path, **kw: {"number": 3, "body": pack_meta({"version": 1, "mode": "live", "draft": "Titolo della proposta verificabile", "source_url": "https://example.org/test"}), "state": "open"}
        fake.labels = lambda n: {"pa-bozza"}
        logs = []
        fake.comment = lambda n, msg: logs.append(msg)
        with patch.dict(os.environ, {"GITHUB_REPOSITORY": "gigicogo/Redazione-PA-Agentica"}), \
             patch("approve.GitHub", return_value=fake), patch("approve.atproto_post") as publisher:
            handler({"sender": {"login": "gigicogo"}, "comment": {"user": {"login": "gigicogo"}, "body": "/go"}, "issue": {"number": 3}})
        self.assertIn("disabilitata", logs[-1])
        publisher.assert_not_called()

if __name__ == "__main__":
    unittest.main()
