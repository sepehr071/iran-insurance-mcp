import httpx
import pytest
from conftest import fixture, text_fixture

from iran_insurance_mcp.azki import http

pytestmark = pytest.mark.anyio


def q(call: httpx.Request) -> dict[str, str]:
    return dict(call.url.params.multi_items())


async def test_request_headers_match_the_sites_frontend(api):
    api["/api/product/third/durations"] = []
    await http.fetch("/api/product/third/durations")
    h = api.calls[-1].headers
    assert h["accept"] == "application/json, text/plain, */*" and h["referer"] == "https://www.azki.com/"
    assert h["accept-language"] == "fa" and "origin" not in h
    assert (h["sec-fetch-site"], h["sec-fetch-mode"], h["sec-fetch-dest"]) == ("same-origin", "cors", "empty")
    assert h["priority"] == "u=1, i" and h["device"] == "web" and h["deviceid"] == "6"
    assert len(h["user-token"]) == 64 and h["user-token"].isalnum()


async def test_other_hosts_are_refused(api, monkeypatch):
    monkeypatch.setattr(http, "SITE", "https://evil.example")
    with pytest.raises(http.ApiError, match="unexpected host"):
        await http.fetch("/x")
    assert not api.calls


async def test_login_wall_gets_a_plain_message(api):
    api["/api/product/third/durations"] = lambda r: httpx.Response(401, json={})
    with pytest.raises(http.ApiError, match="signed-in"):
        await http.fetch("/api/product/third/durations")


async def test_products_lists_active_and_filters(client, api):
    api["/api/nano/api/products"] = fixture("products.json")
    r = (await client.call_tool("ins_azki_products", {"query": "عمر"})).structured_content
    assert [p["slug"] for p in r["products"]] == ["life-insurance-package"]
    assert q(api.calls[-1]) == {"per_page": "200"}


async def test_car_value_maps_the_estimate_and_explains_a_miss(client, api):
    api["/api/product/vehicle/price-estimate"] = fixture("estimate.json")
    r = (await client.call_tool("ins_azki_car_value", {"vehicle_id": 182091, "year": 1398})).structured_content
    assert r["average_toman"] == 1683000000 and r["lower_toman"] == 1632000000
    assert q(api.calls[-1]) == {"vehicleId": "182091", "year": "1398", "zeroKilometer": "false"}
    api["/api/product/vehicle/price-estimate"] = lambda r: httpx.Response(400, json={"message": "x"})
    bad = await client.call_tool("ins_azki_car_value", {"vehicle_id": 1, "year": 1398})
    assert bad.is_error and "no value estimate" in bad.content[0].text


async def test_body_options_trims_covers_and_drops_disabled_choices(client, api):
    api["/api/product/body/covers/1"] = fixture("body_covers.json")
    api["/api/product/body/company-body-discounts/company/1"] = fixture("body_discounts_company.json")
    r = (
        await client.call_tool("ins_azki_body_options", {"company_id": 1, "vehicle_price": 1650000000})
    ).structured_content
    assert q(api.calls[0]) == {"vehiclePrice": "1650000000"} or q(api.calls[1]) == {"vehiclePrice": "1650000000"}
    first = r["covers"][0]
    assert first["name"] == "accessoryRobberyCoverID" and [c["id"] for c in first["choices"]] == [1, 2]
    assert r["discounts"][0]["id"] == 9


async def test_travel_quote_polls_until_completed(client, api, monkeypatch):
    from iran_insurance_mcp.azki import insurance

    async def no_sleep(_):
        return None

    monkeypatch.setattr("iran_insurance_mcp.azki.insurance.asyncio.sleep", no_sleep)
    answers = [fixture("travel_pending.json"), fixture("travel_done.json")]
    api["/api/marco/prices"] = lambda r: httpx.Response(200, json=answers.pop(0))
    r = await insurance.travel_quote([6, 7], 2, [2, 3])
    assert r["status"] == "COMPLETED" and r["count"] == 2 and not answers
    first, second = api.calls
    assert q(first) == {"countriesId": "6,7", "durationId": "2", "passengerAgeIds": "2,3"}
    assert q(second)["requestId"] == fixture("travel_pending.json")["requestId"]
    plan = r["companies"][0]["plans"][0]
    assert plan["price"] == 343981 and plan["cover_total"] == 30000 and plan["features"]


async def test_company_list_profile_and_product_page(client, api):
    api["/api/content/api/insurance-companies"] = fixture("companies_list.json")
    r = (await client.call_tool("ins_azki_company", {})).structured_content
    assert r["companies"][1] == {"slug": "asia-insurance", "name": "بیمه آسیا"}
    assert q(api.calls[-1])["fields[1]"] == "slug" and "populate" in q(api.calls[-1])
    api["/api/content/api/insurance-companies/asia-insurance"] = fixture("company.json")
    r = (await client.call_tool("ins_azki_company", {"slug": "asia-insurance"})).structured_content
    assert r["company"] == "بیمه آسیا" and r["facts"][0]["title"] == "سال تاسیس" and len(r["faq"]) == 2
    api["/api/content/api/insurance-company-products/asia-insurance"] = fixture("company_product.json")
    r = (
        await client.call_tool("ins_azki_company", {"slug": "asia-insurance", "product": "travel-insurance"})
    ).structured_content
    assert q(api.calls[-1])["productSlug"] == "travel-insurance" and r["cards"] and r["faq"]


async def test_blog_reads_the_feed_and_paginates(client, api):
    api["/blog/feed/"] = text_fixture("blog_feed.xml")
    r = (await client.call_tool("ins_azki_blog", {"chars": 200})).structured_content
    assert r["count"] == 2 and r["posts"][0]["url"].startswith("https://www.azki.com/blog/")
    assert r["posts"][0]["date"] and r["posts"][0]["categories"] and len(r["posts"][0]["text"]) <= 203
    assert "paged" not in q(api.calls[-1])
    await client.call_tool("ins_azki_blog", {"page": 3})
    assert q(api.calls[-1]) == {"paged": "3"}
    api["/blog/"] = text_fixture("blog_feed.xml")
    await client.call_tool("ins_azki_blog", {"query": "x"})
    assert q(api.calls[-1]) == {"s": "x", "feed": "rss2"}
    api["/blog/feed/"] = "<html>not a feed"
    bad = await client.call_tool("ins_azki_blog", {"page": 2})
    assert bad.is_error
