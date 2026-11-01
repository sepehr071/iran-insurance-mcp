<!-- mcp-name: io.github.sepehr071/iran-insurance-mcp -->

# iran-insurance-mcp: Iran insurance MCP server for AI agents (BimeBazar + Azki)

**iran-insurance-mcp is an unofficial, read-only MCP server that gives AI agents the public insurance data of two Iranian marketplaces, BimeBazar (bimebazar.com) and Azki (azki.com), and shows both side by side.**<br>
Its 18 tools compare insurers and ratings, look up vehicles and places, compare live travel prices from both sites in one call, read guides and FAQs, and quote third-party, motorcycle, car body, fire and supplementary health insurance (BimeBazar), estimate a car's value and list body covers (Azki).
No API key or account is needed. It works in Claude, Cursor, Copilot and any other MCP client.

[For AI agents](#for-ai-agents) · [Quick start](#quick-start) · [Tools](#tools) · [Limits](#limits)

---

## For AI agents

- **What:** unofficial MCP server (model context protocol) for bimebazar.com and azki.com, merged: insurers with ratings, vehicle and place lookups, travel insurance prices from both, guides and FAQ, plus each site's own tools.
- **Install:** `uvx iran-insurance-mcp` or `claude mcp add iran-insurance -- uvx iran-insurance-mcp`. Transport: stdio. Needs [uv](https://docs.astral.sh/uv/getting-started/installation/) (Python 3.10+).
- **Auth:** none. Optional `IRAN_INSURANCE_MCP_PROXY` (HTTP proxy URL, or a comma-separated list) applies to both sites; system proxy settings are ignored.
- **Access:** read-only. It cannot log in, buy, pay or file a claim, and never asks for a national ID, phone number or plate.
- **Tools:** 18, all prefixed `ins_`. Five take `provider` (`all` default, `bimebazar`, `azki`) and answer with one block per provider; if one site fails its block holds an `error` and the other still answers.
- **Use when:** the user asks which insurer is rated best, what third-party, body, motorcycle, fire or supplementary health insurance costs, what travel insurance costs on each site, where to file a claim, or how an insurance line works.
- **Do not use when:** the user needs a purchase, a life insurance price, or a plate/national-ID inquiry.
- **Output:** compact JSON. Prices are Toman unless a field says otherwise, years Jalali, text Persian.

## Quick start

```bash
claude mcp add iran-insurance -- uvx iran-insurance-mcp
```

Other clients: command `uvx`, args `["iran-insurance-mcp"]`.

## Tools

Merged (both sites, `provider` argument):

| Tool | What it does | Call next |
|---|---|---|
| `ins_insurers` | Insurers with each site's ratings: BimeBazar market share, satisfaction, solvency; Azki service stats and customer rating (`azki_kind` third or body). | `ins_insurer_reviews`, `ins_claim_centers`, `ins_azki_body_options`, quote tools (`previous_company`) |
| `ins_vehicles` | Brand and model ids from both vehicle catalogs (car, motorcycle, pickup, van, truck). | `ins_quote_third_party`, `ins_quote_car_body` (BimeBazar values), `ins_azki_car_value` (Azki id) |
| `ins_places` | Provinces and cities with each site's ids. | `ins_quote_fire`, `ins_claim_centers` |
| `ins_quote_travel` | Live travel prices from both sites for the same trip. Takes country names and a duration bucket; resolves each site's ids itself. | (end of flow) |
| `ins_content` | Short explanation, guide steps and FAQ of one insurance line (third_party, car_body, motorcycle, travel, fire, life, health, sanhab). | `ins_quote_*` |

BimeBazar only:

| Tool | What it does |
|---|---|
| `ins_quote_third_party` | Live third-party car prices from every insurer, cheapest first (with or without a previous policy). |
| `ins_quote_motorcycle` | Live motorcycle third-party prices. |
| `ins_quote_car_body` | Live car body insurance prices. |
| `ins_quote_fire` | Live home fire insurance prices. |
| `ins_quote_health` | Live supplementary health prices for one person, several people or a family. |
| `ins_insurer_reviews` | Customer reviews of insurers (four 1-5 ratings and text, no names). |
| `ins_claim_centers` | Damage-claim branches by insurer, place and claim type. |
| `ins_glossary` | Short explanations of insurance and car-card terms (VIN, chassis number ...). |

Azki only:

| Tool | What it does |
|---|---|
| `ins_azki_car_value` | Market value estimate (average, low, high) of a car model and year. |
| `ins_azki_body_options` | Optional covers and no-claim discount steps of one company for car body insurance. |
| `ins_azki_products` | Products of Azki's generic engine (life, elevator, fire and more). |
| `ins_azki_company` | List companies, read one company's profile and FAQ, or its page for one insurance type. |
| `ins_azki_blog` | Azki insurance blog posts, newest first, with search and categories. |

Travel is the one quote both sites price anonymously, so it is merged. The other quote tools stay BimeBazar only: Azki shows car, health, life and fire prices only after a phone number. Inputs also differ (BimeBazar asks brand/model values and previous-policy details; Azki's flow has no public price call), so there is nothing to merge.

Migrating from the single-site servers: `bb_insurers`/`az_companies` -> `ins_insurers`; `bb_vehicles`/`az_vehicles` -> `ins_vehicles`; `bb_locations`/`az_zones` -> `ins_places`; `bb_quote_travel`/`az_travel_quote` (+ both country lists, `az_lookup` travel lists) -> `ins_quote_travel`; `bb_faq`/`az_landing` -> `ins_content`; `bb_quote_*` -> `ins_quote_*`; `bb_insurer_reviews`, `bb_claim_centers`, `bb_glossary` -> `ins_*`; `az_car_value`, `az_body_options`, `az_products`, `az_company`, `az_blog` -> `ins_azki_*`. `az_lookup` is not exposed (the travel lists it served are used internally).

## Limits

- Azki does not show car (third-party, body, motorcycle), health, life or fire premiums without a phone number, so only BimeBazar prices those. Life insurance offers are empty on BimeBazar too (it also asks for a phone number first).
- The Sanhab plate/national-ID inquiry is not exposed; `ins_content('sanhab')` explains it.
- BimeBazar rate-limits one IP to about 25-30 calls per minute (HTTP 429); the client backs off and retries, and a travel comparison uses about five calls.
- Azki travel prices come as the API sends them; their currency is not confirmed (they sit on the same scale as BimeBazar's Toman prices). `medical_cover` is a foreign-currency amount, not Toman.
- Quotes are estimates for comparison; the price to pay is shown only when buying on the site. Unofficial: not affiliated with either site. Site and blog text is third-party content.
- Both sites sit behind Iranian CDNs; from abroad set `IRAN_INSURANCE_MCP_PROXY` to a proxy that works, or run from Iran. The server ignores system proxy variables on purpose.

## Development

```bash
uv sync
uv run ruff check . && uv run ruff format --check .
uv run python -m pytest -q
uv run python -m pytest -m live -q
```

MIT license.
