import pytest

pytestmark = [pytest.mark.live, pytest.mark.anyio]


async def test_live_insurers_and_places(client):
    r = (await client.call_tool("ins_insurers", {"query": "آسیا"})).structured_content
    assert "asia" in {i["url_name"] for i in r["bimebazar"]["insurers"]}, r
    (a,) = r["azki"]["companies"]
    assert a["id"] == 3 and a["rating"] and a["reviews"] > 100, r
    r = (await client.call_tool("ins_places", {"query": "تهران"})).structured_content
    assert r["bimebazar"]["matches"] and r["azki"]["provinces"], r


async def test_live_vehicles_to_quote_and_value(client):
    r = (await client.call_tool("ins_vehicles", {"query": "206"})).structured_content
    assert any(m["value"] == "car_peugeot_206-type2" for b in r["bimebazar"]["brands"] for m in b["models"]), r
    models = {m["title"]: m["id"] for b in r["azki"]["brands"] for m in b["models"]}
    assert "206تیپ2" in models, r
    v = (
        await client.call_tool("ins_azki_car_value", {"vehicle_id": models["206تیپ2"], "year": 1398})
    ).structured_content
    assert v["lower_toman"] < v["average_toman"] < v["upper_toman"], v
    q = (
        await client.call_tool(
            "ins_quote_third_party",
            {
                "car_brand": "car_peugeot",
                "car_model": "car_peugeot_206-type2",
                "car_production_year": 1400,
                "financial_coverage": 100000000,
            },
        )
    ).structured_content
    assert q["count"] > 3 and q["offers"][0]["price_toman"] > 1_000_000, q


async def test_live_travel_quote_both_sites(client):
    r = (
        await client.call_tool("ins_quote_travel", {"destinations": ["آلمان"], "duration_days": 15, "limit": 5})
    ).structured_content
    assert r["bimebazar"]["offers"][0]["price_toman"] > 0, r
    assert r["azki"]["offers"][0]["price"] > 0 and r["azki"]["destinations"][0]["id"], r
    en = (
        await client.call_tool("ins_quote_travel", {"destinations": ["Germany"], "duration_days": 7, "limit": 2})
    ).structured_content
    assert "error" not in en["bimebazar"] and "error" not in en["azki"], en


async def test_live_content_both_sites(client):
    r = (await client.call_tool("ins_content", {"page": "third_party"})).structured_content
    assert len(r["bimebazar"]["faq"]) > 5 and r["azki"]["faq"], r
    r = (await client.call_tool("ins_azki_blog", {})).structured_content
    assert r["count"] > 0, r
