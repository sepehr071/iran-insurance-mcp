import httpx
import pytest
from conftest import fixture, page

from iran_insurance_mcp.azki import http as az_http
from iran_insurance_mcp.bimebazar import http as bb_http

pytestmark = pytest.mark.anyio

TOOLS = {
    "ins_insurers",
    "ins_vehicles",
    "ins_places",
    "ins_quote_travel",
    "ins_content",
    "ins_quote_third_party",
    "ins_quote_motorcycle",
    "ins_quote_car_body",
    "ins_quote_fire",
    "ins_quote_health",
    "ins_insurer_reviews",
    "ins_claim_centers",
    "ins_glossary",
    "ins_azki_car_value",
    "ins_azki_body_options",
    "ins_azki_products",
    "ins_azki_company",
    "ins_azki_blog",
}


def q(call: httpx.Request) -> dict[str, str]:
    return dict(call.url.params.multi_items())


def by_path(api, path: str) -> httpx.Request:
    return next(c for c in api.calls if c.url.path == path)


async def test_all_tools_are_read_only_and_described(client):
    tools = (await client.list_tools()).tools
    assert {t.name for t in tools} == TOOLS
    for t in tools:
        assert t.annotations.read_only_hint is True
        assert t.description and t.description.splitlines()[0].endswith(".")
    merged = {t.name: t for t in tools if t.name in ("ins_insurers", "ins_vehicles", "ins_places", "ins_content")}
    assert all("provider" in t.input_schema["properties"] for t in merged.values())


def test_one_proxy_variable_feeds_both_clients(monkeypatch):
    monkeypatch.setenv("IRAN_INSURANCE_MCP_PROXY", "http://127.0.0.1:1, http://127.0.0.1:2")
    monkeypatch.setenv("BIMEBAZAR_MCP_PROXY", "http://old:1")
    monkeypatch.setenv("AZKI_MCP_PROXY", "http://old:2")
    assert bb_http._proxies() == az_http._proxies() == ["http://127.0.0.1:1", "http://127.0.0.1:2"]


async def test_insurers_side_by_side(client, api):
    api["/insurance_api/insurance-companies/"] = fixture("companies.json")
    api["/api/product/third/companies"] = fixture("third_companies.json")
    api["/api/rating/rating/api/v1/general/insurance-companies/rate"] = fixture("rating.json")
    r = (await client.call_tool("ins_insurers", {"query": "آسیا"})).structured_content
    (b,) = r["bimebazar"]["insurers"]
    assert b["url_name"] == "asia" and b["market_share"] == 10.4
    (a,) = r["azki"]["companies"]
    assert a["id"] == 3 and a["rating"] == 4.25 and a["reviews"] == 2192
    assert not {"features", "azki_discount_max", "azki_discount_percent"} & a.keys()
    api["/api/product/body/companies"] = fixture("third_companies.json")
    await client.call_tool("ins_insurers", {"provider": "azki", "azki_kind": "body"})
    assert api.calls[-1].url.path.startswith("/api/")


async def test_one_provider_failing_does_not_fail_the_call(client, api):
    api["/insurance_api/insurance-companies/"] = fixture("companies.json")  # Azki routes are missing -> 404
    r = (await client.call_tool("ins_insurers", {})).structured_content
    assert r["bimebazar"]["count"] > 0
    assert "error" in r["azki"] and "404" in r["azki"]["error"] and "insurers" not in r["azki"]
    only = await client.call_tool("ins_insurers", {"provider": "azki"})
    assert only.is_error and "azki" in only.content[0].text


async def test_all_providers_failing_is_an_error(client, api):
    bad = await client.call_tool("ins_insurers", {})
    assert bad.is_error and "bimebazar:" in bad.content[0].text and "azki:" in bad.content[0].text


async def test_vehicles_side_by_side_and_type_mapping(client, api):
    api["/api/web_config/car_info/"] = fixture("car_info.json")
    api["/api/product/vehicle/models/body"] = fixture("models_body.json")
    r = (await client.call_tool("ins_vehicles", {"query": "206"})).structured_content
    assert r["bimebazar"]["brands"][0]["models"] and r["azki"]["brands"][0]["models"]  # a model query works on both
    r = (await client.call_tool("ins_vehicles", {"query": "پژو"})).structured_content
    assert r["bimebazar"]["brands"][0]["value"] == "car_peugeot"
    (b,) = r["azki"]["brands"]
    assert {m["id"] for m in b["models"]} == {182041, 182091} or len(b["models"]) >= 1
    api["/api/product/vehicle/models/motor"] = [
        {"id": 6, "title": "موتور سیکلت", "brands": [{"id": 1, "title": "هوندا", "models": [{"id": 5, "title": "x"}]}]}
    ]
    r = (await client.call_tool("ins_vehicles", {"vehicle_type": "motorcycle"})).structured_content
    assert r["azki"]["brands"] == [{"id": 1, "title": "هوندا", "models": 1}]
    assert r["bimebazar"]["count"] == 0  # no motorcycles in the car_info fixture


async def test_places_side_by_side(client, api):
    api["/insurance_api/damage-centers-cities/"] = fixture("locations.json")
    api["/api/core/api/data/v2/zones/-1"] = fixture("zones.json")
    r = (await client.call_tool("ins_places", {"query": "تهران"})).structured_content
    assert r["bimebazar"]["matches"][0]["province"] == "tehran"
    assert r["azki"]["provinces"][0]["name"] == "تهران"


async def test_content_side_by_side_and_one_side_missing(client, api):
    api["/sanhab/"] = page("page_tp.html")
    api["/api/content/api/sanhab-landing"] = fixture("landing_sanhab.json")
    r = (await client.call_tool("ins_content", {"page": "sanhab", "chars": 100})).structured_content
    assert r["bimebazar"]["faq"] and "<" not in r["bimebazar"]["faq"][0]["a"]
    assert r["azki"]["title"] and r["azki"]["cards"] and r["azki"]["faq"]
    assert all(len(c["text"]) <= 103 for c in r["azki"]["cards"])
    filtered = (await client.call_tool("ins_content", {"page": "sanhab", "query": "افت قیمت"})).structured_content
    assert filtered["bimebazar"]["faq"] and len(filtered["azki"].get("faq", [])) < len(r["azki"]["faq"])
    api["/api/content/api/life-landing"] = fixture("landing_sanhab.json")  # no BimeBazar life route -> 404
    r = (await client.call_tool("ins_content", {"page": "life"})).structured_content
    assert "error" in r["bimebazar"] and r["azki"]["faq"]


def travel_routes(api):
    api["/travel-insurance/"] = page("page_travel.html")
    api["/travel/api/offers/"] = fixture("offers_travel.json")
    api["/api/marco/countries/cache-list"] = fixture("countries.json")
    api["/api/marco/durations/cache-list"] = fixture("travel_durations.json")
    api["/api/marco/passenger-ages/cache-list"] = fixture("travel_ages.json")
    api["/api/marco/prices"] = fixture("travel_done.json")


async def test_travel_quote_resolves_names_for_both_sites(client, api):
    travel_routes(api)
    args = {"destinations": ["آلمان"], "duration_days": 15, "travellers_0_to_12": 1, "limit": 3}
    r = (await client.call_tool("ins_quote_travel", args)).structured_content
    assert list(q(by_path(api, "/travel/api/offers/")).items()) == [
        ("country", "67"),
        ("u12_persons", "1"),
        ("u65_persons", "1"),
        ("duration", "15"),
    ]
    assert q(by_path(api, "/api/marco/prices")) == {"countriesId": "6", "durationId": "2", "passengerAgeIds": "1,2"}
    bb, az = r["bimebazar"], r["azki"]
    assert bb["destinations"] == [{"id": 67, "name": "آلمان"}] and az["destinations"] == [{"id": 6, "name": "آلمان"}]
    assert 0 < len(bb["offers"]) <= 3 and bb["offers"][0]["price_toman"] and bb["offers"][0]["medical_cover"]
    prices = [o["price_after_discount"] for o in az["offers"]]
    assert az["offers"][0]["company"] and prices == sorted(prices) and az["offers"][0]["medical_cover"] == 30000


async def test_travel_quote_english_name_uses_azkis_persian_title(client, api):
    travel_routes(api)
    r = (
        await client.call_tool("ins_quote_travel", {"destinations": ["Germany"], "duration_days": 7})
    ).structured_content
    assert r["bimebazar"]["destinations"] == [{"id": 67, "name": "آلمان"}]
    assert r["azki"]["destinations"] == [{"id": 6, "name": "آلمان"}]


async def test_travel_quote_one_provider_fails_other_answers(client, api):
    travel_routes(api)
    del api["/api/marco/prices"]
    r = (await client.call_tool("ins_quote_travel", {"destinations": ["آلمان"], "duration_days": 7})).structured_content
    assert r["bimebazar"]["offers"] and "error" in r["azki"]
    travel_routes(api)
    r = (
        await client.call_tool(
            "ins_quote_travel", {"destinations": ["آلمان"], "duration_days": 7, "travellers_86_to_100": 1}
        )
    ).structured_content
    assert r["bimebazar"]["offers"] and "85" in r["azki"]["error"]


async def test_travel_quote_input_errors(client, api):
    travel_routes(api)
    none = await client.call_tool(
        "ins_quote_travel", {"destinations": ["آلمان"], "duration_days": 7, "travellers_13_to_65": 0}
    )
    assert none.is_error and "traveller" in none.content[0].text
    unknown = await client.call_tool("ins_quote_travel", {"destinations": ["wakanda"], "duration_days": 7})
    assert unknown.is_error and "wakanda" in unknown.content[0].text
    many = await client.call_tool(
        "ins_quote_travel", {"destinations": ["آ"], "duration_days": 7, "provider": "bimebazar"}
    )
    assert many.is_error and "matches" in many.content[0].text
