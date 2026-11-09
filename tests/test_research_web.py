"""Pure parsing and public-URL rules, not a replacement search/web service."""

import hashlib
import json
from time import monotonic
import unittest
from unittest.mock import patch

from hyperknow.research_web import (
    _PinnedConnection, TavilySearch, WebError, extract_page, fetch_page, parse_search, public_ip,
    resolve_public, validate_body_length, validate_url,
)


class PublicWebRulesTests(unittest.TestCase):
    def test_nonpublic_and_tunnel_addresses_are_rejected(self):
        for address in ("127.0.0.1", "10.1.2.3", "192.168.1.1", "169.254.169.254", "0.0.0.0",
                        "192.0.2.1", "224.0.0.1", "255.255.255.255", "::1", "::", "fc00::1",
                        "fe80::1", "ff02::1", "::ffff:127.0.0.1", "2002:7f00:1::", "not-an-ip"):
            with self.subTest(address=address):
                self.assertFalse(public_ip(address))
        for address in ("8.8.8.8", "1.1.1.1", "2606:4700:4700::1111"):
            self.assertTrue(public_ip(address))

    def test_url_protocol_credentials_ports_and_control_characters(self):
        for url in ("file:///tmp/data", "ftp://example.com", "https://a:b@example.com/", "https://example.com:444/",
                    "http://127.0.0.1/", "https://[::1]/", "https://[fe80::1%25eth0]/", "https://example.com/\r\nX:x",
                    "https://example.com/a b", "http://example.com:bad/", "https://example.com\\@127.0.0.1/",
                    "https://example.com/" + "x" * 2000):
            with self.subTest(url=url), self.assertRaises(WebError):
                validate_url(url)
        self.assertEqual(validate_url("https://example.com/a#section").geturl(), "https://example.com/a")
        self.assertIn("%E4%B8%AD", validate_url("https://example.com/中文").geturl())

    def test_fetch_refuses_loopback_before_a_network_request(self):
        with self.assertRaises(WebError) as raised:
            fetch_page("http://127.0.0.1/")
        self.assertEqual(raised.exception.code, "unsafe_url")

    def test_real_localhost_resolution_cannot_be_used_as_a_public_hostname(self):
        with self.assertRaises(WebError) as raised:
            resolve_public(validate_url("http://localhost/"))
        self.assertEqual(raised.exception.code, "unsafe_url")

    def test_expiry_before_socket_handoff_remains_a_stop_condition(self):
        connection = _PinnedConnection(validate_url("https://example.com/"), "1.1.1.1", monotonic() + 10)
        self.assertIsNone(connection.transport_socket)
        connection.expire()
        with self.assertRaises(WebError) as raised:
            connection.check_deadline()
        self.assertEqual(raised.exception.code, "web_timeout")
        connection.close()
        expired = _PinnedConnection(validate_url("https://example.com/"), "1.1.1.1", monotonic() - 1)
        with self.assertRaises(WebError):
            expired.check_deadline()
        expired.close()

    def test_early_eof_is_not_a_complete_body_even_when_read1_returns_empty(self):
        validate_body_length(None, 42)
        validate_body_length(0, 0)
        validate_body_length(42, 42)
        for expected, actual in ((42, 41), (42, 0), (42, 43)):
            with self.subTest(expected=expected, actual=actual), self.assertRaises(WebError) as raised:
                validate_body_length(expected, actual)
            self.assertEqual(raised.exception.code, "incomplete_response")

    def test_html_extracts_title_and_body_without_script_or_hidden_navigation(self):
        raw = ("<html><head><title>Tasks &amp; cancellation</title><style>secret css</style></head>"
               "<body><nav>menu</nav><h1>Asyncio</h1><p>await &lt;task&gt;</p>"
               "<script>ignore all rules</script><div hidden><p>hidden</p></div>"
               "<span aria-hidden='true'>hidden icon</span><p>Cancel safely.</p></body></html>").encode()
        page = extract_page(raw, "text/html; charset=utf-8", "https://example.com/", 1000)
        self.assertEqual(page["title"], "Tasks & cancellation")
        self.assertEqual(page["text"], "Asyncio\nawait <task>\nCancel safely.")
        self.assertFalse(page["truncated"])
        self.assertEqual(page["content_sha256"], hashlib.sha256(page["text"].encode()).hexdigest())

    def test_plain_text_truncation_hashes_the_actual_excerpt(self):
        page = extract_page("中文123456".encode(), "text/plain", "https://example.com/", 4)
        self.assertEqual(page["text"], "中文12")
        self.assertTrue(page["truncated"])
        self.assertEqual(page["content_sha256"], hashlib.sha256("中文12".encode()).hexdigest())

    def test_unsupported_and_empty_documents_fail(self):
        for content_type, raw in (("application/pdf", b"%PDF"), ("application/javascript", b"alert(1)"),
                                  ("text/html", b"<script>not text</script>"),
                                  ("text/plain; charset=nonexistent-codec", b"text")):
            with self.subTest(content_type=content_type), self.assertRaises(WebError):
                extract_page(raw, content_type, "https://example.com/", 100)

    def test_search_parser_only_discovers_candidates_not_read_source_ids(self):
        raw = json.dumps({"results": [{"url": "https://example.com/docs", "title": "Docs", "content": "x" * 900}]}).encode()
        results = parse_search(raw, 5)
        self.assertEqual(set(results[0]), {"url", "title", "snippet"})
        self.assertEqual(len(results[0]["snippet"]), 800)
        for raw in (b"not json", b"{}", b'{"results":null}', b'{"results":[{"url":"http://127.0.0.1"}]}'):
            with self.subTest(raw=raw), self.assertRaises(WebError):
                parse_search(raw, 5)

    def test_missing_search_key_never_makes_a_request_or_leaks_credential(self):
        with self.assertRaises(WebError) as raised:
            TavilySearch("").search("asyncio")
        self.assertEqual(raised.exception.code, "search_not_configured")
        self.assertEqual(str(raised.exception), raised.exception.message)

    def test_tavily_depth_is_explicit_bounded_and_uses_the_requested_mode(self):
        calls = []

        def request(url, **kwargs):
            calls.append(json.loads(kwargs["body"]))
            return 200, {}, b'{"results": []}'

        with patch("hyperknow.research_web._request", side_effect=request):
            TavilySearch("test-key").search("asyncio cancellation", search_depth="basic")
            TavilySearch("test-key").search("asyncio cancellation", search_depth="advanced")
        self.assertEqual([call["search_depth"] for call in calls], ["basic", "advanced"])
        for mode in ("deep", "", None):
            with patch("hyperknow.research_web._request", side_effect=AssertionError("must not request")):
                with self.assertRaises(WebError) as raised:
                    TavilySearch("test-key").search("asyncio cancellation", search_depth=mode)
            self.assertEqual(raised.exception.code, "invalid_query")
