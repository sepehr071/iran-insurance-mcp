import json
from pathlib import Path

import httpx
import pytest
from mcp import Client

from iran_insurance_mcp.azki import http as az_http
from iran_insurance_mcp.bimebazar import http as bb_http
from iran_insurance_mcp.server import mcp

FIXTURES = Path(__file__).parent / "fixtures"


def _path(name: str) -> Path:
    """Fixture names are unique across the two provider folders."""
    return next(p for p in FIXTURES.glob(f"*/{name}"))


def fixture(name: str):
    return json.loads(_path(name).read_text(encoding="utf-8"))


def text_fixture(name: str) -> str:
    return _path(name).read_text(encoding="utf-8")


def page(name: str):
    """Route handler serving a saved HTML page."""
    body = text_fixture(name)
    return lambda request: httpx.Response(200, text=body)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def fresh_http_client(monkeypatch):
    """The shared httpx clients are bound to one event loop; each test gets a new loop."""
    for h in (bb_http, az_http):
        monkeypatch.setattr(h, "RETRY_DELAY", 0)
        monkeypatch.setattr(h, "JITTER", (0, 0))
        h.set_transport(None)
    yield
    for h in (bb_http, az_http):
        h.set_transport(None)


@pytest.fixture
def api():
    """Route table for a fake upstream (both providers): api["/path"] = JSON body, text, or a callable(request) -> httpx.Response.

    Keys match the URL path only (host ignored; the two sites use different paths). Unknown paths return 404.
    Every request is appended to api.calls so tests can assert on query params.
    """

    class Routes(dict):
        calls: list[httpx.Request]

    routes = Routes()
    routes.calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        routes.calls.append(request)
        target = routes.get(request.url.path)
        if target is None:
            return httpx.Response(404, json={"error": "no fake route"})
        if callable(target):
            return target(request)
        if isinstance(target, str):
            return httpx.Response(200, text=target)
        return httpx.Response(200, json=target)

    for h in (bb_http, az_http):
        h.set_transport(httpx.MockTransport(handler))
    return routes


@pytest.fixture
async def client():
    async with Client(mcp, raise_exceptions=True) as c:
        call_tool = c.call_tool

        async def parsed(*args, **kwargs):
            result = await call_tool(*args, **kwargs)
            if not result.is_error:
                result.structured_content = json.loads(result.content[0].text)
            return result

        c.call_tool = parsed
        yield c
