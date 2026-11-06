"""BimeBazar price-quote tools: the compare page's `/{insurance}/api/offers/` call for each insurance line."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field

from ..registry import tool
from .http import ApiError, fetch

DATE = Annotated[str | None, Field(description="Jalali YYYY-MM-DD.", pattern=r"^1[34]\d\d-\d\d-\d\d$")]
DISCOUNT = Annotated[float, Field(description="Old-policy discount fraction (0.1 = 10%).", ge=0, le=0.7)]


def _pick(o: dict[str, Any], coverage: float | None) -> dict[str, Any]:
    """Third-party offers carry one price row per financial coverage; the site shows the row for the chosen one."""
    rows = o.get("tariffs") or []
    row = next((t for t in rows if coverage is not None and t.get("financial_coverage") == coverage), None)
    return {**o, **row} if row else o


def _installments(o: dict[str, Any]) -> list[dict[str, Any]] | None:
    plans = [
        {
            "type": p.get("installment_type"),
            "payments_toman": p.get("installment_payment_prices"),
            "total_toman": p.get("price_with_interest"),
        }
        for p in (o.get("installment_plans") or [])[:3]
    ]
    return plans or None


def _offer(o: dict[str, Any], coverage: float | None, covers: bool) -> dict[str, Any]:
    o = _pick(o, coverage)
    out = {
        "company": o.get("company_url_name"),
        "company_name": o.get("company_name"),
        "plan": o.get("plan_name"),
        "price_toman": o.get("tariff"),
        "tax_toman": o.get("tax"),
        "price_before_discount_toman": o.get("tariff_without_discount") or o.get("base_tariff"),
        "discount_toman": o.get("total_discount_value"),
        "installments": _installments(o),
        "satisfaction": o.get("satisfaction_rate"),
        "solvency": o.get("solvency_level"),
        "market_share_percent": o.get("market_share"),
        "complaint_response_days": o.get("complaint_response_time"),
        "claim_centers": o.get("claim_center_num"),
        "mobile_compensation": o.get("has_mobile_compensation"),
        "delivery": o.get("delivery_option"),
        "franchise": o.get("franchise"),
        "medical_commitment_toman": o.get("commitment"),
        "assistance_company": o.get("assistance_company"),
    }
    if covers and o.get("covers_list"):
        out["covers"] = [
            {k: c.get(k) for k in ("name", "value", "unit", "waiting_period")}
            for c in o["covers_list"]
            if c.get("value")
        ]
    return out


async def _quote(
    insurance: str, pairs: list[tuple[str, Any]], coverage: float | None = None, covers: bool = False, limit: int = 40
) -> dict[str, Any]:
    pairs = [(k, str(v).lower() if isinstance(v, bool) else v) for k, v in pairs if v is not None]
    body = await fetch(f"/{insurance}/api/offers/", pairs)
    d = body.get("data") or {}
    offers = sorted((_offer(o, coverage, covers) for o in d.get("offers") or []), key=lambda x: x["price_toman"] or 0)
    out: dict[str, Any] = {"count": len(offers), "offers": offers[:limit]}
    if not offers:
        out["note"] = (
            "No insurer returned a price for these inputs. Check the values (ins_vehicles, ins_insurers) and retry."
        )
    if d.get("financial_coverages"):
        out["financial_coverages"] = [int(c) for c in d["financial_coverages"]]
    if d.get("alerts"):
        out["alerts"] = d["alerts"]
    return out


def _previous(
    policy: str | None, company: str | None, start: str | None, exp: str | None, tp: float, drv: float, claims: bool
) -> list[tuple[str, Any]]:
    """Query pairs for the previous third-party policy (policy_status without/other)."""
    if policy != "yes":
        return [("policy_status", "without")]
    if not (company and start and exp):
        raise ApiError("previous_policy='yes' needs previous_company, last_policy_start and last_policy_end.")
    return [
        ("policy_status", "other"),
        ("previous_company", company),
        ("last_policy_start_date", start),
        ("last_policy_exp_date", exp),
        ("no_damage_factor", tp),
        ("driver_no_damage_factor", drv),
        ("has_damage", claims),
    ]


PREVIOUS = Annotated[
    Literal["none", "yes"],
    Field(description="'yes' needs previous_company, last_policy_start, last_policy_end (and the discounts)."),
]
COMPANY = Annotated[
    str | None,
    Field(description="url_name from ins_insurers, e.g. 'iran'."),
]


@tool("Quote third-party car insurance")
async def ins_quote_third_party(
    car_brand: Annotated[str, Field(description="Brand value from ins_vehicles, e.g. 'car_peugeot'.")],
    car_production_year: Annotated[int, Field(description="Production year, Jalali.", ge=1340, le=1450)],
    car_model: Annotated[
        str | None,
        Field(description="Model value from ins_vehicles, e.g. 'car_peugeot_206-type2'; omit if the brand has none."),
    ] = None,
    car_usage: Annotated[
        Literal["passenger", "agency", "taxi_intracity", "taxi_outskirt"],
        Field(description="Other vehicle types use passenger."),
    ] = "passenger",
    vehicle_type: Annotated[
        Literal["car", "carrier", "pickup", "truck", "van"],
        Field(description="Only car is verified."),
    ] = "car",
    previous_policy: PREVIOUS = "none",
    previous_company: COMPANY = None,
    last_policy_start: DATE = None,
    last_policy_end: DATE = None,
    third_party_discount: DISCOUNT = 0,
    driver_discount: DISCOUNT = 0,
    had_claim: Annotated[bool, Field(description="The previous policy paid a claim.")] = False,
    policy_term_months: Annotated[Literal[2, 3, 4, 6, 9, 12], Field(description="Months.")] = 12,
    financial_coverage: Annotated[
        int | None, Field(description="Cover in Toman, from financial_coverages in the answer.")
    ] = None,
) -> dict[str, Any]:
    """Get live third-party (شخص ثالث) car insurance prices from every insurer BimeBazar sells, cheapest first.

    BimeBazar only. Call ins_vehicles first for brand/model values, ins_insurers for previous_company. Prices are
    Toman for the whole term; no personal data needed.
    """
    pairs: list[tuple[str, Any]] = [
        ("vehicle_type", vehicle_type),
        ("car_usage", car_usage),
        ("car_brand", car_brand),
        ("car_model", car_model),
        ("car_production_year", car_production_year),
        *_previous(
            previous_policy,
            previous_company,
            last_policy_start,
            last_policy_end,
            third_party_discount,
            driver_discount,
            had_claim,
        ),
        ("policy_term", policy_term_months),
        ("financial_coverage", financial_coverage),
    ]
    return await _quote("thirdparty", pairs, financial_coverage)


@tool("Quote motorcycle third-party insurance")
async def ins_quote_motorcycle(
    motor_type: Annotated[
        Literal["electric", "one_cylinder", "two_cylinder", "multi_wheel"],
        Field(description="Motorcycle class."),
    ],
    production_year: Annotated[int, Field(description="Production year, Jalali.", ge=1340, le=1450)],
    previous_policy: PREVIOUS = "none",
    previous_company: COMPANY = None,
    last_policy_start: DATE = None,
    last_policy_end: DATE = None,
    third_party_discount: DISCOUNT = 0,
    driver_discount: DISCOUNT = 0,
    had_claim: bool = False,
    policy_term_months: Annotated[Literal[2, 3, 4, 6, 9, 12], Field(description="Months.")] = 12,
    financial_coverage: Annotated[int | None, Field(description="Cover in Toman, from financial_coverages.")] = None,
) -> dict[str, Any]:
    """Get live motorcycle third-party insurance prices from every insurer, cheapest first.

    BimeBazar only. ins_vehicles is not needed; ins_insurers gives previous_company. Prices are Toman for the whole term.
    """
    pairs: list[tuple[str, Any]] = [
        ("car_brand", motor_type),
        ("car_production_year", production_year),
        *_previous(
            previous_policy,
            previous_company,
            last_policy_start,
            last_policy_end,
            third_party_discount,
            driver_discount,
            had_claim,
        ),
        ("policy_term", policy_term_months),
        ("financial_coverage", financial_coverage),
    ]
    return await _quote("thirdpartymotor", pairs, financial_coverage)


@tool("Quote car body insurance")
async def ins_quote_car_body(
    car_brand: Annotated[str, Field(description="Brand value from ins_vehicles, e.g. 'car_kia'.")],
    car_model: Annotated[
        str,
        Field(description="Model value from ins_vehicles, e.g. 'car_kia_optima-jf'."),
    ],
    car_production_year: Annotated[int, Field(description="Production year, Jalali.", ge=1340, le=1450)],
    car_value: Annotated[
        int,
        Field(description="Car market value in Toman (minimum 50000000).", ge=50_000_000, le=1_000_000_000_000),
    ],
    accessories_value: Annotated[int, Field(description="Accessories in Toman.", ge=0)] = 0,
    car_usage: Annotated[Literal["passenger", "agency"], Field(description="Private or agency.")] = "passenger",
    had_previous_policy: Annotated[bool, Field(description="Had a body policy before (only false verified).")] = False,
    previous_company: COMPANY = None,
    previous_policy_end: DATE = None,
    years_without_claim: Annotated[
        int | None,
        Field(description="Claim-free years on the old policy (-1 = paid a claim, 0 = none).", ge=-1, le=9),
    ] = None,
    third_party_discount_years: Annotated[int, Field(description="Third-party no-claim years.", ge=0, le=14)] = 0,
) -> dict[str, Any]:
    """Get live car body (بدنه) insurance prices from every insurer, cheapest first.

    BimeBazar only. Needs a model from ins_vehicles; for car_value use ins_azki_car_value or the user's figure.
    """
    pairs: list[tuple[str, Any]] = [
        ("car_usage", car_usage),
        ("car_brand", car_brand),
        ("car_model", car_model),
        ("car_production_year", car_production_year),
        ("car_is_imported", False),
        ("discount_third_party", third_party_discount_years),
        ("has_previous_policy", had_previous_policy),
        ("car_is_new", False),
        ("car_value", car_value),
        ("car_accessories_value", accessories_value),
    ]
    if had_previous_policy:
        pairs += [
            ("previous_company", previous_company),
            ("last_policy_exp_date", previous_policy_end),
            ("years_without_incident", years_without_claim),
        ]
    return await _quote("carbody", pairs)


AGES = ("u12", "u65", "u70", "u75", "u80", "u85", "u100", "others")


async def quote_travel(countries: list[int], duration_days: int, counts: list[int], limit: int = 40) -> dict[str, Any]:
    """Live travel prices for BimeBazar country ids, a duration bucket (days) and travellers per AGES band."""
    if not any(counts):
        raise ApiError("At least one traveller is needed.")
    pairs: list[tuple[str, Any]] = [("country", c) for c in countries]
    pairs += [(f"{a}_persons", n) for a, n in zip(AGES, counts, strict=True) if n]
    pairs.append(("duration", duration_days))
    return await _quote("travel", pairs, limit=limit)


@tool("Quote fire insurance")
async def ins_quote_fire(
    province: Annotated[str, Field(description="Province value from ins_places, e.g. 'tehran'.")],
    city: Annotated[str, Field(description="City value from ins_places, e.g. 'tehran'.")],
    building_type: Annotated[
        Literal["apartment", "villa", "complex"],
        Field(description="Complex needs apartment_count."),
    ],
    structure: Annotated[
        Literal["steel", "concrete", "brick", "2800"],
        Field(description="Building frame."),
    ],
    building_year: Annotated[int, Field(description="Year built, Jalali.", ge=1300, le=1450)],
    area_m2: Annotated[int, Field(description="Floor area in square metres.", ge=9, le=100000)],
    contents_value: Annotated[int, Field(description="Contents value in Toman.", ge=0, le=100_000_000_000)] = 0,
    covers: Annotated[
        list[
            Literal[
                "theft_by_break",
                "pipe_break",
                "subsidence_landslide",
                "earthquake",
                "rain_snow_damage",
                "flood",
                "storm",
                "war",
                "heavy_snow",
            ]
        ],
        Field(description="Extra perils; all nine at once returns no offers.", max_length=9),
    ] = (),
    cost_per_m2: Annotated[
        int,
        Field(description="Rebuild cost per m2 in Toman (site minimum 10000000).", ge=1_000_000),
    ] = 10_000_000,
    apartment_count: Annotated[
        int | None, Field(description="Units, for building_type='complex'.", ge=1, le=10000)
    ] = None,
) -> dict[str, Any]:
    """Get live home fire insurance (آتش‌سوزی) prices from every insurer, cheapest first.

    BimeBazar only. Get province and city from ins_places first. Prices the building at cost_per_m2 x area plus
    optional contents and perils.
    """
    pairs: list[tuple[str, Any]] = [
        ("province_name", province),
        ("building_city", city),
        ("building_type", building_type),
        ("apartment_count", apartment_count),
        ("building_structure_type", structure),
        ("building_production_year", building_year),
        ("building_floor_area", area_m2),
        ("building_properties_value", contents_value),
        *[(f"cover_{c}", True) for c in covers],
        ("building_cost_per_area_unit", cost_per_m2),
    ]
    return await _quote("fire", pairs)


BASE = Literal[
    "social_security",
    "health_insurance_org",
    "armed_forces_health_insurance_org",
    "iranian_health_insurance",
    "without",
]
AGE_BANDS = Literal["age_0_15", "age_16_45", "age_46_50", "age_51_60", "age_61_70"]


@tool("Quote supplementary health insurance")
async def ins_quote_health(
    age_bands: Annotated[list[AGE_BANDS], Field(description="One age band per person.", min_length=1, max_length=10)],
    base_insurers: Annotated[
        list[BASE],
        Field(
            description="Basic insurer per person, same order and length as age_bands.",
            min_length=1,
            max_length=10,
        ),
    ],
    family: Annotated[bool, Field(description="One family policy (2+ people) instead of individual ones.")] = False,
    covers: Annotated[bool, Field(description="Include coverage limits (long).")] = False,
    limit: Annotated[int, Field(description="Most offers, cheapest first.", ge=1, le=60)] = 15,
) -> dict[str, Any]:
    """Get live supplementary health (تکمیلی درمان) insurance prices for one person, several people or a family.

    BimeBazar only. Plans with franchise (deductible fraction) and premium in Toman.
    """
    if len(age_bands) != len(base_insurers):
        raise ApiError("age_bands and base_insurers must have the same length.")
    if family and len(age_bands) < 2:
        raise ApiError("A family policy needs at least 2 people.")
    kind = "family" if family else "individual"
    pairs: list[tuple[str, Any]] = [
        ("base_insurance_type", "individual-family"),
        ("group", kind),
        ("number_of_person", len(age_bands)),
    ]
    for i, (a, b) in enumerate(zip(age_bands, base_insurers, strict=True), 1):
        pairs += [(f"{kind}_policy_holder:age_range:{i}", a), (f"{kind}_policy_holder:base_insurance:{i}", b)]
    return await _quote("health", pairs, covers=covers, limit=limit)
