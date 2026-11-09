"""Real Tavily/Exa retrieval and bounded public-web text extraction, without a browser."""

from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import http.client
import ipaddress
import json
import re
import socket
import ssl
from threading import Event, Timer
from time import monotonic
from urllib.parse import quote, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser


USER_AGENT = "HyperknowResearch/1.0"


class WebError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def public_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    if (not address.is_global or address.is_multicast or address.is_reserved
            or address.is_unspecified or address.is_loopback or address.is_link_local):
        return False
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            return public_ip(str(address.ipv4_mapped))
        if address.sixtofour is not None or address.teredo is not None or address.is_site_local:
            return False
    return True


def validate_url(url: str):
    if (not isinstance(url, str) or len(url) > 2000 or "\\" in url
            or any(ord(char) <= 32 or ord(char) == 127 for char in url)):
        raise WebError("invalid_url", "网页URL无效或超出长度限制")
    try:
        parsed = urlsplit(url)
        port = parsed.port
        host = parsed.hostname
        if (parsed.scheme not in {"http", "https"} or not host or "%" in host
                or parsed.username is not None or parsed.password is not None
                or port not in {None, 80 if parsed.scheme == "http" else 443}):
            raise ValueError("unsupported URL")
        host = host.encode("idna").decode("ascii")
        # Direct IP literals can be rejected before DNS or any socket operation.
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None and not public_ip(str(address)):
            raise WebError("unsafe_url", "拒绝访问非公网地址")
        netloc = f"[{host}]" if ":" in host else host
        if port is not None:
            netloc += f":{port}"
        return urlsplit(urlunsplit((parsed.scheme, netloc,
                                    quote(parsed.path or "/", safe="/%:@!$&'()*+,;=-._~"),
                                    quote(parsed.query, safe="%/?@!$&'()*+,;=:-._~"), "")))
    except (ValueError, UnicodeError) as exc:
        raise WebError("invalid_url", "仅支持无凭据的标准端口HTTP或HTTPS公开网页") from exc


def resolve_public(parsed) -> str:
    port = 443 if parsed.scheme == "https" else 80
    try:
        answers = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise WebError("dns_failed", "网页域名解析失败") from exc
    addresses = list(dict.fromkeys(answer[4][0] for answer in answers))
    if not addresses or any(not public_ip(address) for address in addresses):
        raise WebError("unsafe_url", "拒绝访问解析到非公网地址的网页")
    return addresses[0]


class _PinnedConnection(http.client.HTTPConnection):
    def __init__(self, parsed, address: str, deadline: float):
        super().__init__(parsed.hostname, 443 if parsed.scheme == "https" else 80,
                         timeout=max(0.001, deadline - monotonic()))
        self.address, self.secure = address, parsed.scheme == "https"
        self.deadline, self.expired = deadline, Event()
        self.transport_socket = None

    def check_deadline(self):
        remaining = self.deadline - monotonic()
        if self.expired.is_set() or remaining <= 0:
            raise WebError("web_timeout", "网页请求超过时间预算")

    def connect(self):
        # Numeric, prevalidated IP only: never resolve the untrusted hostname again.
        self.check_deadline()
        self.sock = socket.create_connection((self.address, self.port), timeout=self.timeout)
        self.transport_socket = self.sock
        self.check_deadline()
        if self.secure:
            try:
                self.sock = ssl.create_default_context().wrap_socket(
                    self.sock, server_hostname=self.host, do_handshake_on_connect=False)
                self.transport_socket = self.sock
                self.check_deadline()
                self.sock.settimeout(max(0.001, self.deadline - monotonic()))
                self.sock.do_handshake()
            except BaseException:
                self.sock.close()
                raise
        # A timer firing during socket handoff must not be lost.
        self.check_deadline()

    def expire(self):
        # HTTPResponse may retain a makefile after HTTPConnection clears sock.
        # shutdown also interrupts slow-trickle header/body reads on that handle.
        self.expired.set()
        if self.transport_socket is not None:
            try:
                self.transport_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


def validate_body_length(expected: int | None, actual: int):
    if expected is not None and expected != actual:
        raise WebError("incomplete_response", "网页响应提前断开，未作为已读资料保存")


def _request(url: str, *, deadline: float, max_bytes: int, method: str = "GET",
             body: bytes | None = None, headers: dict | None = None):
    parsed = validate_url(url)
    address = resolve_public(parsed)
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise WebError("web_timeout", "网页请求超过时间预算")
    connection = _PinnedConnection(parsed, address, deadline)
    timer = Timer(remaining, connection.expire)
    timer.daemon = True
    timer.start()
    response = None
    try:
        target = parsed.path + ("?" + parsed.query if parsed.query else "")
        connection.request(method, target, body=body, headers={
            "User-Agent": USER_AGENT, "Accept-Encoding": "identity", **(headers or {})})
        connection.check_deadline()
        response = connection.getresponse()
        connection.check_deadline()
        expected_length = response.length
        metadata = {key.lower(): value for key, value in response.getheaders()}
        if metadata.get("content-encoding", "identity").lower() not in {"", "identity"}:
            raise WebError("unsupported_encoding", "服务器未提供未压缩正文，本次不解压或绕过限制")
        raw = bytearray()
        while True:
            connection.check_deadline()
            # read1 prevents an unbounded slow trickle from hiding in one large read.
            block = response.read1(min(16384, max_bytes + 1 - len(raw)))
            if not block:
                break
            raw.extend(block)
            if len(raw) > max_bytes:
                raise WebError("response_too_large", "网页响应超过字节预算，未作为已读资料保存")
        connection.check_deadline()
        validate_body_length(expected_length, len(raw))
        return response.status, metadata, bytes(raw)
    except WebError:
        raise
    except (OSError, http.client.HTTPException, ValueError) as exc:
        if monotonic() >= deadline:
            raise WebError("web_timeout", "网页请求超过时间预算") from exc
        raise WebError("web_request_failed", "公开网页请求失败；未重试或绕过访问限制") from exc
    finally:
        timer.cancel()
        if response is not None:
            response.close()
        connection.close()


def _robots_allowed(url: str, deadline: float):
    parsed = validate_url(url)
    robots_url = urlunsplit((parsed.scheme, parsed.netloc, "/robots.txt", "", ""))
    status, headers, raw = _request(robots_url, deadline=deadline, max_bytes=128000)
    if status in {404, 410}:
        return
    if status != 200:
        # Do not silently follow robots redirects or assume an unavailable policy allows access.
        raise WebError("robots_unavailable", "无法确认站点抓取规则，未读取目标网页")
    if "text" not in headers.get("content-type", "").lower():
        raise WebError("robots_unavailable", "站点抓取规则不是可识别文本")
    policy = RobotFileParser()
    policy.parse(raw.decode("utf-8", errors="replace").splitlines())
    if not policy.can_fetch(USER_AGENT, url):
        raise WebError("robots_denied", "站点抓取规则不允许读取该网页")


class PageParser(HTMLParser):
    IGNORED = {"script", "style", "nav", "footer", "header", "noscript", "svg", "template", "form"}
    BLOCKS = {"p", "div", "li", "pre", "article", "section", "br", "h1", "h2", "h3", "h4", "tr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title: list[str] = []
        self.hidden: list[str] = []
        self.in_title = False

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        hidden = (tag in self.IGNORED or "hidden" in attributes
                  or attributes.get("aria-hidden") == "true"
                  or re.search(r"(?:display\s*:\s*none|visibility\s*:\s*hidden)",
                               attributes.get("style") or "", re.I))
        if self.hidden or hidden:
            if tag not in {"br", "img", "input", "meta", "link", "hr", "source", "wbr"}:
                self.hidden.append(tag)
            return
        if tag == "title":
            self.in_title = True
        elif tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if self.hidden:
            if tag in self.hidden:
                # Drop the matching hidden frame and any unclosed inner elements.
                index = len(self.hidden) - 1 - self.hidden[::-1].index(tag)
                del self.hidden[index:]
            return
        if tag == "title":
            self.in_title = False
        elif tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, data):
        if self.hidden:
            return
        (self.title if self.in_title else self.parts).append(data)


def extract_page(raw: bytes, content_type: str, url: str, max_chars: int) -> dict:
    mime = content_type.split(";", 1)[0].strip().lower()
    if mime not in {"text/html", "application/xhtml+xml", "text/plain", "text/markdown"}:
        raise WebError("unsupported_content", "只支持HTML或纯文本，不解析PDF、脚本或其他二进制资料")
    charset = re.search(r"charset\s*=\s*[\"']?([\w-]+)", content_type, re.I)
    try:
        decoded = raw.decode(charset.group(1) if charset else "utf-8", errors="replace")
    except LookupError as exc:
        raise WebError("unsupported_encoding", "网页字符编码不可识别") from exc
    title = ""
    if mime in {"text/html", "application/xhtml+xml"}:
        parser = PageParser()
        parser.feed(decoded)
        parser.close()
        title = " ".join("".join(parser.title).split())[:300]
        decoded = "".join(parser.parts)
    text = "\n".join(line for line in (" ".join(line.split()) for line in decoded.splitlines()) if line)
    if not text.strip():
        raise WebError("empty_page", "网页没有可读取正文，可能需要脚本或登录；未尝试绕过")
    truncated = len(text) > max_chars
    text = text[:max_chars]
    return {"url": url, "title": title or urlsplit(url).hostname or "网页", "text": text,
            "fetched_at": datetime.now(timezone.utc).isoformat(), "truncated": truncated,
            "content_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}


def fetch_page(url: str, *, timeout: float = 15, max_bytes: int = 1000000,
               max_chars: int = 10000) -> dict:
    if timeout <= 0 or max_bytes < 1 or max_chars < 1:
        raise ValueError("page budgets must be positive")
    deadline = monotonic() + timeout
    current = validate_url(url).geturl()
    for _ in range(4):
        _robots_allowed(current, deadline)
        status, headers, raw = _request(current, deadline=deadline, max_bytes=max_bytes)
        if status in {301, 302, 303, 307, 308}:
            location = headers.get("location")
            if not location:
                raise WebError("invalid_redirect", "网页重定向没有有效目标")
            current = validate_url(urljoin(current, location)).geturl()
            continue
        if status != 200:
            raise WebError("web_http_error", "网页未返回成功正文；未登录、重试或绕过访问限制")
        return extract_page(raw, headers.get("content-type", ""), current, max_chars)
    raise WebError("too_many_redirects", "网页重定向超过上限")


def parse_search(raw: bytes, max_results: int) -> list[dict]:
    try:
        payload = json.loads(raw)
        results = payload["results"]
        if not isinstance(results, list):
            raise ValueError("invalid results")
        parsed = []
        for item in results[:max_results]:
            if not isinstance(item, dict):
                raise ValueError("invalid search item")
            url = validate_url(item["url"]).geturl()
            if not isinstance(item.get("title", ""), str) or not isinstance(item.get("content", ""), str):
                raise ValueError("invalid search text")
            parsed.append({"url": url, "title": item.get("title", "")[:300],
                           "snippet": item.get("content", "")[:800]})
        return parsed
    except (ValueError, TypeError, KeyError, WebError) as exc:
        raise WebError("search_invalid_response", "搜索服务返回的结果结构不符合要求") from exc


class TavilySearch:
    def __init__(self, api_key: str, timeout: float = 20):
        self.api_key, self.timeout = api_key, timeout

    def search(self, query: str, max_results: int = 5, search_depth: str = "basic") -> list[dict]:
        if not self.api_key:
            raise WebError("search_not_configured", "未配置TAVILY_API_KEY")
        if (not isinstance(query, str) or not 2 <= len(query.strip()) <= 400
                or not 1 <= max_results <= 5 or search_depth not in {"basic", "advanced"}):
            raise WebError("invalid_query", "搜索词或结果数量超出预算")
        body = json.dumps({"query": query, "search_depth": search_depth, "max_results": max_results,
                           "include_answer": False, "include_raw_content": False}).encode("utf-8")
        try:
            status, _, raw = _request("https://api.tavily.com/search", deadline=monotonic() + self.timeout,
                                      max_bytes=256000, method="POST", body=body,
                                      headers={"Authorization": "Bearer " + self.api_key,
                                               "Content-Type": "application/json"})
        except WebError as exc:
            raise WebError("search_request_failed", "搜索服务请求失败，未自动重试；请检查网络和配置") from exc
        if status != 200:
            raise WebError("search_http_error", "搜索服务拒绝请求，请检查凭据、限额或服务状态")
        return parse_search(raw, max_results)


def _require_exa_key(api_key: str):
    if (not isinstance(api_key, str) or not api_key.strip()
            or any(ord(char) <= 32 or ord(char) == 127 for char in api_key)):
        raise WebError("search_not_configured", "未配置EXA_API_KEY")


def _exa_post(endpoint: str, api_key: str, timeout: float, payload: dict,
              failure: tuple[str, str], http_error: tuple[str, str]) -> bytes:
    # The key stays in one header. Vendor bodies and transport errors are not chained.
    body = json.dumps(payload).encode("utf-8")
    try:
        status, _, raw = _request(endpoint, deadline=monotonic() + timeout, max_bytes=256000,
                                  method="POST", body=body,
                                  headers={"Content-Type": "application/json", "x-api-key": api_key})
    except WebError:
        status, raw = None, b""
    if status is None:
        raise WebError(*failure)
    if status != 200:
        raise WebError(*http_error)
    return raw


def _vendor_object(raw: bytes, code: str, message: str) -> dict:
    payload = None
    if isinstance(raw, bytes):
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = None
    if not isinstance(payload, dict):
        raise WebError(code, message)
    return payload


def _published_at(item: dict):
    if "publishedDate" not in item or item["publishedDate"] is None:
        return None
    if not isinstance(item["publishedDate"], str):
        raise ValueError("invalid published date")
    return item["publishedDate"]


def _parse_exa_search(raw: bytes, max_results: int) -> list[dict]:
    payload = _vendor_object(raw, "search_invalid_response", "搜索服务返回的结果结构不符合要求")
    parsed = None
    try:
        results = payload["results"]
        if not isinstance(results, list):
            raise ValueError("invalid results")
        parsed = []
        for item in results[:max_results]:
            if not isinstance(item, dict) or not isinstance(item.get("highlights"), list):
                raise ValueError("invalid search item")
            if any(not isinstance(part, str) for part in item["highlights"]):
                raise ValueError("invalid highlights")
            title = item.get("title") or ""
            if not isinstance(title, str):
                raise ValueError("invalid title")
            highlights = list(item["highlights"])
            parsed.append({"provider": "exa", "url": validate_url(item["url"]).geturl(),
                           "title": title[:300], "snippet": "\n".join(highlights)[:800],
                           "highlights": highlights, "published_at": _published_at(item)})
    except (KeyError, TypeError, ValueError, WebError):
        parsed = None
    if parsed is None:
        raise WebError("search_invalid_response", "搜索服务返回的结果结构不符合要求")
    return parsed


def _content_excerpt(payload: dict, url: str):
    results = payload["results"]
    if not isinstance(results, list) or (results and not isinstance(results[0], dict)):
        raise ValueError("invalid results")
    if not results:
        return None
    item = results[0]
    found = url if item.get("url") is None else validate_url(item["url"]).geturl()
    if found != url:
        raise ValueError("url mismatch")
    highlights = item["highlights"]
    if not isinstance(highlights, list) or any(not isinstance(part, str) for part in highlights):
        raise ValueError("invalid highlights")
    title = item.get("title") or ""
    if not isinstance(title, str):
        raise ValueError("invalid title")
    return (found, title[:300] or urlsplit(found).hostname or "网页", "\n".join(highlights))


def _parse_exa_contents(raw: bytes, url: str, max_chars: int) -> dict:
    payload = _vendor_object(raw, "content_invalid_response", "内容服务返回的结果结构不符合要求")
    try:
        excerpt = _content_excerpt(payload, url)
    except (KeyError, TypeError, ValueError, WebError):
        excerpt = False
    if excerpt is False:
        raise WebError("content_invalid_response", "内容服务返回的结果结构不符合要求")
    if excerpt is None or not excerpt[2].strip():
        raise WebError("empty_page", "网页没有可读取正文，可能需要脚本或登录；未尝试绕过")
    found, title, text = excerpt
    truncated = True
    text = text[:max_chars]
    return {"url": found, "title": title, "text": text,
            "fetched_at": datetime.now(timezone.utc).isoformat(), "truncated": truncated,
            "content_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "provider": "exa", "content_mode": "highlights"}


class ExaSearch:
    def __init__(self, api_key: str, timeout: float = 20):
        self.api_key, self.timeout = api_key, timeout

    def search(self, query: str, max_results: int = 5) -> list[dict]:
        _require_exa_key(self.api_key)
        if not isinstance(query, str) or not 2 <= len(query.strip()) <= 400 or not 1 <= max_results <= 5:
            raise WebError("invalid_query", "搜索词或结果数量超出预算")
        raw = _exa_post("https://api.exa.ai/search", self.api_key, self.timeout,
                        {"query": query, "numResults": max_results, "contents": {"highlights": True}},
                        ("search_request_failed", "搜索服务请求失败，未自动重试；请检查网络和配置"),
                        ("search_http_error", "搜索服务拒绝请求，请检查凭据、限额或服务状态"))
        return _parse_exa_search(raw, max_results)


class ExaContents:
    def __init__(self, api_key: str, timeout: float = 20):
        self.api_key, self.timeout = api_key, timeout

    def read(self, url: str, query: str, max_chars: int = 6000) -> dict:
        _require_exa_key(self.api_key)
        if not isinstance(query, str) or not 2 <= len(query.strip()) <= 400:
            raise WebError("invalid_query", "搜索词超出预算")
        if max_chars < 1:
            raise ValueError("page budgets must be positive")
        current = validate_url(url).geturl()
        raw = _exa_post("https://api.exa.ai/contents", self.api_key, self.timeout,
                        {"ids": [current], "highlights": {"query": query}},
                        ("content_request_failed", "内容服务请求失败，未自动重试；请检查网络和配置"),
                        ("content_http_error", "内容服务拒绝请求，请检查凭据、限额或服务状态"))
        return _parse_exa_contents(raw, current, max_chars)
