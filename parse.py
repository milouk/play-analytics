"""Parse one app's downloaded Play Console reports into a metrics dict."""
from __future__ import annotations

import csv
import glob
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import App


def _read_csv(path: Path) -> list[dict[str, str]]:
    """Read a Play CSV, handling UTF-16 LE BOM (stats) vs UTF-8 (sales)."""
    for enc in ("utf-16", "utf-8-sig", "utf-8"):
        try:
            with path.open(encoding=enc) as f:
                return list(csv.DictReader(f))
        except (UnicodeError, UnicodeDecodeError):
            continue
    return []


def _to_int(s: str | None) -> int:
    if not s:
        return 0
    try:
        return int(s)
    except ValueError:
        try:
            return int(float(s.replace(",", "")))
        except ValueError:
            return 0


def _to_float(s: str | None) -> float:
    if not s:
        return 0.0
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return 0.0


def _glob(app_data: Path, pattern: str) -> list[Path]:
    return [Path(p) for p in sorted(glob.glob(str(app_data / pattern)))]


def _aggregate_by(
    app_data: Path, pattern: str, key_col: str, value_col: str = "Install events"
) -> Counter:
    agg: Counter = Counter()
    for p in _glob(app_data, pattern):
        for r in _read_csv(p):
            k = r.get(key_col)
            if not k:
                continue
            agg[k] += _to_int(r.get(value_col))
    return agg


def _installs_timeline(app_data: Path, pkg: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for p in _glob(app_data, f"stats/installs_{pkg}_*_overview.csv"):
        for r in _read_csv(p):
            out.append({
                "date": r.get("Date", ""),
                "device_installs": _to_int(r.get("Daily Device Installs")),
                "user_installs": _to_int(r.get("Daily User Installs")),
                "user_uninstalls": _to_int(r.get("Daily User Uninstalls")),
                "active_devices": _to_int(r.get("Active Device Installs")),
                "install_events": _to_int(r.get("Install events")),
                "uninstall_events": _to_int(r.get("Uninstall events")),
                "update_events": _to_int(r.get("Update events")),
            })
    out.sort(key=lambda d: d["date"])
    return out


def _crashes_timeline(app_data: Path, pkg: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for p in _glob(app_data, f"stats/crashes_{pkg}_*_overview.csv"):
        for r in _read_csv(p):
            out.append({
                "date": r.get("Date", ""),
                "crashes": _to_int(r.get("Daily Crashes")),
                "anrs": _to_int(r.get("Daily ANRs")),
            })
    out.sort(key=lambda d: d["date"])
    return out


def _ratings_timeline(app_data: Path, pkg: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for p in _glob(app_data, f"stats/ratings_{pkg}_*_overview.csv"):
        for r in _read_csv(p):
            out.append({
                "date": r.get("Date", ""),
                "daily_avg": _to_float(r.get("Daily Average Rating")),
                "total_avg": _to_float(r.get("Total Average Rating")),
            })
    out.sort(key=lambda d: d["date"])
    return out


def _reviews(app_data: Path, pkg: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for p in _glob(app_data, f"reviews/reviews_{pkg}_*.csv"):
        for r in _read_csv(p):
            out.append({
                "submitted_at": r.get("Review Submit Date and Time", ""),
                "updated_at": r.get("Review Last Update Date and Time", ""),
                "stars": _to_int(r.get("Star Rating")),
                "language": r.get("Reviewer Language", ""),
                "device": r.get("Device", ""),
                "version_code": r.get("App Version Code", ""),
                "version_name": r.get("App Version Name", ""),
                "title": (r.get("Review Title") or "").strip(),
                "text": (r.get("Review Text") or "").strip(),
                "reply_text": (r.get("Developer Reply Text") or "").strip(),
            })
    seen: set[tuple[str, str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for rv in out:
        key = (rv["submitted_at"], rv["device"], rv["text"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(rv)
    deduped.sort(key=lambda d: d["submitted_at"])
    return deduped


def _sales(app_data: Path, pkg: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for p in _glob(app_data, "sales/salesreport_*.csv"):
        for r in _read_csv(p):
            if r.get("Package ID") and r.get("Package ID") != pkg:
                continue
            out.append({
                "order": r.get("Order Number", ""),
                "date": r.get("Order Charged Date", ""),
                "status": r.get("Financial Status", ""),
                "device": r.get("Device Model", ""),
                "product": r.get("Product Title", ""),
                "sku": r.get("SKU ID", ""),
                "type": r.get("Product Type", ""),
                "currency": r.get("Currency of Sale", ""),
                "item_price": _to_float(r.get("Item Price")),
                "tax": _to_float(r.get("Taxes Collected")),
                "charged": _to_float(r.get("Charged Amount")),
                "country": r.get("Country of Buyer", ""),
                "city": r.get("City of Buyer", ""),
                "channel": r.get("Sales Channel", ""),
            })
    out.sort(key=lambda d: d["date"])
    return out


def _earnings(app_data: Path, pkg: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for p in _glob(app_data, "earnings/*.csv"):
        for r in _read_csv(p):
            if r.get("Package ID") != pkg:
                continue
            out.append({
                "date": r.get("Transaction Date", ""),
                "type": r.get("Transaction Type", ""),
                "description": r.get("Description", ""),
                "buyer_currency": r.get("Buyer Currency", ""),
                "buyer_amount": _to_float(r.get("Amount (Buyer Currency)")),
                "merchant_currency": r.get("Merchant Currency", ""),
                "merchant_amount": _to_float(r.get("Amount (Merchant Currency)")),
                "buyer_country": r.get("Buyer Country", ""),
                "product_id": r.get("Sku Id", ""),
            })
    return out


def _summary(m: dict[str, Any]) -> dict[str, Any]:
    timeline = m["timeline"]
    sales = m["sales"]
    reviews = m["reviews"]
    crashes = m["crashes_timeline"]
    earnings = m["earnings"]

    total_user_installs = sum(d["user_installs"] for d in timeline)
    total_user_uninstalls = sum(d["user_uninstalls"] for d in timeline)
    total_install_events = sum(d["install_events"] for d in timeline)
    total_uninstall_events = sum(d["uninstall_events"] for d in timeline)
    active_now = timeline[-1]["active_devices"] if timeline else 0
    first_day = timeline[0]["date"] if timeline else ""
    last_day = timeline[-1]["date"] if timeline else ""

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

    paying_countries: Counter = Counter(s["country"] for s in charged)
    conv = (len(charged) / total_user_installs * 100) if total_user_installs else 0.0

    return {
        "window_start": first_day,
        "window_end": last_day,
        "total_user_installs": total_user_installs,
        "total_user_uninstalls": total_user_uninstalls,
        "total_install_events": total_install_events,
        "total_uninstall_events": total_uninstall_events,
        "active_devices_now": active_now,
        "paid_orders": len(charged),
        "paid_conversion_pct": round(conv, 3),
        "revenue_by_currency": {k: round(v, 2) for k, v in revenue_by_ccy.items()},
        "earnings_net": {k: round(v, 2) for k, v in net_merchant.items()},
        "earnings_months": sorted({e["date"][-4:] for e in earnings if e["date"]}),
        "paying_countries": paying_countries.most_common(),
        "review_count": len(reviews),
        "review_avg_stars": round(avg_stars, 2),
        "review_star_dist": dict(star_dist),
        "crashes_total": sum(c["crashes"] for c in crashes),
        "anrs_total": sum(c["anrs"] for c in crashes),
    }


def parse_app(app_data: Path, app: App) -> dict[str, Any]:
    pkg = app.package
    api_path = app_data / "api" / "snapshot.json"
    api = json.loads(api_path.read_text()) if api_path.exists() else {}

    metrics: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "package": pkg,
        "name": app.name,
        "timeline": _installs_timeline(app_data, pkg),
        "country_installs": _aggregate_by(
            app_data, f"stats/installs_{pkg}_*_country.csv", "Country"
        ).most_common(),
        "device_installs": _aggregate_by(
            app_data, f"stats/installs_{pkg}_*_device.csv", "Device"
        ).most_common(),
        "os_installs": _aggregate_by(
            app_data, f"stats/installs_{pkg}_*_os_version.csv", "Android OS Version"
        ).most_common(),
        "version_installs": _aggregate_by(
            app_data, f"stats/installs_{pkg}_*_app_version.csv", "App Version"
        ).most_common(),
        "language_installs": _aggregate_by(
            app_data, f"stats/installs_{pkg}_*_language.csv", "Language"
        ).most_common(),
        "crashes_timeline": _crashes_timeline(app_data, pkg),
        "ratings_timeline": _ratings_timeline(app_data, pkg),
        "reviews": _reviews(app_data, pkg),
        "sales": _sales(app_data, pkg),
        "earnings": _earnings(app_data, pkg),
        "api": api,
    }
    metrics["summary"] = _summary(metrics)
    return metrics
