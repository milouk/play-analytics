"""PPP-tier classification, mispricing detection, and a PATCH applier
for Google Play one-time-product regional prices.

Shared between the dashboard (which surfaces recommendations) and the
``apply_pricing.py`` CLI (which writes changes to Play).

The price tiering is rough and not personalised — it's a starting point.
Always sanity-check before applying.
"""
from __future__ import annotations

import copy
import math
from dataclasses import dataclass

# --------------------------------------------------------------------------- #
# Country → PPP tier mapping. Tier 1 = no discount; tier 4 = ~80% off anchor.
# These groupings reflect Google's own published tier guidance and broad
# purchasing-power data, not a per-app conversion study. Edit to taste.
# --------------------------------------------------------------------------- #

TIER1 = {  # full anchor price
    "US", "CA", "GB", "IE", "AU", "NZ", "DE", "FR", "IT", "ES", "NL", "BE",
    "AT", "CH", "SE", "NO", "DK", "FI", "IS", "LU", "JP", "SG", "HK", "AE",
    "IL", "QA", "KW", "BH", "KR", "TW",
}
TIER2 = {  # ~60% of anchor
    "PT", "GR", "CY", "MT", "SI", "SK", "CZ", "PL", "HU", "EE", "LV", "LT",
    "HR", "BG", "RO", "RS", "BA", "MK", "AL", "ME", "UA", "RU", "BY", "KZ",
    "GE", "AM", "AZ", "TH", "MY", "CN", "BR", "CL", "UY", "CR", "PA", "MX",
    "SA", "OM", "JO", "ZA", "MU", "TT", "JM",
}
TIER3 = {  # ~30% of anchor
    "AR", "CO", "PE", "DO", "GT", "HN", "SV", "NI", "BO", "PY", "VE", "TR",
    "TN", "MA", "DZ", "LB", "IQ", "IR", "YE", "PH", "VN", "ID", "IN", "PK",
    "BD", "LK", "NP", "BT", "MV", "KH", "KG", "TJ", "TM", "UZ", "CU", "PR",
    "EC", "BS", "BB",
}
TIER4 = {  # ~20% of anchor
    "EG", "NG", "KE", "GH", "ET", "UG", "TZ", "RW", "CI", "SN", "CM", "AO",
    "ZM", "ZW", "MZ", "MG",
}

TIER_FACTOR = {"tier1": 1.00, "tier2": 0.60, "tier3": 0.30, "tier4": 0.20}


def country_tier(code: str) -> str | None:
    if code in TIER1: return "tier1"
    if code in TIER2: return "tier2"
    if code in TIER3: return "tier3"
    if code in TIER4: return "tier4"
    return None


# --------------------------------------------------------------------------- #
# Approximate USD FX rates (May 2026). Used ONLY for comparing current
# regional prices against the anchor target; actual price-setting happens
# in local currency. Keep best-effort current; not load-bearing.
# --------------------------------------------------------------------------- #

USD_RATES = {
    "USD": 1.0, "EUR": 1.10, "GBP": 1.27, "AUD": 0.66, "CAD": 0.73,
    "NZD": 0.62, "CHF": 1.12, "SEK": 0.095, "NOK": 0.094, "DKK": 0.147,
    "JPY": 0.0065, "KRW": 0.00068, "CNY": 0.138, "HKD": 0.128, "TWD": 0.031,
    "SGD": 0.74, "THB": 0.028, "MYR": 0.21, "PHP": 0.018, "IDR": 0.0000615,
    "VND": 0.000041, "INR": 0.012, "PKR": 0.0036, "BDT": 0.0085, "LKR": 0.0034,
    "NPR": 0.0075,
    "BRL": 0.20, "MXN": 0.054, "ARS": 0.0011, "CLP": 0.00104, "COP": 0.000245,
    "PEN": 0.27, "UYU": 0.024, "BOB": 0.145,
    "TRY": 0.029, "RUB": 0.011, "UAH": 0.024, "PLN": 0.25, "CZK": 0.043,
    "HUF": 0.0028, "RON": 0.22, "BGN": 0.56, "RSD": 0.0094,
    "EGP": 0.021, "NGN": 0.0007, "ZAR": 0.054, "KES": 0.0078, "MAD": 0.10,
    "DZD": 0.0075, "TND": 0.32, "GHS": 0.066, "TZS": 0.00039, "UGX": 0.00027,
    "XOF": 0.00167, "XAF": 0.00167,
    "AED": 0.272, "SAR": 0.267, "QAR": 0.275, "KWD": 3.27, "BHD": 2.65,
    "OMR": 2.6, "JOD": 1.41, "ILS": 0.27,
    "KZT": 0.0022, "AMD": 0.0026, "AZN": 0.59, "GEL": 0.37,
}


def price_to_usd(price: dict) -> float | None:
    """Convert a Play price dict ({currencyCode, units, nanos}) to USD."""
    ccy = price.get("currencyCode", "")
    rate = USD_RATES.get(ccy)
    if rate is None:
        return None
    units = int(price.get("units", 0))
    nanos = price.get("nanos", 0)
    return (units + nanos / 1e9) * rate


def fmt_local_price(price: dict) -> str:
    units = int(price.get("units", 0))
    nanos = price.get("nanos", 0)
    amount = units + nanos / 1e9
    ccy = price.get("currencyCode", "")
    if ccy in ("KRW", "JPY", "VND", "IDR", "CLP", "COP", "PYG", "HUF"):
        return f"{amount:,.0f} {ccy}"
    return f"{amount:,.2f} {ccy}"


def suggest_local_price(currency: str, target_usd: float) -> dict | None:
    """Suggest a Play-style local price (ending in .99 or whole number).

    Returns the price as a {currencyCode, units, nanos} dict, or None when
    we don't have an FX rate for that currency.
    """
    rate = USD_RATES.get(currency)
    if not rate or rate <= 0:
        return None
    local = target_usd / rate
    # Round to "nice" tier values:
    if currency in ("KRW", "JPY", "VND", "IDR", "CLP", "COP", "PYG", "HUF"):
        # No-decimal currencies — round UP to nearest tier-ish whole number
        # ending in 9/49/99/499/999 so it reads as a "price tier".
        if local >= 5000:
            local = math.ceil(local / 100) * 100 - 1
        elif local >= 500:
            local = math.ceil(local / 50) * 50 - 1
        else:
            local = math.ceil(local / 10) * 10 - 1
        units = int(local)
        nanos = 0
    else:
        # Round UP to the next .99 tier (Play's standard pricing rhythm).
        # math.ceil avoids Python's banker's rounding biting at .5 boundaries.
        local = max(0.99, math.ceil(local) - 0.01)
        units = int(local)
        nanos = int(round((local - units) * 1e9))
    return {"currencyCode": currency, "units": str(units), "nanos": nanos}


# --------------------------------------------------------------------------- #
# Recommendation engine
# --------------------------------------------------------------------------- #

# Verdict legend:
#   "fine":   priced within ±25% of expected — leave alone
#   "cut":    significantly over target, and there's no signal it converts
#   "raise":  significantly under target (rare)
#   "hold":   priced over target BUT the country has paying buyers; risk to ARPU
#   "skip":   no FX rate or no tier mapping
TOLERANCE = 0.25
MIN_INSTALL_SIGNAL = 3  # only recommend changes for countries with >=N installs


@dataclass(frozen=True)
class Recommendation:
    region: str
    currency: str
    current_price: dict
    current_usd: float | None
    expected_usd: float | None
    suggested_price: dict | None
    suggested_usd: float | None
    verdict: str
    reason: str
    installs: int
    buyers: int


def _anchor_usd(prices: list[dict]) -> float:
    """Pick the US price (or the highest tier-1 price) as the anchor."""
    by_region = {p["regionCode"]: p for p in prices}
    us = by_region.get("US")
    if us and (u := price_to_usd(us["price"])):
        return u
    for c in TIER1:
        if c in by_region and (u := price_to_usd(by_region[c]["price"])):
            return u
    return 4.99  # fallback


def recommend_for_product(
    product: dict,
    country_installs: dict[str, int],
    country_buyers: dict[str, int],
) -> tuple[list[Recommendation], float]:
    """Produce one Recommendation per regional config that has install signal.

    Returns (sorted recs, anchor_usd).
    """
    opts = product.get("purchaseOptions") or [{}]
    configs = opts[0].get("regionalPricingAndAvailabilityConfigs") or []
    anchor = _anchor_usd(configs)

    recs: list[Recommendation] = []
    for c in configs:
        region = c.get("regionCode", "")
        price = c.get("price", {})
        installs = country_installs.get(region, 0)
        buyers = country_buyers.get(region, 0)
        tier = country_tier(region)
        cur_usd = price_to_usd(price)
        if tier is None or cur_usd is None:
            verdict, reason, expected_usd, sugg, sugg_usd = "skip", "unmapped", None, None, None
        else:
            expected_usd = anchor * TIER_FACTOR[tier]
            delta = cur_usd / expected_usd - 1
            sugg = suggest_local_price(price.get("currencyCode", ""), expected_usd)
            sugg_usd = price_to_usd(sugg) if sugg else None
            is_no_op = (
                sugg is not None
                and sugg.get("currencyCode") == price.get("currencyCode")
                and int(sugg.get("units", 0)) == int(price.get("units", 0))
                and sugg.get("nanos", 0) == price.get("nanos", 0)
            )
            if installs < MIN_INSTALL_SIGNAL:
                verdict, reason = "skip", f"<{MIN_INSTALL_SIGNAL} installs"
            elif is_no_op:
                verdict, reason = "fine", "already at best tier price"
            elif abs(delta) <= TOLERANCE:
                verdict, reason = "fine", f"within ±{int(TOLERANCE*100)}% of tier target"
            elif delta > TOLERANCE and buyers > 0:
                verdict, reason = "hold", f"{buyers} buyer(s) — risk to ARPU"
            elif delta > TOLERANCE:
                verdict, reason = "cut", f"+{delta*100:.0f}% vs tier target, 0 buyers"
            else:
                verdict, reason = "raise", f"{delta*100:.0f}% vs tier target"

        recs.append(Recommendation(
            region=region,
            currency=price.get("currencyCode", ""),
            current_price=price,
            current_usd=cur_usd,
            expected_usd=expected_usd,
            suggested_price=sugg,
            suggested_usd=sugg_usd,
            verdict=verdict,
            reason=reason,
            installs=installs,
            buyers=buyers,
        ))
    # Sort: actionable first (cut > raise > hold > fine > skip), then installs.
    rank = {"cut": 0, "raise": 1, "hold": 2, "fine": 3, "skip": 4}
    recs.sort(key=lambda r: (rank[r.verdict], -r.installs))
    return recs, anchor


# --------------------------------------------------------------------------- #
# PATCH applier
# --------------------------------------------------------------------------- #


def apply_changes(
    pub,
    package: str,
    product_id: str,
    region_to_new_price: dict[str, dict],
) -> dict:
    """PATCH the one-time product with all given regional price changes in
    a single API call (atomic) and refetch to verify."""
    otp = pub.monetization().onetimeproducts()
    product = otp.get(packageName=package, productId=product_id).execute()
    regions_version = product.get("regionsVersion", {}).get("version", "2025/03")

    modified = copy.deepcopy(product)
    configs = modified["purchaseOptions"][0]["regionalPricingAndAvailabilityConfigs"]
    by_region = {c["regionCode"]: c for c in configs}
    for region, new_price in region_to_new_price.items():
        if region not in by_region:
            raise ValueError(f"region {region} not present in product")
        by_region[region]["price"] = new_price

    otp.patch(
        packageName=package,
        productId=product_id,
        regionsVersion_version=regions_version,
        updateMask="purchaseOptions",
        body=modified,
    ).execute()

    verify = otp.get(packageName=package, productId=product_id).execute()
    v_configs = verify["purchaseOptions"][0]["regionalPricingAndAvailabilityConfigs"]
    v_by_region = {c["regionCode"]: c for c in v_configs}
    result: dict[str, dict] = {}
    for region, expected in region_to_new_price.items():
        got = v_by_region[region]["price"]
        ok = (got.get("currencyCode") == expected.get("currencyCode")
              and int(got.get("units", 0)) == int(expected.get("units", 0))
              and got.get("nanos", 0) == expected.get("nanos", 0))
        result[region] = {"ok": ok, "got": got}
    return result
