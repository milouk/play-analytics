"""Render dashboards from purely synthetic data — for the public demo.

Generates plausible-looking metrics for two fictional apps so the demo
at milouk.me/projects/play-analytics shows what the tool produces without
exposing any real Play Console data. Deterministic (fixed seed) so the
demo output is stable across rebuilds.
"""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import dashboard
import parse
import report_md


# --- demo apps ------------------------------------------------------------- #

DEMO_APPS = [
    {
        "package": "co.example.whisper",
        "name": "Whisper",
        "pro_sku": "whisper_pro",
        "pro_title": "Whisper Pro",
        "pro_price_local": 4.99,
        "pro_price_ccy": "USD",
        "seed": 42,
        "active_now": 412,
        "growth_factor": 1.8,
        "version_codes": [7, 8, 9, 10, 11, 12, 13],
        "current_release": "1.4.0",
        "current_track_versions": ["13"],
        "review_seeds": [
            (5, "Finally a notes app that doesn't get in my way. Sync just works."),
            (5, "Bought Pro the same day I installed it. Worth every cent."),
            (4, "Great app overall — would love a tablet layout."),
            (5, ""),
            (5, "Clean, fast, no telemetry. Exactly what I wanted."),
            (3, "Feels slow on my older device sometimes."),
            (5, "Replaced three apps for me. Daily driver now."),
        ],
    },
    {
        "package": "co.example.pixelmaze",
        "name": "PixelMaze",
        "pro_sku": "pixelmaze_unlock",
        "pro_title": "Unlock all packs",
        "pro_price_local": 2.99,
        "pro_price_ccy": "USD",
        "seed": 7,
        "active_now": 1187,
        "growth_factor": 2.4,
        "version_codes": [22, 23, 24, 25, 26, 27, 28, 29],
        "current_release": "3.1.2",
        "current_track_versions": ["29"],
        "review_seeds": [
            (5, "Hours of fun in tiny levels — perfect for the metro."),
            (5, "Unlocked the full game in week one. No regrets."),
            (4, "Levels 40+ are brutal in the best way."),
            (5, "Pixel art is gorgeous. Music too."),
            (2, "Crashed on me once on level 23. Otherwise great."),
            (5, ""),
            (4, "Wish there were more daily challenges."),
            (5, "Bought this for my niece, ended up addicted myself."),
        ],
    },
]


# Realistic country / OS / device / language distributions. Skewed toward
# tier-1 buyer markets, but with a long tail of free installs from emerging
# markets — mirrors typical paid-utility app shape.

COUNTRY_DIST = [
    ("US", 0.16), ("IN", 0.12), ("BR", 0.08), ("DE", 0.07), ("GB", 0.06),
    ("ID", 0.05), ("MX", 0.05), ("FR", 0.04), ("IT", 0.04), ("ES", 0.03),
    ("CA", 0.03), ("AU", 0.03), ("PL", 0.03), ("NL", 0.02), ("TR", 0.02),
    ("PK", 0.02), ("VN", 0.02), ("PH", 0.02), ("EG", 0.02), ("AR", 0.02),
    ("CO", 0.01), ("CL", 0.01), ("RO", 0.01), ("CZ", 0.01), ("KR", 0.01),
    ("JP", 0.01), ("ZA", 0.01),
]

LANGUAGE_DIST = [
    ("en_US", 0.32), ("en_GB", 0.12), ("en_IN", 0.09), ("es_US", 0.07),
    ("pt_BR", 0.06), ("de_DE", 0.06), ("fr_FR", 0.04), ("it_IT", 0.04),
    ("es_ES", 0.03), ("id_ID", 0.03), ("pl_PL", 0.02), ("ru_RU", 0.02),
    ("tr_TR", 0.02), ("ar", 0.02), ("nl_NL", 0.02), ("ja_JP", 0.01),
    ("ko_KR", 0.01), ("zh_CN", 0.01), ("vi_VN", 0.01),
]

OS_DIST = [
    ("36", 0.30), ("35", 0.25), ("34", 0.18), ("33", 0.12),
    ("32", 0.06), ("31", 0.04), ("30", 0.03), ("29", 0.02),
]

DEVICE_DIST = [
    ("pa3q", 0.06), ("e3q", 0.05), ("dm3q", 0.05), ("m3q", 0.04),
    ("HWANE", 0.04), ("V2511", 0.03), ("tanzanite", 0.03), ("a16", 0.03),
    ("OP5B05L1", 0.03), ("Infinix-X6525", 0.03), ("TECNO-KM4", 0.02),
    ("V2430", 0.02), ("a12s", 0.02), ("a07", 0.02), ("dew", 0.02),
    ("rosemary", 0.02), ("rubypro", 0.02), ("HNANY-Q", 0.02),
    ("blazer", 0.02), ("klimt", 0.01), ("panther", 0.01), ("coral", 0.01),
    ("Spacewar", 0.01),
]


def _multinomial(total: int, dist: list[tuple[str, float]], rng: random.Random) -> list[tuple[str, int]]:
    """Draw `total` samples across a categorical distribution and return counts."""
    counts: dict[str, int] = {k: 0 for k, _ in dist}
    keys = [k for k, _ in dist]
    weights = [w for _, w in dist]
    for _ in range(total):
        choice = rng.choices(keys, weights=weights, k=1)[0]
        counts[choice] += 1
    return [(k, v) for k, v in counts.items() if v > 0]


def _build_timeline(rng: random.Random, active_now: int, growth: float) -> list[dict]:
    """60-day growth curve climbing to `active_now`."""
    days = 60
    today = date(2026, 5, 23)
    start = today - timedelta(days=days)
    timeline = []
    active = 0
    cumulative_installs = 0
    cumulative_uninstalls = 0
    for i in range(days):
        d = start + timedelta(days=i)
        # Daily installs follow an exponentialish curve with weekly noise.
        daily = max(1, int(rng.gauss(
            (active_now / days) * (0.4 + (i / days) * 1.6),
            (active_now / days) * 0.25,
        )))
        # Slight weekday boost.
        if d.weekday() < 5:
            daily = int(daily * 1.1)
        # Daily uninstalls: about 70% of installs eventually churn over the window.
        daily_unin = int(daily * 0.65 * (i / days))
        cumulative_installs += daily
        cumulative_uninstalls += daily_unin
        active = max(0, cumulative_installs - cumulative_uninstalls)
        timeline.append({
            "date": d.isoformat(),
            "device_installs": daily,
            "user_installs": daily,
            "user_uninstalls": daily_unin,
            "active_devices": active,
            "install_events": int(daily * 1.05),
            "uninstall_events": int(daily_unin * 1.05),
            "update_events": int(active * 0.05),
        })
    # Scale to land exactly on active_now.
    scale = active_now / max(1, timeline[-1]["active_devices"])
    for t in timeline:
        for k in ("device_installs", "user_installs", "user_uninstalls",
                  "active_devices", "install_events", "uninstall_events",
                  "update_events"):
            t[k] = max(0, int(t[k] * scale))
    return timeline


def _build_crashes(rng: random.Random, timeline: list[dict]) -> list[dict]:
    """Sparse crashes + ANRs — most days zero, occasional 1-3."""
    out = []
    for t in timeline:
        if rng.random() < 0.18:
            out.append({
                "date": t["date"],
                "crashes": rng.choice([0, 0, 0, 1, 1, 2]),
                "anrs": rng.choice([0, 0, 1, 1, 2, 3]),
            })
        else:
            out.append({"date": t["date"], "crashes": 0, "anrs": 0})
    return out


def _build_reviews(app_cfg: dict, rng: random.Random) -> list[dict]:
    """Reviews seeded from a small curated pool, anonymised."""
    reviews = []
    base_date = datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc)
    for i, (stars, text) in enumerate(app_cfg["review_seeds"]):
        ver = rng.choice(app_cfg["version_codes"][-3:])
        d = base_date + timedelta(days=i * 6 + rng.randint(0, 4))
        reviews.append({
            "submitted_at": d.isoformat().replace("+00:00", "Z"),
            "updated_at": d.isoformat().replace("+00:00", "Z"),
            "stars": stars,
            "language": rng.choice(["en", "es", "de", "fr", "pt"]),
            "device": rng.choice([d for d, _ in DEVICE_DIST[:6]]),
            "version_code": str(ver),
            "version_name": app_cfg["current_release"],
            "title": "",
            "text": text,
            "reply_text": "",
        })
    return sorted(reviews, key=lambda r: r["submitted_at"])


def _build_sales(app_cfg: dict, rng: random.Random, total_installs: int) -> list[dict]:
    """Synthetic sales: ~2% conversion, prices in plausible local currencies."""
    n = max(3, int(total_installs * 0.022))
    base_price = app_cfg["pro_price_local"]
    base_ccy = app_cfg["pro_price_ccy"]
    paying_countries_pool = ["US","US","US","US","US","DE","DE","DE","GB","GB","FR","IT","ES","BR","CA","AU","NL","SE","KR","JP"]
    out = []
    base_date = date(2026, 4, 1)
    for i in range(n):
        country = rng.choice(paying_countries_pool)
        # Pick currency/price by country (approximated to base price level).
        ccy_by_country = {
            "US":("USD", base_price), "GB":("GBP", round(base_price*0.85, 2)),
            "DE":("EUR", round(base_price*1.0, 2)), "FR":("EUR", round(base_price*1.0, 2)),
            "IT":("EUR", round(base_price*1.0, 2)), "ES":("EUR", round(base_price*1.0, 2)),
            "NL":("EUR", round(base_price*1.0, 2)), "SE":("SEK", round(base_price*10.5, 2)),
            "BR":("BRL", round(base_price*4.9, 2)), "CA":("CAD", round(base_price*1.35, 2)),
            "AU":("AUD", round(base_price*1.5, 2)), "KR":("KRW", int(base_price*1500)),
            "JP":("JPY", int(base_price*150)),
        }
        ccy, price = ccy_by_country.get(country, (base_ccy, base_price))
        tax = round(price * rng.uniform(0.0, 0.21), 2)
        charged = round(price + tax, 2)
        out.append({
            "order": f"GPA.{rng.randint(1000,9999)}-{rng.randint(1000,9999)}-{rng.randint(1000,9999)}-{rng.randint(10000,99999)}",
            "date": (base_date + timedelta(days=rng.randint(0, 50))).isoformat(),
            "status": "Charged",
            "device": rng.choice([d for d, _ in DEVICE_DIST[:10]]),
            "product": app_cfg["pro_title"],
            "sku": app_cfg["pro_sku"],
            "type": "One-time product",
            "currency": ccy,
            "item_price": price,
            "tax": tax,
            "charged": charged,
            "country": country,
            "city": "",
            "channel": "",
        })
    return sorted(out, key=lambda s: s["date"])


def _build_earnings(sales: list[dict], rng: random.Random) -> list[dict]:
    """Finalised earnings for the prior month, converted to EUR merchant."""
    out = []
    finalised_month = "Apr"  # April finalised, May still settling
    for s in sales:
        if not s["date"].startswith("2026-04"):
            continue
        amount = s["charged"]
        if s["currency"] != "EUR":
            # Naive demo FX, just to show conversion happens.
            fx = {"USD": 0.92, "GBP": 1.17, "BRL": 0.19, "CAD": 0.68, "AUD": 0.61,
                  "KRW": 0.0007, "JPY": 0.006, "SEK": 0.088}.get(s["currency"], 1.0)
            amount = round(amount * fx, 2)
        out.append({
            "date": f"{finalised_month} {int(s['date'][-2:])}, 2026",
            "type": "Charge",
            "description": s["order"],
            "buyer_currency": s["currency"],
            "buyer_amount": s["charged"],
            "merchant_currency": "EUR",
            "merchant_amount": amount,
            "buyer_country": s["country"],
            "product_id": s["sku"],
        })
        out.append({
            "date": f"{finalised_month} {int(s['date'][-2:])}, 2026",
            "type": "Google fee",
            "description": s["order"],
            "buyer_currency": s["currency"],
            "buyer_amount": 0.0,
            "merchant_currency": "EUR",
            "merchant_amount": round(-amount * 0.15, 2),
            "buyer_country": s["country"],
            "product_id": s["sku"],
        })
    return out


def _summary(metrics: dict) -> dict:
    """Replicates parse._summary (kept in sync — small & stable)."""
    from collections import Counter, defaultdict

    timeline = metrics["timeline"]
    sales = metrics["sales"]
    reviews = metrics["reviews"]
    crashes = metrics["crashes_timeline"]
    earnings = metrics["earnings"]

    total_user_installs = sum(d["user_installs"] for d in timeline)
    total_user_uninstalls = sum(d["user_uninstalls"] for d in timeline)
    total_install_events = sum(d["install_events"] for d in timeline)
    total_uninstall_events = sum(d["uninstall_events"] for d in timeline)
    active_now = timeline[-1]["active_devices"] if timeline else 0

    charged = [s for s in sales if s["status"] == "Charged"]
    revenue_by_ccy: dict[str, float] = defaultdict(float)
    for s in charged:
        revenue_by_ccy[s["currency"]] += s["charged"]

    net_merchant: dict[str, float] = defaultdict(float)
    for e in earnings:
        if e["merchant_currency"]:
            net_merchant[e["merchant_currency"]] += e["merchant_amount"]

    star_dist: Counter = Counter()
    for r in reviews:
        if r["stars"]:
            star_dist[r["stars"]] += 1
    rated = sum(star_dist.values())
    avg_stars = sum(k * v for k, v in star_dist.items()) / rated if rated else 0.0
    paying = Counter(s["country"] for s in charged)
    conv = (len(charged) / total_user_installs * 100) if total_user_installs else 0.0

    return {
        "window_start": timeline[0]["date"] if timeline else "",
        "window_end": timeline[-1]["date"] if timeline else "",
        "total_user_installs": total_user_installs,
        "total_user_uninstalls": total_user_uninstalls,
        "total_install_events": total_install_events,
        "total_uninstall_events": total_uninstall_events,
        "active_devices_now": active_now,
        "paid_orders": len(charged),
        "paid_conversion_pct": round(conv, 3),
        "revenue_by_currency": {k: round(v, 2) for k, v in revenue_by_ccy.items()},
        "earnings_net": {k: round(v, 2) for k, v in net_merchant.items()},
        "earnings_months": ["2026-04"] if earnings else [],
        "paying_countries": paying.most_common(),
        "review_count": len(reviews),
        "review_avg_stars": round(avg_stars, 2),
        "review_star_dist": dict(star_dist),
        "crashes_total": sum(c["crashes"] for c in crashes),
        "anrs_total": sum(c["anrs"] for c in crashes),
    }


def _build_app(cfg: dict) -> dict:
    rng = random.Random(cfg["seed"])
    timeline = _build_timeline(rng, cfg["active_now"], cfg["growth_factor"])
    total_installs = sum(t["user_installs"] for t in timeline)
    country_counts = _multinomial(total_installs, COUNTRY_DIST, rng)
    lang_counts = _multinomial(total_installs, LANGUAGE_DIST, rng)
    device_counts = _multinomial(total_installs, DEVICE_DIST, rng)
    os_counts = _multinomial(total_installs, OS_DIST, rng)
    # Version: most installs on latest, descending share for older versions.
    versions = cfg["version_codes"]
    version_weights = [0.04, 0.05, 0.06, 0.08, 0.15, 0.25, 0.37][: len(versions)]
    while len(version_weights) < len(versions):
        version_weights.insert(0, 0.02)
    version_counts = _multinomial(total_installs, list(zip(map(str, versions), version_weights)), rng)

    sales = _build_sales(cfg, rng, total_installs)
    reviews = _build_reviews(cfg, rng)
    crashes = _build_crashes(rng, timeline)
    earnings = _build_earnings(sales, rng)

    # Build a plausible regional pricing config so the dashboard's
    # Pricing Recommendations section has something to recommend on.
    # Some entries are intentionally mispriced (left at USD default) to
    # demonstrate the "cut" verdict.
    base = cfg["pro_price_local"]
    regional_prices = [
        # Tier-1 markets: anchor / tier-1 pricing.
        ("US", "USD", base), ("CA", "CAD", round(base * 1.35, 2)),
        ("GB", "GBP", round(base * 0.85, 2)), ("DE", "EUR", round(base * 1.0, 2)),
        ("FR", "EUR", round(base * 1.0, 2)), ("AU", "AUD", round(base * 1.5, 2)),
        ("JP", "JPY", int(base * 150)), ("KR", "KRW", int(base * 1500)),
        ("SG", "SGD", round(base * 1.35, 2)),
        # Tier-2 markets: correctly priced.
        ("BR", "BRL", round(base * 4.0, 2)), ("MX", "MXN", round(base * 18, 2)),
        ("PL", "PLN", round(base * 2.4, 2)), ("CZ", "CZK", int(base * 14)),
        # Tier-3 markets at PPP.
        ("IN", "INR", round(base * 22, 2)), ("ID", "IDR", int(base * 4000)),
        # Mispriced — these should surface as "cut" recommendations.
        ("TR", "TRY", round(base * 52, 2)),
        ("EG", "EGP", round(base * 56, 2)),
        ("NG", "NGN", round(base * 1370, 2)),
        ("PK", "PKR", round(base * 260, 2)),
        ("AR", "USD", base),  # USD default, wrong for AR
        ("VN", "VND", int(base * 24000)),
        ("PH", "PHP", round(base * 64, 2)),
    ]
    regional_configs = [
        {"regionCode": rc,
         "price": {"currencyCode": ccy,
                   "units": str(int(amt)),
                   "nanos": int(round((amt - int(amt)) * 1e9))},
         "availability": "AVAILABLE"}
        for rc, ccy, amt in regional_prices
    ]
    api_snapshot = {
        "onetime_products": {
            "oneTimeProducts": [{
                "productId": cfg["pro_sku"],
                "listings": [{"languageCode": "en-US", "title": cfg["pro_title"]}],
                "purchaseOptions": [{
                    "purchaseOptionId": f"{cfg['pro_sku']}-default",
                    "state": "ACTIVE",
                    "regionalPricingAndAvailabilityConfigs": regional_configs,
                }],
            }],
        },
        "subscriptions": {"subscriptions": []},
        "tracks": {"tracks": [{
            "track": "production",
            "releases": [{
                "name": cfg["current_release"],
                "status": "completed",
                "versionCodes": cfg["current_track_versions"],
                "userFraction": None,
            }],
        }]},
        "live_reviews": [],
        "listings": {"listings": []},
    }

    metrics = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "package": cfg["package"],
        "name": cfg["name"],
        "timeline": timeline,
        "country_installs": sorted(country_counts, key=lambda x: -x[1]),
        "device_installs": sorted(device_counts, key=lambda x: -x[1]),
        "os_installs": sorted(os_counts, key=lambda x: -x[1]),
        "version_installs": sorted(version_counts, key=lambda x: -x[1]),
        "language_installs": sorted(lang_counts, key=lambda x: -x[1]),
        "crashes_timeline": crashes,
        "ratings_timeline": [],
        "reviews": reviews,
        "sales": sales,
        "earnings": earnings,
        "api": api_snapshot,
    }
    metrics["summary"] = _summary(metrics)
    return metrics


def main() -> None:
    output_dir = Path("output")
    output_dir.mkdir(parents=True, exist_ok=True)

    all_metrics: list[dict] = []
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    windows: list[int | None] = [7, 30, None]
    for cfg in DEMO_APPS:
        full = _build_app(cfg)
        full["generated_at"] = generated_at
        for w in windows:
            m = parse.filter_to_window(full, w)
            m["windows"] = windows
            m["current_window"] = w
            m["_pricing_source"] = full
            dashboard.write_dashboard(m, output_dir)
        report_md.write(full, output_dir)
        all_metrics.append(full)
        s = full["summary"]
        print(f"  {cfg['package']}: {s['active_devices_now']:,} active · "
              f"{s['total_user_installs']:,} installs · {s['paid_orders']} sales "
              f"({len(windows)} window(s))")
    dashboard.write_index(all_metrics, output_dir, generated_at)
    # Tiny banner so visitors know this is synthetic data.
    banner = output_dir / "DEMO.txt"
    banner.write_text(
        "This is a public demo with SYNTHETIC data — none of the apps, "
        "users, or sales are real.\n"
        "Source: https://github.com/milouk/play-analytics\n"
    )
    print(f"\n  index: {output_dir / 'index.html'}")


if __name__ == "__main__":
    main()
