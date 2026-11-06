"""Azki lookups and quotes that need no account: products, companies, vehicles, car value, lookups, travel prices."""

from __future__ import annotations

import asyncio
import random
from typing import Annotated, Any, Literal

from pydantic import Field

from ..registry import tool
from ..text import norm
from .http import CACHE_LONG, ApiError, fetch

RATING = "/api/rating/rating/api/v1/general/insurance-companies/rate"

# name -> path; answers are a list, or {"result": [...]} for the health lists
LOOKUPS = {
    "third_durations": "/api/product/third/durations",
    "third_covers": "/api/product/third/covers",
    "third_discounts": "/api/product/third/third-discounts",
    "driver_discounts": "/api/product/third/driver-discounts",
    "third_financial_damages": "/api/product/third/third-financial-damages",
    "third_life_damages": "/api/product/third/third-life-damages",
    "driver_life_damages": "/api/product/third/driver-life-damages",
    "body_discounts": "/api/product/body/body-discounts",
    "body_accessory_items": "/api/product/body/non-fabric-categories/with-items",
    "travel_durations": "/api/marco/durations/cache-list",
    "travel_passenger_ages": "/api/marco/passenger-ages/cache-list",
    "health_base_insurers": "/api/core/api/products/supplementary/base-insures",
    "health_age_ranges": "/api/core/api/products/supplementary/single-age-ranges",
    "health_family_relations": "/api/core/api/products/supplementary/relations",
}
LookupName = Literal[
    "third_durations",
    "third_covers",
    "third_discounts",
    "driver_discounts",
    "third_financial_damages",
    "third_life_damages",
    "driver_life_damages",
    "body_discounts",
    "body_accessory_items",
    "travel_durations",
    "travel_passenger_ages",
    "health_base_insurers",
    "health_age_ranges",
    "health_family_relations",
]


@tool("List Azki insurance products")
async def ins_azki_products(
    query: Annotated[str | None, Field(description="Persian product title part, e.g. 'عمر'.")] = None,
) -> dict[str, Any]:
    """List the insurance products Azki sells through its generic product engine (30 types such as life, elevator, fire).

    Azki only. Car, motorcycle, travel and health have their own flows and are not listed. `slug` is the
    azki.com/nano-product/<slug> landing; `insure_type` is Azki's numeric type.
    """
    r = await fetch("/api/nano/api/products", {"per_page": 200}, ttl=CACHE_LONG)
    q = norm(query or "")
    items = [
        {
            "insure_type": p["insureType"],
            "slug": p["landingUrl"],
            "title": p["title"],
            "has_compare": bool(p.get("hasCompare")),
            "business_only": bool(p.get("isB2b")),
        }
        for p in r.get("data", [])
        if p.get("isActive") and q in norm(p["title"])
    ]
    return {"count": len(items), "products": items}


async def companies(
    kind: Annotated[
        Literal["third", "body"],
        Field(description="'third' = third-party (liability) sellers, 'body' = car body insurance sellers."),
    ] = "third",
    query: Annotated[str | None, Field(description="Part of the company name in Persian, e.g. 'آسیا'.")] = None,
) -> dict[str, Any]:
    """List the insurance companies Azki sells car insurance for, with service stats and customer ratings.

    `id` is the company id used by az_body_options. satisfaction, wealth_level and complaint_response_time are
    Azki's own scores as sent; the unit of azki_discount_max and azki_discount_percent is not confirmed.
    Rating fields come from Azki customer reviews (1 to 5).
    """
    companies, ratings = await asyncio.gather(
        fetch(f"/api/product/{kind}/companies", ttl=CACHE_LONG), fetch(RATING, ttl=CACHE_LONG)
    )
    by_id = {x["id"]: x for x in ratings}
    q = norm(query or "")
    out = []
    for c in companies:
        if q not in norm(c["title"]):
            continue
        r = by_id.get(c["id"], {})
        out.append(
            {
                "id": c["id"],
                "title": c["title"],
                "available": bool(c.get("available")),
                "satisfaction": c.get("satisfaction"),
                "wealth_level": c.get("wealthLevel"),
                "complaint_response_time": c.get("complaintResponseTime"),
                "branches": c.get("branchNumber"),
                "online_damage": bool(c.get("onlineDamage")),
                "azki_discount_max": c.get("maxBimitoDiscount"),
                "azki_discount_percent": c.get("bimitoDiscountPercent"),
                "features": [f["title"] for f in c.get("features") or []],
                "rating": r.get("rate"),
                "reviews": r.get("totalReviews"),
                "rating_price": r.get("premiumAmountRate"),
                "rating_coverage": r.get("insuranceCoverageRate"),
                "rating_claims": r.get("amountDamageRate"),
                "rating_support": r.get("supportRate"),
            }
        )
    return {"count": len(out), "companies": out}


async def vehicles(
    kind: Annotated[
        Literal["third", "body", "motor"],
        Field(description="Catalog: 'third' (all vehicles), 'body' (body insurance), 'motor' (motorcycles)."),
    ] = "body",
    query: Annotated[
        str | None, Field(description="Brand name, Persian or Latin, e.g. 'پژو' or 'peugeot'. Omit to list brands.")
    ] = None,
    category: Annotated[
        int,
        Field(
            description="Vehicle category id: 1 car (default), 2 pickup, 7 van, 8 truck, 9 light truck, 10 bus, 11 minibus."
        ),
    ] = 1,
) -> dict[str, Any]:
    """Look up brand and model ids in Azki's vehicle catalog.

    Without `query` it lists the brands of one category with their model counts. With `query` it returns the models of
    the matching brands; a model `id` is the vehicle_id for az_car_value. Years are Jalali.
    """
    cats = await fetch(f"/api/product/vehicle/models/{kind}", ttl=CACHE_LONG)
    cat = next((c for c in cats if c["id"] == category), None)
    if cat is None:
        raise ApiError(f"Category {category} is not in the {kind} catalog; use one of {[c['id'] for c in cats]}.")
    q = norm(query or "")
    brands = [b for b in cat["brands"] if q in norm(b["title"]) or q in norm(b.get("latinTitle") or "")]
    if q and not brands:  # a model query such as '206': keep the brands that have a matching model
        found = [b | {"models": [m for m in b["models"] if q in norm(m["title"])]} for b in cat["brands"]]
        brands = [b for b in found if b["models"]]
    head = {"category": cat["title"], "usages": [u["title"] for u in cat.get("usages", [])]}
    if not query:
        return head | {
            "brands": [
                {"id": b["id"], "title": b["title"].strip(), "latin": b.get("latinTitle"), "models": len(b["models"])}
                for b in brands
            ]
        }
    return head | {
        "brands": [
            {
                "id": b["id"],
                "title": b["title"].strip(),
                "latin": b.get("latinTitle"),
                "models": [
                    {"id": m["id"], "title": m["title"], "imported": bool(m.get("imported"))} for m in b["models"]
                ],
            }
            for b in brands[:5]
        ]
    }


@tool("Estimate a car's market value")
async def ins_azki_car_value(
    vehicle_id: Annotated[int, Field(description="Azki model id from ins_vehicles.", ge=1)],
    year: Annotated[int, Field(description="Build year, Jalali.", ge=1300, le=1500)],
    zero_km: Annotated[bool, Field(description="Brand-new zero-km car.")] = False,
) -> dict[str, Any]:
    """Estimate a car's market value the way Azki does before pricing body insurance.

    Azki only. Call ins_vehicles first for the model id. Use the result as car_value (ins_quote_car_body) or
    vehicle_price (ins_azki_body_options). Returns average, lower and upper price in Toman; if no estimate exists,
    ask the user for the value.
    """
    try:
        r = await fetch(
            "/api/product/vehicle/price-estimate",
            {"vehicleId": vehicle_id, "year": year, "zeroKilometer": str(zero_km).lower()},
        )
    except ApiError as e:
        if e.status in (400, 404):
            raise ApiError(f"Azki has no value estimate for vehicle {vehicle_id}, year {year}.", 400) from e
        raise
    e = r.get("estimate") or {}
    return {
        "provider": r.get("provider"),
        "average_toman": e.get("latestAveragePrice"),
        "lower_toman": e.get("latestLowerPrice"),
        "upper_toman": e.get("latestUpperPrice"),
        "last_year_toman": e.get("lastYearPrice"),
        "zero_km_toman": e.get("priceZero"),
    }


async def lookup(
    name: Annotated[
        LookupName,
        Field(
            description="Which list: third-party durations/covers/discounts/damage history, body discounts or accessories, travel durations/passenger ages, health base insurers/age ranges/relations."
        ),
    ],
) -> dict[str, Any]:
    """Return one of Azki's fixed option lists, with the ids its forms and quote calls use.

    Use it to explain what a quote form asks (no-claim discount steps, cover amounts, durations) or to get ids for
    az_travel_quote. Each item has an id and a title; some add amount (third_covers, as the API sends it), percent or year.
    """
    r = await fetch(LOOKUPS[name], {"enable": "true"} if name == "third_covers" else None, ttl=CACHE_LONG)
    items = r["result"] if isinstance(r, dict) else r
    return {"name": name, "count": len(items), "items": items}


@tool("Get Azki body insurance covers and discounts")
async def ins_azki_body_options(
    company_id: Annotated[
        int, Field(description="Azki id from ins_insurers (provider='azki', azki_kind='body').", ge=1)
    ],
    vehicle_price: Annotated[int, Field(description="Car value in Toman.", ge=1)],
) -> dict[str, Any]:
    """List the optional covers and no-claim discount steps one company offers for car body insurance.

    Azki only. Explains what a body policy can include and the no-claim discount steps. It does not price a policy
    (Azki needs a phone number); use ins_quote_car_body for prices.
    """
    covers, discounts = await asyncio.gather(
        fetch(f"/api/product/body/covers/{company_id}", {"vehiclePrice": vehicle_price}),
        fetch(f"/api/product/body/company-body-discounts/company/{company_id}"),
    )
    return {
        "covers": [
            {
                "name": c["name"],
                "title": c["title"],
                "description": c.get("description"),
                "choices": [
                    {"id": x["id"], "title": x["longTitle"] or x["title"]}
                    for x in c.get("availableChoices", [])
                    if not x.get("disabled")
                ],
                "disabled": bool(c.get("disabled")),
                "default": bool(c.get("default")),
            }
            for c in covers
        ],
        "discounts": [{"id": d["discountId"], "title": d["title"], "percent": d["percent"]} for d in discounts],
    }


async def zones(
    query: Annotated[str | None, Field(description="Part of a province or city name in Persian, e.g. 'تهران'.")] = None,
) -> dict[str, Any]:
    """List the provinces and cities Azki uses for addresses, with ids; filter by a Persian name.

    Without `query` it lists the provinces only. With `query` it returns the matching provinces and cities.
    """
    r = await fetch("/api/core/api/data/v2/zones/-1", ttl=CACHE_LONG)
    zones = r["result"]
    q = norm(query or "")
    if not q:
        return {
            "provinces": [
                {"id": z["id"], "name": z["name"], "capital": z.get("capital"), "cities": len(z["cities"])}
                for z in zones
            ]
        }
    out = []
    for z in zones:
        cities = [{"id": c["id"], "name": c["name"]} for c in z["cities"] if q in norm(c["name"])]
        if q in norm(z["name"]) or cities:
            out.append(
                {
                    "id": z["id"],
                    "name": z["name"],
                    "cities": cities
                    if q not in norm(z["name"])
                    else [{"id": c["id"], "name": c["name"]} for c in z["cities"]][:40],
                }
            )
    return {"count": len(out), "provinces": out}


async def travel_countries(
    query: Annotated[
        str | None, Field(description="Country name in Persian or English, e.g. 'آلمان' or 'germany'.")
    ] = None,
) -> dict[str, Any]:
    """List the destination countries Azki's travel insurance knows, with ids for az_travel_quote."""
    r = await fetch("/api/marco/countries/cache-list", ttl=CACHE_LONG)
    q = norm(query or "")
    items = [
        {"id": c["id"], "title": c["title"], "english": c.get("englishTitle")}
        for c in r
        if q in norm(c["title"]) or q in norm(c.get("englishTitle") or "")
    ]
    return {"count": len(items), "countries": items[:60]}


async def travel_quote(
    country_ids: Annotated[
        list[int], Field(description="Destination ids from az_travel_countries.", min_length=1, max_length=10)
    ],
    duration_id: Annotated[
        int,
        Field(description="Stay length id from az_lookup travel_durations (1 = up to 7 days ... 9 = one year).", ge=1),
    ],
    passenger_age_ids: Annotated[
        list[int],
        Field(
            description="One age-band id per traveller from az_lookup travel_passenger_ages.",
            min_length=1,
            max_length=10,
        ),
    ],
) -> dict[str, Any]:
    """Get live travel insurance prices from the companies on Azki for a trip, with plans per company.

    Anonymous, no personal data. Azki computes prices progressively, so this waits up to about 20 seconds for the
    answer to finish. Amounts are as the API sends them (the site shows price in Toman, cover_total in euro or dollars
    as the plan features say; the currencies are not confirmed). Prices are per the traveller group given.
    """
    params: dict[str, Any] = {
        "countriesId": ",".join(map(str, country_ids)),
        "durationId": duration_id,
        "passengerAgeIds": ",".join(map(str, passenger_age_ids)),
    }
    r: dict[str, Any] = {}
    for _ in range(10):
        r = await fetch(
            "/api/marco/prices", params | ({"requestId": r["requestId"]} if r.get("requestId") else {}), ttl=0
        )
        if r.get("requestStatus") != "PENDING":
            break
        await asyncio.sleep(2 + random.uniform(0, 0.5))
    companies = [
        {
            "company_id": c["companyId"],
            "company": c["title"],
            "satisfaction": c.get("satisfaction"),
            "branches": c.get("branchNumber"),
            "plans": [
                {
                    "price": p["price"],
                    "price_after_discount": p["discountedPrice"],
                    "cover_total": p.get("coverTotalPrice"),
                    "zone": p.get("zoneTitle"),
                    "assistance_company": p.get("rescuerTitle"),
                    "duration": p.get("durationTitle"),
                    "features": [f["title"] for f in p.get("features") or []],
                }
                for p in c.get("prices", [])
            ],
        }
        for c in r.get("responses", [])
    ]
    return {"status": r.get("requestStatus"), "count": len(companies), "companies": companies}
