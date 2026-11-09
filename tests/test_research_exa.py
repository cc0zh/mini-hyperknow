# Exa retrieval and quotable highlight excerpts. Requests are patched and never leave the process.
import hashlib
import json
from datetime import datetime
import unittest
from unittest.mock import patch

from hyperknow.research_web import ExaContents, ExaSearch, WebError


SECRET = "exa-live-key-do-not-leak"
MARKER = "vendor-body-secret"
SEARCH = "https://api.exa.ai/search"
CONTENTS = "https://api.exa.ai/contents"
PAGE = "https://example.com/docs"


def search_payload():
    return {"autopromptString": MARKER, "results": [
        {"url": "https://example.com/docs#frag", "title": "Docs " + "t" * 320, "score": 0.1,
         "publishedDate": "2024-01-02T03:04:05Z", "highlights": ["alpha  beta", "x" * 900],
         "highlightScores": [0.2, 0.9]},
        {"url": "https://example.org/later", "title": "Later", "score": 0.99, "highlights": ["second"]},
    ]}


def content_payload(highlights, url=PAGE, title="Page"):
    return {"results": [{"url": url, "title": title, "score": 4, "text": "FULL_PAGE_NOT_QUOTE",
                         "highlights": highlights, "highlightScores": [9, 1]}]}


class ExaProviderTests(unittest.TestCase):
    def _request(self, responder):
        return patch("hyperknow.research_web._request", side_effect=responder)

    def test_search_request_preserves_order_and_drops_scores(self):
        calls = []

        def fake(url, *, deadline, max_bytes, method="GET", body=None, headers=None):
            calls.append({"url": url, "method": method, "body": body, "headers": headers,
                          "max_bytes": max_bytes, "deadline": deadline})
            return 200, {}, json.dumps(search_payload()).encode()

        with self._request(fake):
            results = ExaSearch(SECRET, timeout=20).search("asyncio tasks", 2)
            first_only = ExaSearch(SECRET).search("asyncio tasks", 1)
        self.assertEqual([(item["url"], item["method"]) for item in calls], [(SEARCH, "POST"), (SEARCH, "POST")])
        self.assertEqual(calls[0]["headers"], {"Content-Type": "application/json", "x-api-key": SECRET})
        self.assertNotIn(SECRET, calls[0]["url"])
        self.assertIsInstance(calls[0]["body"], bytes)
        self.assertNotIn(SECRET.encode(), calls[0]["body"])
        self.assertEqual(json.loads(calls[0]["body"]), {
            "query": "asyncio tasks", "numResults": 2, "contents": {"highlights": True}})
        self.assertEqual(json.loads(calls[1]["body"])["numResults"], 1)
        self.assertGreater(calls[0]["max_bytes"], 0)
        self.assertEqual([item["url"] for item in results], [PAGE, "https://example.org/later"])
        self.assertEqual(set(results[0]), {"provider", "url", "title", "snippet", "highlights", "published_at"})
        self.assertEqual(results[0]["provider"], "exa")
        self.assertEqual(results[0]["title"], ("Docs " + "t" * 320)[:300])
        self.assertEqual(results[0]["highlights"], ["alpha  beta", "x" * 900])
        self.assertEqual(results[0]["snippet"], ("alpha  beta\n" + "x" * 900)[:800])
        self.assertEqual(len(results[0]["snippet"]), 800)
        self.assertEqual(results[0]["published_at"], "2024-01-02T03:04:05Z")
        self.assertIsNone(results[1]["published_at"])
        self.assertEqual(first_only[0]["title"], results[0]["title"])
        self.assertEqual(len(first_only), 1)
        encoded = json.dumps(results)
        self.assertNotIn("0.99", encoded)
        self.assertNotIn(MARKER, encoded)

    def test_search_rejects_missing_fields_bad_json_and_malicious_urls(self):
        payloads = [
            b"not-json " + MARKER.encode(),
            b"[]",
            b"{}",
            json.dumps({"results": None}).encode(),
            json.dumps({"results": [{"title": "x", "highlights": ["a"], "score": 1}]}).encode(),
            json.dumps({"results": [{"url": PAGE, "title": "x"}]}).encode(),
            json.dumps({"results": [{"url": PAGE, "title": "x", "highlights": "a"}]}).encode(),
            json.dumps({"results": [{"url": PAGE, "title": "x", "highlights": [1],
                                     "publishedDate": MARKER}]}).encode(),
            json.dumps({"results": [{"url": PAGE, "highlights": ["a"], "publishedDate": 1}]}).encode(),
            json.dumps({"results": [
                {"url": PAGE, "title": "ok", "highlights": ["kept"]},
                {"url": "http://127.0.0.1/secret", "title": MARKER, "highlights": ["bad"], "score": 1},
            ]}).encode(),
            json.dumps({"results": [{"url": "https://user:pass@example.com/a", "title": "x",
                                     "highlights": [MARKER]}]}).encode(),
        ]

        def fake(url, *, deadline, max_bytes, method="GET", body=None, headers=None):
            return 200, {}, fake.raw

        for raw in payloads:
            fake.raw = raw
            with self.subTest(raw=raw), self._request(fake), self.assertRaises(WebError) as raised:
                ExaSearch(SECRET).search("asyncio")
            self.assertEqual(raised.exception.code, "search_invalid_response")
            self.assertNotIn(SECRET, str(raised.exception))
            self.assertNotIn(MARKER, str(raised.exception))
            self.assertNotIn("127.0.0.1", str(raised.exception))
            self.assertIsNone(raised.exception.__cause__)
            self.assertIsNone(raised.exception.__context__)

    def test_contents_request_joins_highlights_and_hashes_truncated_excerpt(self):
        calls = []
        state = {"highlights": ["alpha  beta", "gamma"], "url": PAGE}

        def fake(url, *, deadline, max_bytes, method="GET", body=None, headers=None):
            calls.append({"url": url, "method": method, "body": body, "headers": dict(headers)})
            return 200, {}, json.dumps(content_payload(state["highlights"], state["url"])).encode()

        query = 'quote "cancel" \\ tasks'
        with self._request(fake):
            page = ExaContents(SECRET).read(PAGE + "#section", query)
            state["highlights"] = ["中文123456"]
            short = ExaContents(SECRET).read(PAGE, "asyncio", max_chars=4)
            state["highlights"] = ["a" * 6001]
            bounded = ExaContents(SECRET).read(PAGE, "asyncio")
            state["url"] = None
            state["highlights"] = ["quoted passage"]
            echoed = ExaContents(SECRET).read(PAGE, "asyncio")
        self.assertEqual(calls[0]["url"], CONTENTS)
        self.assertEqual(calls[0]["method"], "POST")
        self.assertEqual(calls[0]["headers"], {"Content-Type": "application/json", "x-api-key": SECRET})
        self.assertEqual(json.loads(calls[0]["body"]), {"ids": [PAGE], "highlights": {"query": query}})
        self.assertNotIn(SECRET.encode(), calls[0]["body"])
        self.assertEqual(page["text"], "alpha  beta\ngamma")
        self.assertIn("alpha  beta", page["text"])
        self.assertTrue(page["truncated"])
        self.assertEqual(page["content_sha256"], hashlib.sha256(page["text"].encode()).hexdigest())
        self.assertEqual(set(page), {"url", "title", "text", "fetched_at", "truncated", "content_sha256",
                                     "provider", "content_mode"})
        self.assertEqual(page["provider"], "exa")
        self.assertEqual(page["content_mode"], "highlights")
        self.assertEqual(page["url"], PAGE)
        self.assertNotIn("FULL_PAGE_NOT_QUOTE", page["text"])
        parsed_time = datetime.fromisoformat(page["fetched_at"])
        self.assertIsNotNone(parsed_time.tzinfo)
        self.assertEqual(short["text"], "中文12")
        self.assertTrue(short["truncated"])
        self.assertEqual(short["content_sha256"], hashlib.sha256("中文12".encode()).hexdigest())
        self.assertNotEqual(short["content_sha256"], hashlib.sha256("中文123456".encode()).hexdigest())
        self.assertEqual(len(bounded["text"]), 6000)
        self.assertTrue(bounded["truncated"])
        self.assertEqual(bounded["content_sha256"], hashlib.sha256(("a" * 6000).encode()).hexdigest())
        self.assertEqual(echoed["url"], PAGE)
        self.assertEqual(echoed["text"], "quoted passage")

    def test_contents_rejects_empty_overlong_shape_and_foreign_url(self):
        cases = {
            "empty": (content_payload([" ", ""]), "empty_page"),
            "no results": ({"results": []}, "empty_page"),
            "bad json": (b"{" + MARKER.encode(), "content_invalid_response"),
            "missing highlights": ({"results": [{"url": PAGE, "text": MARKER}]}, "content_invalid_response"),
            "foreign": (content_payload(["nope"], "https://evil.example/phish"), "content_invalid_response"),
        }

        def fake(url, *, deadline, max_bytes, method="GET", body=None, headers=None):
            raw = fake.payload
            return 200, {}, raw if isinstance(raw, bytes) else json.dumps(raw).encode()

        for name, (payload, code) in cases.items():
            fake.payload = payload
            with self.subTest(name=name), self._request(fake), self.assertRaises(WebError) as raised:
                ExaContents(SECRET).read(PAGE, "asyncio")
            self.assertEqual(raised.exception.code, code)
            self.assertNotIn(MARKER, str(raised.exception))
            self.assertNotIn("evil.example", str(raised.exception))
            self.assertIsNone(raised.exception.__context__)

    def test_missing_key_and_bad_target_do_not_request_or_leak(self):
        def explode(*args, **kwargs):
            raise AssertionError("request was sent")

        with self._request(explode):
            for call in (lambda: ExaSearch("").search("asyncio"),
                         lambda: ExaSearch(" \n" + SECRET).search("asyncio"),
                         lambda: ExaContents(None).read(PAGE, "asyncio"),
                         lambda: ExaSearch(SECRET).search("a"),
                         lambda: ExaSearch(SECRET).search("asyncio", 6)):
                with self.subTest(call=call), self.assertRaises(WebError) as raised:
                    call()
                self.assertNotIn(SECRET, str(raised.exception))
                self.assertIsNone(raised.exception.__context__)
            with self.assertRaises(WebError) as raised:
                ExaContents(SECRET).read("http://127.0.0.1/secret", "asyncio")
            self.assertEqual(raised.exception.code, "unsafe_url")
            self.assertNotIn("127.0.0.1", str(raised.exception))
            self.assertNotIn(SECRET, str(raised.exception))

    def test_http_and_transport_errors_hide_vendor_secrets(self):
        def http_error(url, *, deadline, max_bytes, method="GET", body=None, headers=None):
            return 403, {}, json.dumps({"error": MARKER, "apiKey": SECRET}).encode()

        def transport_error(url, *, deadline, max_bytes, method="GET", body=None, headers=None):
            raise WebError("web_request_failed", SECRET + MARKER)

        calls = (lambda: ExaSearch(SECRET).search("asyncio"),
                 lambda: ExaContents(SECRET).read(PAGE, "asyncio"))
        for responder, code in ((http_error, "http"), (transport_error, "request")):
            for call in calls:
                with self.subTest(code=code, call=call), self._request(responder), self.assertRaises(WebError) as raised:
                    call()
                self.assertIn(code, raised.exception.code)
                self.assertNotIn(SECRET, str(raised.exception))
                self.assertNotIn(MARKER, str(raised.exception))
                self.assertNotIn(SECRET, repr(raised.exception))
                self.assertIsNone(raised.exception.__cause__)
                self.assertIsNone(raised.exception.__context__)
