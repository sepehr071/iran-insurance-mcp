"""BimeBazar lookup tools: insurers and their ratings, reviews, claim centers, vehicle and place values, FAQ, glossary."""

from __future__ import annotations

import html
import re
from typing import Annotated, Any, Literal

from pydantic import Field

from ..registry import tool
from .http import CACHE_LONG, ApiError, fetch, page_props

SLUGS = Literal[
    "third-party-insurance",
    "car-body-insurance",
    "motorthird-party-insurance",
    "travel-insurance",
    "fire-insurance",
    "life-insurance",
    "supplemental-insurance",
    "sanhab",
]


def _text(s: str | None) -> str:
    """Page copy is HTML; keep the words."""
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", s or "")).split())


def _has(q: str | None, *fields: str | None) -> bool:
    return not q or any(q.lower() in (f or "").lower() for f in fields)


async def insurers() -> dict[str, Any]:
    """List the insurance companies BimeBazar sells, with market share, satisfaction and solvency ratings.

    The `url_name` of each company is the value other tools expect (previous_company, company).
    """
    d = (await fetch("/insurance_api/insurance-companies/", ttl=CACHE_LONG))["data"]["companies"]
    keys = (
        "name",
        "url_name",
        "market_share",
        "satisfaction_rate",
        "solvency_level",
        "complaint_response_time",
        "branches_num",
    )
    return {"count": len(d), "insurers": [{k: c.get(k) for k in keys} for c in d]}


@tool("Read BimeBazar insurer reviews")
async def ins_insurer_reviews(
    company: Annotated[
        str | None,
        Field(description="Insurer url_name from ins_insurers, e.g. 'iran'. Omit for all."),
    ] = None,
    order: Annotated[Literal["newest", "oldest"], Field(description="Review order.")] = "newest",
    page: Annotated[int, Field(description="1-based page, 20 reviews each.", ge=1, le=200)] = 1,
) -> dict[str, Any]:
    """Read BimeBazar customer reviews of insurers: four 1-5 ratings and the text, newest first.

    BimeBazar only. Use after ins_insurers to judge one insurer. Ratings: response quality, ease of payment, damage
    payout, response time.
    """
    q = {
        "ordering": "-created_date" if order == "newest" else "created_date",
        "page": page,
        "company__url_name": company,
    }
    d = (await fetch("/insurance_api/company-comments/", {k: v for k, v in q.items() if v})).get("data") or {}
    keys = (
        "company",
        "order_type",
        "response_quality_rate",
        "ease_of_payment_rate",
        "damage_price_rate",
        "response_time_rate",
        "likes_count",
        "dislikes_count",
        "text",
    )
    return {
        "total": d.get("count"),
        "page": page,
        "reviews": [{k: r.get(k) or None for k in keys} for r in d.get("results") or []],
    }


@tool("Find insurer claim centers")
async def ins_claim_centers(
    company: Annotated[str | None, Field(description="Insurer url_name from ins_insurers, e.g. 'iran'.")] = None,
    province: Annotated[str | None, Field(description="Province value from ins_places, e.g. 'tehran'.")] = None,
    city: Annotated[str | None, Field(description="City value from ins_places, e.g. 'karaj'.")] = None,
    service: Annotated[
        Literal["thirdparty_life", "thirdparty_financial", "carbody"] | None,
        Field(description="Claim type: third-party injury, third-party property, car body."),
    ] = None,
    page: Annotated[int, Field(description="1-based page, 5 centers each.", ge=1, le=200)] = 1,
) -> dict[str, Any]:
    """Find insurers' damage-claim branches with address, phone numbers and map position, filtered by insurer, place and claim type.

    BimeBazar only. Get insurer and place values from ins_insurers and ins_places first. Check `total` against 5 per page.
    """
    q = {"company": company, "province": province, "city": city, "field_of_activity": service, "page": page}
    d = (await fetch("/insurance_api/insurance-damage-centers/", {k: v for k, v in q.items() if v})).get("data") or {}
    keys = ("company", "province", "city", "address", "phone_number_first", "phone_number_second", "field_of_activity")
    centers = [
        {**{k: c.get(k) for k in keys}, "lat": c.get("lng"), "lng": c.get("lat")} for c in d.get("results") or []
    ]
    return {"total": d.get("count"), "page": page, "centers": centers}  # the API swaps lat and lng; fixed here


async def locations(
    query: Annotated[
        str | None, Field(description="Part of a province or city name, Persian or Latin, e.g. 'کرج' or 'karaj'.")
    ] = None,
) -> dict[str, Any]:
    """Look up the province and city values that bb_claim_centers and bb_quote_fire expect.

    Without a query only the 31 provinces are listed; with one, the matching provinces and cities.
    """
    prov = await fetch("/insurance_api/damage-centers-cities/", ttl=CACHE_LONG)
    if not query:
        return {"provinces": [{"name": p["province_name"], "name_fa": p["province_name_fa"]} for p in prov]}
    out = []
    for p in prov:
        cities = [
            {"name": c["name"], "name_fa": c["name_fa"]} for c in p["cities"] if _has(query, c["name"], c["name_fa"])
        ]
        if cities or _has(query, p["province_name"], p["province_name_fa"]):
            out.append({"province": p["province_name"], "province_fa": p["province_name_fa"], "cities": cities[:15]})
    return {"matches": out}


async def vehicles(
    query: Annotated[
        str | None, Field(description="Part of a brand or model name, Persian or Latin, e.g. 'پژو', 'kia', '206'.")
    ] = None,
    vehicle_type: Annotated[
        Literal["car", "autocar", "van", "motorcycle", "carrier", "pickup", "truck"],
        Field(description="Vehicle class; cars are by far the largest list."),
    ] = "car",
) -> dict[str, Any]:
    """Look up the brand and model values (like car_kia, car_kia_optima-jf) that the car quote tools expect.

    Without a query only brands are listed; with one, the matching brands and their matching models.
    """
    d = await fetch("/api/web_config/car_info/", ttl=CACHE_LONG)
    brands = [c for c in d["cars_list"] if c["type"] == vehicle_type]
    if not query:
        return {
            "count": len(brands),
            "brands": [{"value": c["name_en"], "name": c["name"], "models": len(c["models"])} for c in brands],
        }
    out = []
    for c in brands:
        models = [
            {"value": m["name_en"], "name": m["name"].strip()}
            for m in c["models"]
            if _has(query, m["name"], m["name_en"])
        ]
        if models or _has(query, c["name"], c["name_en"]):
            out.append({"value": c["name_en"], "name": c["name"], "models": models[:25] if models else None})
    return {"count": len(out), "brands": out[:15], "years": "any Jalali year from 1405 down to 1362"}


async def travel_countries(
    query: Annotated[str | None, Field(description="Part of a country name in Persian, e.g. 'ترکیه'.")] = None,
) -> dict[str, Any]:
    """List the destination countries and their numeric ids for bb_quote_travel.

    The ids are the site's own, not phone or ISO codes.
    """
    steps = (await page_props("travel-insurance")).get("wizardFlow", {}).get("steps", [])
    countries = next((s["data"] for s in steps if s.get("identifier") == "START"), [])
    found = [{"id": c["value"], "name": c["label"]} for c in countries if _has(query, c["label"])]
    return {"count": len(found), "countries": found[:60]}


async def faq(
    page: Annotated[SLUGS, Field(description="Which insurance line's landing page to read.")],
    query: Annotated[
        str | None, Field(description="Keep only questions or answers containing this text (Persian).")
    ] = None,
) -> dict[str, Any]:
    """Read a BimeBazar insurance page's short explanation and frequently asked questions in Persian.

    Use for rules and how-to questions (documents, discounts, delays), not for prices.
    """
    items = (await page_props(page)).get("content", {}).get("items", [])
    faq = [
        {"q": _text(i.get("title")), "a": _text(i.get("text"))}
        for it in items
        if it.get("item_type") == "faq"
        for i in it.get("items", [])
    ]
    intro = next((_text(it.get("text")) for it in items if it.get("item_type") == "short_explanation"), None)
    faq = [f for f in faq if _has(query, f["q"], f["a"])]
    if not faq and not intro:
        raise ApiError(f"No FAQ found on the '{page}' page.")
    return {"page": page, "intro": intro, "faq": faq[:30]}


@tool("Look up insurance terms")
async def ins_glossary(
    query: Annotated[str | None, Field(description="Term part, Persian or Latin, e.g. 'شاسی', 'vin'.")] = None,
) -> dict[str, Any]:
    """Look up short explanations of insurance and car-card terms (VIN, chassis number, liability cover and more).

    BimeBazar only. Use to explain a form field or a term in a quote.
    """
    terms = await fetch("/api/wiki/", ttl=CACHE_LONG)
    if any(not t.get("name") for t in terms):  # insurer agency-code rows carry no name, only 'asia-ins'
        cs = (await fetch("/insurance_api/insurance-companies/", ttl=CACHE_LONG))["data"]["companies"]
        insurers = {c["url_name"]: c["name"] for c in cs}
        for t in terms:
            n = insurers.get((t.get("keyword") or "").removesuffix("-ins"))
            if not t.get("name") and n:
                t["name"] = f"بیمه {n}"
    found = [
        {"term": t["name"] or t["keyword"], "key": t["keyword"], "explanation": _text(t.get("description"))}
        for t in terms
        if _has(query, t.get("name"), t.get("keyword"), t.get("description"))
    ]
    return {"count": len(found), "terms": found[:30]}
