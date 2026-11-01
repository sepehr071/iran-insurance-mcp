"""Shared async HTTP client for the public JSON APIs behind bimebazar.com (insurance quotes, insurers, claim centers).

Every tool goes through `fetch`, which caps concurrency, caches answers briefly and turns HTTP failures
into `ToolError` messages the model can act on.
"""

from __future__ import annotations

import asyncio
import copy
import json as json_lib
import os
import random
import re
import time
from typing import Any

import httpx
from curl_cffi.const import CurlOpt
from httpx_curl_cffi import AsyncCurlTransport
from mcp.server.mcpserver.exceptions import ToolError

SITE = "https://bimebazar.com"
# Doubles as the host allowlist. The web app (Next.js) calls these paths same-origin (checked in Chrome 2026-11-01).
HOSTS = {"bimebazar.com"}

HEADERS = {
    # User-Agent, sec-ch-ua and TLS come from the impersonated Chrome profile (see _get_client).
    "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.8",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "priority": "u=1, i",
}

MAX_CONCURRENCY = 2
JITTER = (0.2, 0.6)  # seconds before each uncached call
MAX_RETRIES = 2
MAX_RETRY_WAIT = 10  # cap for Retry-After and backoff, seconds
CACHE_TTL = 120  # seconds
CACHE_LONG = 3600  # seconds, for lists that change rarely
CACHE_MAX = 128
RETRY_DELAY = 0.5  # seconds, doubled per retry
MAX_BODY = 6_000_000  # bytes; larger responses are refused

_transport: httpx.AsyncBaseTransport | None = None
_client: httpx.AsyncClient | None = None
_limit: asyncio.Semaphore | None = None
_proxy_index = 0
_retired: set[asyncio.Task] = set()
_cache: dict[tuple, tuple[float, Any]] = {}


class _XhrTransport(AsyncCurlTransport):
    """The Chrome profile sends navigation-only headers; a None value makes curl drop them on XHR calls."""

    def _create_request_params(self, req: httpx.Request) -> dict[str, Any]:
        # The parent drops "accept: */*" as an httpx default; curl would then send Chrome's page Accept instead.
        accept = req.headers.get("accept")
        p = super()._create_request_params(req)
        extra = [(b"cache-control", None)]  # Chrome sends max-age=0 only on a reload
        if req.headers.get("sec-fetch-mode") != "navigate":
            extra += [(b"upgrade-insecure-requests", None), (b"sec-fetch-user", None)]
        p["headers"] = [*p["headers"], *extra, *([(b"accept", b"*/*")] if accept == "*/*" else [])]
        return p


class ApiError(ToolError):
    """A failed upstream call. `status` is the HTTP status, or None for network errors."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def set_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    """Swap the transport (tests use httpx.MockTransport). Drops the current client."""
    global _transport, _client, _limit, _proxy_index
    _transport, _client, _limit, _proxy_index = transport, None, None, 0
    _cache.clear()


def _proxies() -> list[str]:
    """IRAN_INSURANCE_MCP_PROXY: one proxy URL, or a comma-separated list used one at a time."""
    return [p.strip() for p in os.environ.get("IRAN_INSURANCE_MCP_PROXY", "").split(",") if p.strip()]


def _next_proxy(client: httpx.AsyncClient) -> None:
    """Sticky pool: move to the next proxy after a block or connect error; the next call rebuilds the client.

    Only the client that failed may rotate. The old client is closed late because other requests may still use it.
    """
    global _client, _limit, _proxy_index
    if len(_proxies()) < 2 or client is not _client:
        return
    _client, _limit, _proxy_index = None, None, _proxy_index + 1
    t = asyncio.create_task(_close_later(client))
    _retired.add(t)
    t.add_done_callback(_retired.discard)


async def _close_later(client: httpx.AsyncClient) -> None:
    await asyncio.sleep(30)  # longer than the 20 s request timeout
    await client.aclose()


def _get_client() -> tuple[httpx.AsyncClient, asyncio.Semaphore]:
    global _client, _limit
    if _client is None:
        # System proxy settings are ignored; the proxy only comes from IRAN_INSURANCE_MCP_PROXY. curl_cffi
        # presents Chrome's TLS/HTTP2 fingerprint and default headers. The proxy goes to the transport.
        proxies = _proxies()
        _client = httpx.AsyncClient(
            transport=_transport
            or _XhrTransport(
                impersonate="chrome",
                default_headers=True,
                curl_options={
                    CurlOpt.NOPROXY: "*"
                },  # httpx-curl-cffi drops its own NOPROXY unless this dict is non-empty
                proxy=proxies[_proxy_index % len(proxies)] if proxies else None,
                max_connections=2 * MAX_CONCURRENCY,
            ),
            headers=HEADERS,
            timeout=httpx.Timeout(25, connect=8),
            limits=httpx.Limits(max_connections=2 * MAX_CONCURRENCY),
            follow_redirects=False,
            trust_env=False,
        )
        _limit = asyncio.Semaphore(MAX_CONCURRENCY)
    assert _limit is not None
    return _client, _limit


async def fetch(
    path: str, params: dict[str, Any] | list[tuple[str, Any]] | None = None, ttl: int = CACHE_TTL, html: bool = False
) -> Any:
    """GET a bimebazar.com API path the way the web app does and return the parsed JSON body.

    `params` is a dict or a list of pairs (a key may repeat). With `html=True` the page at `path` is fetched as a
    navigation and the raw text returned. Retried up to MAX_RETRIES times on timeout, network error, 5xx or 429,
    with jittered exponential backoff or after Retry-After when sent. 403 is never retried.
    """
    query = list(params.items()) if isinstance(params, dict) else list(params or [])
    url = SITE + path
    host = httpx.URL(url).host
    if host not in HOSTS:
        raise ApiError(f"Refusing to call unexpected host {host}.")
    key = (url, tuple(sorted((k, str(v)) for k, v in query)), html)
    if (hit := _cache.get(key)) and time.monotonic() - hit[0] < ttl:
        return copy.deepcopy(hit[1])
    if html:
        headers = {"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
        headers |= {"sec-fetch-dest": "document", "sec-fetch-mode": "navigate", "sec-fetch-site": "none"}
    else:
        # The web app's own fetch calls (checked in Chrome 2026-11-01): Accept */*, a JSON content-type even on GET,
        # same-origin with the compare page as Referer. It also sends an empty `authorization`; not sent here.
        headers = {"Referer": f"{SITE}/", "Accept": "*/*", "Content-Type": "application/json"}
        headers |= {"sec-fetch-site": "same-origin"}
    for attempt in range(MAX_RETRIES + 1):
        last = attempt == MAX_RETRIES
        wait = RETRY_DELAY * 2**attempt * random.uniform(1, 1.5)
        try:
            r, content = await _request(url, query, headers, host)
        except ApiError as e:
            if last or e.status is not None:
                raise
            await asyncio.sleep(min(wait, MAX_RETRY_WAIT))
            continue
        if (r.status_code == 429 or r.status_code >= 500) and not last:
            await asyncio.sleep(min(_retry_after(r) or wait, MAX_RETRY_WAIT))
            continue
        break

    if r.status_code >= 400:
        raise ApiError(_status_message(r, host, content), r.status_code)
    if html:
        body: Any = content.decode("utf-8", "replace")
    else:
        try:
            body = json_lib.loads(content)
        except ValueError as e:
            raise ApiError(
                f"{host} returned a non-JSON response (HTTP {r.status_code}); it may be showing a browser check. "
                "Wait a minute and retry.",
                r.status_code,
            ) from e
    if len(_cache) >= CACHE_MAX:
        _cache.pop(next(iter(_cache)))
    _cache[key] = (time.monotonic(), copy.deepcopy(body))
    return body


async def _send(client, limit, url, query, headers, host) -> tuple[httpx.Response, bytes]:
    try:
        async with limit:
            await asyncio.sleep(random.uniform(*JITTER))
            async with client.stream("GET", url, params=query, headers=headers) as r:
                return r, await _read_capped(r, host)
    except httpx.TimeoutException as e:
        raise ApiError(f"{host} did not answer in time. Try again in a moment.") from e
    except httpx.RequestError as e:
        if isinstance(e, httpx.ConnectError | httpx.ProxyError):
            _next_proxy(client)
        raise ApiError(
            f"Could not reach {host} ({type(e).__name__}). Check the internet connection "
            "(or the IRAN_INSURANCE_MCP_PROXY setting if you use one)."
        ) from e


async def _request(url, query, headers, host) -> tuple[httpx.Response, bytes]:
    client, limit = _get_client()
    r, content = await _send(client, limit, url, query, headers, host)
    if r.status_code == 307 and not content and _same_url(r, url):
        # ArvanCloud's cookie check: the first request of a session is redirected to the same URL with Set-Cookie
        # (__arcscoc, 120 s); the client's cookie jar replays it on the second request.
        r, content = await _send(client, limit, url, query, headers, host)
    if r.status_code in (403, 429):
        _next_proxy(client)  # blocked: try the next proxy on the following call
    return r, content


def _same_url(r: httpx.Response, url: str) -> bool:
    loc = r.headers.get("location", "")
    return bool(loc) and httpx.URL(url).path == httpx.URL(loc).path


async def _read_capped(r: httpx.Response, host: str) -> bytes:
    """Read the body, refusing anything over MAX_BODY so one huge answer cannot flood memory or context."""
    buf = bytearray()
    async for chunk in r.aiter_bytes():
        buf += chunk
        if len(buf) > MAX_BODY:
            raise ApiError(f"{host} sent a response over {MAX_BODY // 1_000_000} MB; refused.", r.status_code)
    return bytes(buf)


def _retry_after(r: httpx.Response) -> float | None:
    """Seconds from a numeric Retry-After on a 429/503, else None (HTTP-date form is ignored)."""
    v = r.headers.get("retry-after", "")
    return float(v) if r.status_code in (429, 503) and v.replace(".", "", 1).isdigit() else None


def _status_message(r: httpx.Response, host: str, content: bytes) -> str:
    code = r.status_code
    if code == 400:
        try:
            errors = json_lib.loads(content).get("errors")
        except (ValueError, AttributeError):
            errors = None
        return (
            f"{host} rejected the request (HTTP 400): {errors}"
            if errors
            else f"{host} rejected the request (HTTP 400)."
        )
    if code == 401:
        return f"{host} wants a signed-in user for that call (HTTP 401); this server only reads public data."
    if code == 403:
        return f"{host} blocked the request (HTTP 403). Try another network or set IRAN_INSURANCE_MCP_PROXY."
    if code == 404:
        return f"{host} found nothing at that address (HTTP 404). Check the page slug or insurer name."
    if code == 429:
        return f"{host} is rate limiting requests (HTTP 429). Wait a minute before retrying."
    if code >= 500:
        return f"{host} had a server error (HTTP {code}). Try again later."
    return f"{host} rejected the request (HTTP {code})."


_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)


async def page_props(slug: str) -> dict[str, Any]:
    """pageProps of a public landing page (the JSON Next.js embeds for rendering): FAQ text, wizard option lists."""
    text = await fetch(f"/{slug.strip('/')}/", html=True, ttl=CACHE_LONG)
    m = _NEXT_DATA.search(text)
    if not m:
        raise ApiError(f"{SITE} returned no page data for '{slug}' (not a landing page, or a browser check).")
    return json_lib.loads(m.group(1)).get("props", {}).get("pageProps", {})
