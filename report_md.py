"""Render a Markdown summary per app — for terminals, Slack, PRs."""
from __future__ import annotations

from pathlib import Path
from typing import Any


def _table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return ""
    sep = ["---"] * len(headers)
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join(sep) + " |"]
    for r in rows:
        out.append("| " + " | ".join(r) + " |")
    return "\n".join(out)


def render(metrics: dict[str, Any]) -> str:
    s = metrics["summary"]
    timeline = metrics["timeline"]

    lines: list[str] = []
    lines.append(f"# {metrics['name']} analytics report")
    lines.append("")
    lines.append(f"_Generated {metrics['generated_at']} · package `{metrics['package']}`_")
    lines.append("")
    lines.append(f"**Window:** {s['window_start']} → {s['window_end']}")
    lines.append("")

    lines.append("## Headline")
    lines.append("")
    net_earnings_str = ", ".join(f"{v:,.2f} {k}" for k, v in s["earnings_net"].items()) or "—"
    lines.append(_table(["Metric", "Value"], [
        ["Active devices (latest day)", f"**{s['active_devices_now']:,}**"],
        ["User installs (window)", f"{s['total_user_installs']:,}"],
        ["User uninstalls (window)", f"{s['total_user_uninstalls']:,}"],
        ["Install events (window)", f"{s['total_install_events']:,}"],
        ["Uninstall events (window)", f"{s['total_uninstall_events']:,}"],
        ["Paid orders", f"{s['paid_orders']:,}"],
        ["Paid conversion", f"{s['paid_conversion_pct']:.2f}%"],
        ["Net earnings (finalised)", net_earnings_str],
        ["Average rating", f"{s['review_avg_stars']} ★ ({s['review_count']} reviews)"],
        ["Crashes / ANRs (window)", f"{s['crashes_total']} / {s['anrs_total']}"],
    ]))
    lines.append("")

    if timeline:
        lines.append("## Daily timeline (last 14 days)")
        lines.append("")
        last14 = timeline[-14:]
        lines.append(_table(
            ["Date", "User installs", "Active devices", "Crashes", "ANRs"],
            [
                [
                    d["date"],
                    str(d["user_installs"]),
                    str(d["active_devices"]),
                    str(next((c["crashes"] for c in metrics["crashes_timeline"] if c["date"] == d["date"]), 0)),
                    str(next((c["anrs"] for c in metrics["crashes_timeline"] if c["date"] == d["date"]), 0)),
                ]
                for d in last14
            ],
        ))
        lines.append("")

    if metrics["country_installs"]:
        lines.append("## Top install countries (window)")
        lines.append("")
        lines.append(_table(
            ["Country", "Installs"],
            [[c, str(n)] for c, n in metrics["country_installs"][:15]],
        ))
        lines.append("")

    lines.append("## Revenue")
    lines.append("")
    if s["revenue_by_currency"]:
        lines.append(_table(
            ["Currency", "Charged (window)"],
            [[ccy, f"{amt:,.2f}"]
             for ccy, amt in sorted(s["revenue_by_currency"].items(), key=lambda kv: -kv[1])],
        ))
    else:
        lines.append("_No sales in window._")
    lines.append("")
    if s["paying_countries"]:
        lines.append("**Paying countries:** " + ", ".join(f"{c}×{n}" for c, n in s["paying_countries"]))
        lines.append("")

    lines.append("## Reviews")
    lines.append("")
    if s["review_star_dist"]:
        star_line = "  ".join(f"{k}★ ×{s['review_star_dist'].get(k, 0)}" for k in (5, 4, 3, 2, 1))
        lines.append(f"**Star distribution:** {star_line}")
        lines.append("")
    for r in sorted(metrics["reviews"], key=lambda x: x["submitted_at"], reverse=True):
        if not r["text"]:
            continue
        date = r["submitted_at"][:10]
        lines.append(f"- **{r['stars']}★** _{date} · v{r['version_code']} · {r['device']}_ — {r['text']}")
    lines.append("")
    return "\n".join(lines)


def write(metrics: dict[str, Any], output_dir: Path) -> Path:
    app_out = output_dir / metrics["package"]
    app_out.mkdir(parents=True, exist_ok=True)
    p = app_out / "report.md"
    p.write_text(render(metrics), encoding="utf-8")
    return p
