import httpx
import pytest
from conftest import fixture, page

from iran_insurance_mcp.bimebazar import http

pytestmark = pytest.mark.anyio


def q(call: httpx.Request) -> list[tuple[str, str]]:
    return list(call.url.params.multi_items())


async def test_third_party_new_policy_query_and_price_row(client, api):
    api["/thirdparty/api/offers/"] = fixture("offers_thirdparty.json")
    r = (
        await client.call_tool(
            "ins_quote_third_party",
            {
                "car_brand": "car_peugeot",
                "car_model": "car_peugeot_206-type2",
                "car_production_year": 1400,
                "financial_coverage": 70000000,
            },
        )
    ).structured_content
    params = q(api.calls[0])
    for pair in [
        ("vehicle_type", "car"),
        ("car_usage", "passenger"),
        ("car_brand", "car_peugeot"),
        ("car_production_year", "1400"),
        ("policy_status", "without"),
        ("policy_term", "12"),
        ("financial_coverage", "70000000"),
    ]:
        assert pair in params, params
    assert not any(k in ("previous_company", "no_damage_factor") for k, _ in params)
    first = r["offers"][0]
    assert r["count"] == 2 and first["price_toman"] <= r["offers"][1]["price_toman"]
    assert first["company"] and first["tax_toman"]
    assert any(o.get("installments", [{}])[0].get("type") == "bb_bnpl" for o in r["offers"])


async def test_third_party_uses_the_row_of_the_chosen_coverage(client, api):
    d = fixture("offers_thirdparty.json")
    o = d["data"]["offers"][0]
    o["tariffs"] = [
        {"financial_coverage": 70000000, "tariff": 111, "tax": 1},
        {"financial_coverage": 100000000, "tariff": 222, "tax": 2},
    ]
    d["data"]["offers"] = [o]
    api["/thirdparty/api/offers/"] = d
    r = (
        await client.call_tool(
            "ins_quote_third_party",
            {"car_brand": "car_pride", "car_production_year": 1399, "financial_coverage": 100000000},
        )
    ).structured_content
    assert r["offers"][0]["price_toman"] == 222 and r["offers"][0]["tax_toman"] == 2


async def test_third_party_previous_policy_pairs_and_validation(client, api):
    api["/thirdparty/api/offers/"] = fixture("offers_thirdparty.json")
    await client.call_tool(
        "ins_quote_third_party",
        {
            "car_brand": "car_pride",
            "car_production_year": 1399,
            "previous_policy": "yes",
            "previous_company": "iran",
            "last_policy_start": "1404-09-10",
            "last_policy_end": "1405-09-10",
            "third_party_discount": 0.1,
            "driver_discount": 0.05,
        },
    )
    params = q(api.calls[0])
    for pair in [
        ("policy_status", "other"),
        ("previous_company", "iran"),
        ("last_policy_start_date", "1404-09-10"),
        ("last_policy_exp_date", "1405-09-10"),
        ("no_damage_factor", "0.1"),
        ("driver_no_damage_factor", "0.05"),
        ("has_damage", "false"),
    ]:
        assert pair in params, params
    bad = await client.call_tool(
        "ins_quote_third_party", {"car_brand": "car_pride", "car_production_year": 1399, "previous_policy": "yes"}
    )
    assert bad.is_error and "previous_company" in bad.content[0].text


async def test_empty_offers_explain_themselves(client, api):
    api["/carbody/api/offers/"] = {"status": "ok", "data": {"offers": [], "alerts": []}}
    r = (
        await client.call_tool(
            "ins_quote_car_body",
            {"car_brand": "car_pride", "car_model": "x", "car_production_year": 1400, "car_value": 300_000_000},
        )
    ).structured_content
    assert r["count"] == 0 and "No insurer" in r["note"]


async def test_car_body_query(client, api):
    api["/carbody/api/offers/"] = fixture("offers_carbody.json")
    r = (
        await client.call_tool(
            "ins_quote_car_body",
            {
                "car_brand": "car_kia",
                "car_model": "car_kia_optima-jf",
                "car_production_year": 1402,
                "car_value": 2_000_000_000,
            },
        )
    ).structured_content
    params = q(api.calls[0])
    for pair in [
        ("car_value", "2000000000"),
        ("car_accessories_value", "0"),
        ("has_previous_policy", "false"),
        ("car_is_new", "false"),
        ("car_is_imported", "false"),
    ]:
        assert pair in params, params
    assert r["offers"][0]["price_toman"] and r["offers"][0]["company"]


async def test_motorcycle_query(client, api):
    api["/thirdpartymotor/api/offers/"] = {"data": {"offers": []}}
    await client.call_tool("ins_quote_motorcycle", {"motor_type": "one_cylinder", "production_year": 1400})
    params = q(api.calls[0])
    for pair in [("car_brand", "one_cylinder"), ("car_production_year", "1400"), ("policy_status", "without")]:
        assert pair in params, params


async def test_fire_query(client, api):
    api["/fire/api/offers/"] = {"data": {"offers": []}}
    await client.call_tool(
        "ins_quote_fire",
        {
            "province": "tehran",
            "city": "tehran",
            "building_type": "apartment",
            "structure": "concrete",
            "building_year": 1395,
            "area_m2": 80,
            "covers": ["earthquake"],
        },
    )
    params = q(api.calls[0])
    for pair in [
        ("province_name", "tehran"),
        ("building_floor_area", "80"),
        ("building_properties_value", "0"),
        ("cover_earthquake", "true"),
        ("building_cost_per_area_unit", "10000000"),
    ]:
        assert pair in params, params
    assert not any(k == "apartment_count" for k, _ in params)


async def test_health_individual_and_family_keys(client, api):
    api["/health/api/offers/"] = fixture("offers_health.json")
    r = (
        await client.call_tool(
            "ins_quote_health", {"age_bands": ["age_16_45"], "base_insurers": ["social_security"], "covers": True}
        )
    ).structured_content
    assert q(api.calls[0]) == [
        ("base_insurance_type", "individual-family"),
        ("group", "individual"),
        ("number_of_person", "1"),
        ("individual_policy_holder:age_range:1", "age_16_45"),
        ("individual_policy_holder:base_insurance:1", "social_security"),
    ]
    assert r["offers"][0]["covers"] and r["offers"][0]["franchise"]
    await client.call_tool(
        "ins_quote_health",
        {"age_bands": ["age_16_45", "age_0_15"], "base_insurers": ["without", "without"], "family": True},
    )
    assert ("family_policy_holder:age_range:2", "age_0_15") in q(api.calls[1])
    bad = await client.call_tool(
        "ins_quote_health", {"age_bands": ["age_16_45"], "base_insurers": ["without", "without"]}
    )
    assert bad.is_error


async def test_reviews_drop_names(client, api):
    api["/insurance_api/company-comments/"] = fixture("reviews.json")
    r = (await client.call_tool("ins_insurer_reviews", {"company": "iran", "page": 2})).structured_content
    assert ("company__url_name", "iran") in q(api.calls[-1]) and ("ordering", "-id") in q(api.calls[-1])
    assert r["total"] == 316 and r["reviews"][0]["response_quality_rate"] and "name" not in r["reviews"][0]


async def test_claim_centers_filters_and_swapped_coordinates(client, api):
    api["/insurance_api/insurance-damage-centers/"] = fixture("claim_centers.json")
    r = (
        await client.call_tool("ins_claim_centers", {"company": "iran", "province": "tehran", "service": "carbody"})
    ).structured_content
    params = q(api.calls[0])
    for pair in [("company", "iran"), ("province", "tehran"), ("field_of_activity", "carbody"), ("page", "1")]:
        assert pair in params, params
    c = r["centers"][0]
    assert 25 < c["lat"] < 40 and 44 < c["lng"] < 64  # Iran; the API sends them swapped


async def test_glossary(client, api):
    api["/api/wiki/"] = fixture("wiki.json")
    r = (await client.call_tool("ins_glossary", {"query": "vin"})).structured_content
    assert r["terms"][0]["key"] == "vin"


async def test_cookie_check_redirect_is_replayed_once(client, api):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:  # ArvanCloud: redirect to the same URL with a cookie
            return httpx.Response(307, headers={"location": str(request.url), "set-cookie": "__arcscoc=x; Path=/"})
        return httpx.Response(200, json={"data": {"companies": []}})

    http.set_transport(httpx.MockTransport(handler))
    assert (await http.fetch("/insurance_api/insurance-companies/"))["data"] == {"companies": []}
    assert len(calls) == 2 and "__arcscoc=x" in calls[1].headers.get("cookie", "")


async def test_401_is_explained(api):
    api["/api/faq/"] = lambda request: httpx.Response(401, json={"detail": "no"})
    with pytest.raises(http.ApiError, match="signed-in"):
        await http.fetch("/api/faq/")


async def test_request_headers_match_the_sites_frontend(api):
    api["/thirdparty/api/offers/"] = {}
    await http.fetch("/thirdparty/api/offers/", {"car_brand": "car_pride"})
    h = api.calls[-1].headers
    assert h["accept"] == "*/*" and h["content-type"] == "application/json" and h["referer"] == "https://bimebazar.com/"
    assert (h["sec-fetch-site"], h["sec-fetch-mode"], h["sec-fetch-dest"]) == ("same-origin", "cors", "empty")
    assert h["priority"] == "u=1, i" and h["accept-language"].startswith("fa-IR") and "origin" not in h
    assert "authorization" not in h and "x-user-context" not in h


async def test_page_props_navigation_headers(api):
    api["/travel-insurance/"] = page("page_travel.html")
    await http.page_props("travel-insurance")
    h = api.calls[-1].headers
    assert h["accept"].startswith("text/html") and (h["sec-fetch-mode"], h["sec-fetch-dest"]) == (
        "navigate",
        "document",
    )
