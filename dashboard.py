"""Render per-app HTML dashboards + a top-level multi-app index."""
from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

# -- minimal country reference ---------------------------------------------- #

COUNTRY_NAMES = {
    "US":"United States","GB":"United Kingdom","DE":"Germany","FR":"France",
    "IT":"Italy","ES":"Spain","PT":"Portugal","NL":"Netherlands","PL":"Poland",
    "BE":"Belgium","AT":"Austria","CH":"Switzerland","SE":"Sweden","NO":"Norway",
    "DK":"Denmark","FI":"Finland","IE":"Ireland","GR":"Greece","CY":"Cyprus",
    "TR":"Turkey","RU":"Russia","UA":"Ukraine","HU":"Hungary","CZ":"Czechia",
    "SK":"Slovakia","RO":"Romania","BG":"Bulgaria","HR":"Croatia","SI":"Slovenia",
    "RS":"Serbia","BA":"Bosnia","MK":"N. Macedonia","AL":"Albania","ME":"Montenegro",
    "LT":"Lithuania","LV":"Latvia","EE":"Estonia",
    "IN":"India","PK":"Pakistan","BD":"Bangladesh","LK":"Sri Lanka","NP":"Nepal",
    "CN":"China","JP":"Japan","KR":"South Korea","TW":"Taiwan","HK":"Hong Kong",
    "TH":"Thailand","VN":"Vietnam","ID":"Indonesia","MY":"Malaysia","SG":"Singapore",
    "PH":"Philippines","MM":"Myanmar","KH":"Cambodia",
    "AU":"Australia","NZ":"New Zealand",
    "BR":"Brazil","AR":"Argentina","MX":"Mexico","CL":"Chile","CO":"Colombia",
    "PE":"Peru","VE":"Venezuela","EC":"Ecuador","UY":"Uruguay","PY":"Paraguay",
    "BO":"Bolivia","DO":"Dominican Rep.","GT":"Guatemala","HN":"Honduras",
    "SV":"El Salvador","NI":"Nicaragua","CR":"Costa Rica","PA":"Panama",
    "CA":"Canada",
    "EG":"Egypt","MA":"Morocco","DZ":"Algeria","TN":"Tunisia",
    "NG":"Nigeria","KE":"Kenya","GH":"Ghana","ZA":"South Africa","ET":"Ethiopia",
    "UG":"Uganda","TZ":"Tanzania","RW":"Rwanda","CI":"Côte d'Ivoire",
    "SN":"Senegal","CM":"Cameroon","AO":"Angola","ZM":"Zambia","ZW":"Zimbabwe",
    "SA":"Saudi Arabia","AE":"U.A.E.","QA":"Qatar","KW":"Kuwait","BH":"Bahrain",
    "OM":"Oman","JO":"Jordan","LB":"Lebanon","IL":"Israel",
    "KZ":"Kazakhstan","UZ":"Uzbekistan","KG":"Kyrgyzstan",
    "AM":"Armenia","AZ":"Azerbaijan","GE":"Georgia",
}

COUNTRY_FLAGS = {
    c: "".join(chr(0x1F1E6 + ord(ch) - ord("A")) for ch in c)
    for c in COUNTRY_NAMES
}


def _country_label(code: str) -> str:
    if not code:
        return "—"
    return f"{COUNTRY_FLAGS.get(code,'')} {COUNTRY_NAMES.get(code, code)}".strip()


def _fmt(n: int | float) -> str:
    if isinstance(n, float):
        return f"{n:,.2f}"
    return f"{n:,}"


def _ccy_pill(amount: float, ccy: str) -> str:
    sym = {"EUR":"€","USD":"$","GBP":"£","BRL":"R$","KRW":"₩","CZK":"Kč",
           "CAD":"C$","AUD":"A$","JPY":"¥","INR":"₹","TRY":"₺","MXN":"M$"}.get(ccy, "")
    if ccy == "KRW":
        return f"{sym}{amount:,.0f}"
    if sym:
        return f"{sym}{amount:,.2f}"
    return f"{amount:,.2f} {ccy}"


# -- per-app dashboard ------------------------------------------------------ #

DASHBOARD_TMPL = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js"></script>
<style>{css}</style>
</head>
<body>

<header>
  <div>
    <a href="../index.html" class="back">← all apps</a>
    <h1>{title}<span class="pkg">{package}</span></h1>
  </div>
  <div class="meta">Window <strong>{window_start} → {window_end}</strong> · generated {generated_at}</div>
</header>

<div class="grid kpis">
  <div class="kpi accent"><div class="label">Active devices</div><div class="value">{active_now}</div><div class="sub">most recent day</div></div>
  <div class="kpi"><div class="label">User installs</div><div class="value">{user_installs}</div><div class="sub">{install_events} install events</div></div>
  <div class="kpi"><div class="label">Net retention</div><div class="value">{retention_pct}%</div><div class="sub">{uninstall_events} uninstall events</div></div>
  <div class="kpi good"><div class="label">Paid orders</div><div class="value">{paid_orders}</div><div class="sub">{paid_conv}% conversion</div></div>
  <div class="kpi accent"><div class="label">Net earnings</div><div class="value">{net_earnings}</div><div class="sub">finalised: {earnings_months}</div></div>
  <div class="kpi"><div class="label">Avg rating</div><div class="value">{avg_stars} ★</div><div class="sub">{review_count} reviews</div></div>
  <div class="kpi warn"><div class="label">Crashes / ANRs</div><div class="value">{crashes} / {anrs}</div><div class="sub">across window</div></div>
</div>

<h2>Growth</h2>
<div class="card"><div class="h"><h3>Daily installs &amp; active devices</h3><span class="sub">installs (bars) · active (line)</span></div><div class="chart-wrap tall"><canvas id="cInstalls"></canvas></div></div>

<h2>Geography &amp; audience</h2>
<div class="row row-2">
  <div class="card"><div class="h"><h3>Installs by country</h3><span class="sub">top 15</span></div><div class="chart-wrap tall"><canvas id="cCountry"></canvas></div></div>
  <div class="card"><div class="h"><h3>Languages</h3><span class="sub">top 10</span></div><div class="chart-wrap tall"><canvas id="cLang"></canvas></div></div>
</div>
<div class="row row-3" style="margin-top:16px">
  <div class="card"><div class="h"><h3>Devices</h3><span class="sub">top 12</span></div><div class="chart-wrap"><canvas id="cDevice"></canvas></div></div>
  <div class="card"><div class="h"><h3>Android OS version</h3><span class="sub">install share</span></div><div class="chart-wrap"><canvas id="cOs"></canvas></div></div>
  <div class="card"><div class="h"><h3>App version</h3><span class="sub">install share</span></div><div class="chart-wrap"><canvas id="cVer"></canvas></div></div>
</div>

<h2>Quality</h2>
<div class="row row-2">
  <div class="card"><div class="h"><h3>Crashes &amp; ANRs</h3><span class="sub">daily</span></div><div class="chart-wrap"><canvas id="cCrash"></canvas></div></div>
  <div class="card"><div class="h"><h3>Rating distribution</h3><span class="sub">from review CSVs</span></div><div class="chart-wrap"><canvas id="cStars"></canvas></div></div>
</div>

<h2>Monetisation</h2>
<div class="row row-2">
  <div class="card"><div class="h"><h3>Sales transactions</h3><span class="sub">{paid_orders} charged</span></div><div class="scroll"><table><thead><tr><th>Date</th><th>Country</th><th>Device</th><th class="num">Price</th><th class="num">Tax</th><th class="num">Charged</th><th>CCY</th></tr></thead><tbody>{sales_rows}</tbody></table></div></div>
  <div class="card"><div class="h"><h3>Revenue &amp; paying countries</h3><span class="sub">window total</span></div><div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:14px">{revenue_pills}</div><table><thead><tr><th>Country</th><th class="num">Buyers</th></tr></thead><tbody>{paying_rows}</tbody></table></div>
</div>

<h2>Voice of customer</h2>
<div class="card"><div class="h"><h3>Reviews</h3><span class="sub">{review_count} total · avg {avg_stars}★</span></div><div>{review_blocks}</div></div>

<h2>Catalog</h2>
<div class="row row-2">
  <div class="card"><div class="h"><h3>In-app products</h3><span class="sub">monetization API</span></div><div class="scroll"><table><thead><tr><th>Product ID</th><th>Title</th><th>State</th><th>Type</th></tr></thead><tbody>{catalog_rows}</tbody></table></div></div>
  <div class="card"><div class="h"><h3>Release tracks</h3><span class="sub">live edit snapshot</span></div><div class="scroll"><table><thead><tr><th>Track</th><th>Release</th><th>Versions</th><th>Status</th><th>Rollout</th></tr></thead><tbody>{track_rows}</tbody></table></div></div>
</div>

<footer>data via Play Console reports bucket + Android Publisher API · <a href="https://github.com/milouk/play-analytics">milouk/play-analytics</a></footer>

<script>
const data = {data_json};
const TXT='#e6eaf3', MUTED='#8b94a7', GRID='#232a3a';
Chart.defaults.color=MUTED; Chart.defaults.borderColor=GRID;
Chart.defaults.font.family='-apple-system, BlinkMacSystemFont, Inter, Segoe UI, system-ui, sans-serif';

new Chart(document.getElementById('cInstalls'), {{
  data: {{ labels: data.timeline.map(d=>d.date), datasets: [
    {{ type:'bar', label:'User installs', data: data.timeline.map(d=>d.user_installs), backgroundColor:'rgba(122,162,255,0.55)', borderRadius:3 }},
    {{ type:'line', label:'Active devices', data: data.timeline.map(d=>d.active_devices), borderColor:'#b388ff', backgroundColor:'rgba(179,136,255,0.15)', tension:0.3, fill:true, pointRadius:0 }},
  ] }},
  options: {{ responsive:true, maintainAspectRatio:false, scales: {{ y: {{ beginAtZero:true }}, x: {{ grid: {{ display:false }}, ticks: {{ maxRotation:0, autoSkip:true, maxTicksLimit:12 }} }} }}, plugins: {{ legend: {{ position:'top', labels: {{ color: TXT }} }} }} }}
}});

function hBar(id, items, color, max) {{
  const top = items.slice(0, max||10);
  new Chart(document.getElementById(id), {{ type:'bar',
    data: {{ labels: top.map(x=>x.label), datasets:[{{ data: top.map(x=>x.value), backgroundColor: color, borderRadius:3 }}] }},
    options: {{ indexAxis:'y', responsive:true, maintainAspectRatio:false, plugins:{{legend:{{display:false}}}}, scales: {{ x:{{beginAtZero:true}}, y:{{grid:{{display:false}}}} }} }}
  }});
}}
hBar('cCountry', data.country_installs, 'rgba(122,162,255,0.7)', 15);
hBar('cLang',    data.language_installs,'rgba(179,136,255,0.65)', 10);
hBar('cDevice',  data.device_installs,  'rgba(74,222,128,0.55)',  12);

const palette = ['#7aa2ff','#b388ff','#4ade80','#facc15','#f87171','#22d3ee','#f472b6','#a3e635','#fb923c','#94a3b8','#818cf8','#34d399'];
function doughnut(id, items) {{
  new Chart(document.getElementById(id), {{ type:'doughnut',
    data: {{ labels: items.map(x=>x.label), datasets:[{{ data: items.map(x=>x.value), backgroundColor: palette, borderColor:'#0b0d12', borderWidth:2 }}] }},
    options: {{ responsive:true, maintainAspectRatio:false, cutout:'58%', plugins: {{ legend: {{ position:'right', labels: {{ color: TXT, boxWidth:10 }} }} }} }}
  }});
}}
doughnut('cOs',  data.os_installs);
doughnut('cVer', data.version_installs);

new Chart(document.getElementById('cCrash'), {{
  data: {{ labels: data.crashes_timeline.map(d=>d.date), datasets: [
    {{ type:'bar', label:'Crashes', data: data.crashes_timeline.map(d=>d.crashes), backgroundColor:'#f87171', borderRadius:3 }},
    {{ type:'bar', label:'ANRs',    data: data.crashes_timeline.map(d=>d.anrs),    backgroundColor:'#fbbf24', borderRadius:3 }},
  ] }},
  options: {{ responsive:true, maintainAspectRatio:false, scales: {{ y: {{ beginAtZero:true, ticks: {{ stepSize:1 }} }}, x: {{ grid: {{ display:false }} }} }}, plugins: {{ legend: {{ position:'top', labels: {{ color: TXT }} }} }} }}
}});

new Chart(document.getElementById('cStars'), {{
  type:'bar',
  data: {{ labels:['1★','2★','3★','4★','5★'], datasets:[{{ data:[data.star_dist['1']||0,data.star_dist['2']||0,data.star_dist['3']||0,data.star_dist['4']||0,data.star_dist['5']||0], backgroundColor:['#f87171','#fb923c','#fbbf24','#60a5fa','#4ade80'], borderRadius:3 }}] }},
  options: {{ responsive:true, maintainAspectRatio:false, plugins:{{legend:{{display:false}}}}, scales: {{ y: {{ beginAtZero:true, ticks: {{ stepSize:1 }} }}, x: {{ grid: {{ display:false }} }} }} }}
}});
</script>
</body>
</html>
"""


# -- top-level index (multi-app) ------------------------------------------- #

INDEX_TMPL = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Play Analytics — dashboards</title>
<style>{css}</style>
</head>
<body>
<header>
  <div><h1>Play Analytics</h1></div>
  <div class="meta">{n_apps} app(s) · generated {generated_at}</div>
</header>

<div class="grid app-cards">
  {app_cards}
</div>

<footer>data via Play Console reports bucket + Android Publisher API · <a href="https://github.com/milouk/play-analytics">milouk/play-analytics</a></footer>
</body>
</html>
"""

APP_CARD_TMPL = """
<a class="app-card" href="{slug}/dashboard.html">
  <div class="app-card-head"><h3>{name}</h3><span class="pkg">{package}</span></div>
  <div class="app-kpis">
    <div><span class="lbl">Active</span><span class="val accent">{active}</span></div>
    <div><span class="lbl">Installs</span><span class="val">{installs}</span></div>
    <div><span class="lbl">Orders</span><span class="val good">{orders}</span></div>
    <div><span class="lbl">Rating</span><span class="val">{rating}★</span></div>
  </div>
  <div class="app-card-sub">{window_start} → {window_end}</div>
</a>
"""

# -- shared CSS ------------------------------------------------------------ #

CSS = """
:root{--bg:#0b0d12;--panel:#121620;--panel-2:#181d29;--border:#232a3a;--text:#e6eaf3;--muted:#8b94a7;--accent:#7aa2ff;--accent-2:#b388ff;--good:#4ade80;--bad:#f87171;--warn:#fbbf24;--gold:#facc15;}
*{box-sizing:border-box}
html,body{margin:0;padding:0;background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,Inter,Segoe UI,system-ui,sans-serif;-webkit-font-smoothing:antialiased}
body{padding:28px max(20px,calc((100% - 1280px)/2))}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
header{display:flex;align-items:baseline;justify-content:space-between;padding-bottom:8px;border-bottom:1px solid var(--border);margin-bottom:28px;flex-wrap:wrap;gap:12px}
header .back{font-size:13px;color:var(--muted);display:block;margin-bottom:6px}
header h1{margin:0;font-size:24px;font-weight:700;letter-spacing:-0.01em}
header h1 .pkg{color:var(--muted);font-weight:400;font-size:14px;margin-left:10px}
header .meta{color:var(--muted);font-size:13px}
h2{font-size:13px;text-transform:uppercase;letter-spacing:0.08em;color:var(--muted);margin:36px 0 14px;font-weight:600}
.grid{display:grid;gap:16px}
.kpis{grid-template-columns:repeat(auto-fit,minmax(180px,1fr));margin-bottom:8px}
.kpi{background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:16px 18px}
.kpi .label{font-size:11px;text-transform:uppercase;letter-spacing:0.07em;color:var(--muted)}
.kpi .value{font-size:28px;font-weight:700;margin-top:6px;letter-spacing:-0.02em}
.kpi .sub{font-size:12px;color:var(--muted);margin-top:4px}
.kpi.good .value{color:var(--good)} .kpi.warn .value{color:var(--warn)} .kpi.accent .value{color:var(--accent)}
.row{display:grid;gap:16px}.row-2{grid-template-columns:1fr 1fr}.row-3{grid-template-columns:2fr 1fr 1fr}
@media (max-width:880px){.row-2,.row-3{grid-template-columns:1fr}}
.card{background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:18px}
.card .h{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:12px}
.card .h h3{margin:0;font-size:14px;font-weight:600}
.card .h .sub{color:var(--muted);font-size:12px}
.chart-wrap{position:relative;height:280px}.chart-wrap.tall{height:360px}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--border)}
th{font-weight:600;color:var(--muted);text-transform:uppercase;font-size:11px;letter-spacing:0.05em}
tr:last-child td{border-bottom:none}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
.scroll{max-height:360px;overflow-y:auto}
.review{border-left:3px solid var(--border);padding:10px 14px;margin-bottom:12px;background:var(--panel-2);border-radius:0 8px 8px 0}
.review.r5{border-color:var(--good)}.review.r4{border-color:#60a5fa}.review.r3{border-color:var(--warn)}
.review.r2,.review.r1{border-color:var(--bad)}
.review .meta{font-size:12px;color:var(--muted);display:flex;gap:10px;flex-wrap:wrap;margin-bottom:6px}
.review .stars{color:var(--gold);letter-spacing:1px}
.review .text{font-size:14px;line-height:1.5;color:var(--text)}
.review .empty{font-style:italic;color:var(--muted);font-size:13px}
.pill{display:inline-block;background:var(--panel-2);border:1px solid var(--border);border-radius:999px;padding:2px 9px;font-size:11px;color:var(--muted)}
footer{margin-top:50px;padding-top:16px;border-top:1px solid var(--border);color:var(--muted);font-size:12px;text-align:center}

.app-cards{grid-template-columns:repeat(auto-fit,minmax(280px,1fr))}
.app-card{display:block;background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:18px 20px;color:var(--text);text-decoration:none;transition:border-color .15s,transform .15s}
.app-card:hover{border-color:var(--accent);text-decoration:none;transform:translateY(-2px)}
.app-card-head{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:14px}
.app-card-head h3{margin:0;font-size:17px;font-weight:600}
.app-card-head .pkg{color:var(--muted);font-size:11px}
.app-kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:12px}
.app-kpis div{display:flex;flex-direction:column;gap:2px}
.app-kpis .lbl{font-size:10px;text-transform:uppercase;color:var(--muted);letter-spacing:0.05em}
.app-kpis .val{font-size:18px;font-weight:700;letter-spacing:-0.01em}
.app-kpis .val.accent{color:var(--accent)} .app-kpis .val.good{color:var(--good)}
.app-card-sub{font-size:11px;color:var(--muted)}
"""


# -- renderers ------------------------------------------------------------- #


def _sales_rows(sales: list[dict[str, Any]]) -> str:
    rows = [
        "<tr>"
        f"<td>{html.escape(s['date'])}</td>"
        f"<td>{html.escape(_country_label(s['country']))}</td>"
        f"<td>{html.escape(s['device'])}</td>"
        f"<td class='num'>{_fmt(s['item_price'])}</td>"
        f"<td class='num'>{_fmt(s['tax'])}</td>"
        f"<td class='num'>{_fmt(s['charged'])}</td>"
        f"<td>{html.escape(s['currency'])}</td>"
        "</tr>"
        for s in sorted(sales, key=lambda x: x["date"], reverse=True)
        if s["status"] == "Charged"
    ]
    return "\n".join(rows) or "<tr><td colspan='7' style='color:var(--muted)'>No sales yet.</td></tr>"


def _revenue_pills(revenue: dict[str, float]) -> str:
    if not revenue:
        return "<span class='pill'>No revenue yet</span>"
    return "".join(
        f"<span class='pill'>{html.escape(_ccy_pill(amt, ccy))}</span>"
        for ccy, amt in sorted(revenue.items(), key=lambda kv: -kv[1])
    )


def _paying_rows(pairs: list[tuple[str, int]]) -> str:
    if not pairs:
        return "<tr><td colspan='2' style='color:var(--muted)'>None</td></tr>"
    return "\n".join(
        f"<tr><td>{html.escape(_country_label(c))}</td><td class='num'>{n}</td></tr>"
        for c, n in pairs
    )


def _review_blocks(reviews: list[dict[str, Any]]) -> str:
    if not reviews:
        return "<p style='color:var(--muted)'>No reviews yet.</p>"
    blocks: list[str] = []
    for r in sorted(reviews, key=lambda x: x["submitted_at"], reverse=True):
        stars = max(1, min(5, r["stars"] or 1))
        star_str = "★" * stars + "☆" * (5 - stars)
        text_html = (
            f"<div class='text'>{html.escape(r['text'])}</div>"
            if r["text"] else "<div class='empty'>(no text)</div>"
        )
        title_html = (
            f"<div class='text' style='font-weight:600'>{html.escape(r['title'])}</div>"
            if r["title"] else ""
        )
        reply_html = ""
        if r.get("reply_text"):
            reply_html = (
                "<div class='text' style='margin-top:8px;color:var(--muted);"
                "font-size:13px;border-left:2px solid var(--border);padding-left:10px'>"
                f"<strong>Reply:</strong> {html.escape(r['reply_text'])}</div>"
            )
        blocks.append(
            f"<div class='review r{stars}'><div class='meta'>"
            f"<span class='stars'>{star_str}</span>"
            f"<span>{html.escape(r['submitted_at'][:10])}</span>"
            f"<span>{html.escape(r['language'])}</span>"
            f"<span>{html.escape(r['device'])}</span>"
            f"<span>v{html.escape(r['version_code'])} ({html.escape(r['version_name'])})</span>"
            f"</div>{title_html}{text_html}{reply_html}</div>"
        )
    return "\n".join(blocks)


def _catalog_rows(api: dict[str, Any]) -> str:
    one = (api.get("onetime_products") or {}).get("oneTimeProducts") or []
    subs = (api.get("subscriptions") or {}).get("subscriptions") or []
    rows: list[str] = []
    for p in one:
        title = (p.get("listings") or [{}])[0].get("title", "")
        state = (p.get("purchaseOptions") or [{}])[0].get("state", "?")
        rows.append(
            f"<tr><td>{html.escape(p.get('productId',''))}</td>"
            f"<td>{html.escape(title)}</td><td>{html.escape(state)}</td>"
            "<td>one-time</td></tr>"
        )
    for s in subs:
        title = (s.get("listings") or [{}])[0].get("title", "")
        state = (s.get("basePlans") or [{}])[0].get("state", "?")
        rows.append(
            f"<tr><td>{html.escape(s.get('productId',''))}</td>"
            f"<td>{html.escape(title)}</td><td>{html.escape(state)}</td>"
            "<td>subscription</td></tr>"
        )
    return "\n".join(rows) or "<tr><td colspan='4' style='color:var(--muted)'>No products.</td></tr>"


def _track_rows(api: dict[str, Any]) -> str:
    tracks = (api.get("tracks") or {}).get("tracks") or []
    rows: list[str] = []
    for t in tracks:
        for rel in t.get("releases", []):
            rows.append(
                "<tr>"
                f"<td>{html.escape(t.get('track',''))}</td>"
                f"<td>{html.escape(rel.get('name','') or '')}</td>"
                f"<td>{html.escape(','.join(rel.get('versionCodes') or []))}</td>"
                f"<td>{html.escape(rel.get('status','') or '')}</td>"
                f"<td>{html.escape(str(rel.get('userFraction') or '100%'))}</td>"
                "</tr>"
            )
    return "\n".join(rows) or "<tr><td colspan='5' style='color:var(--muted)'>No tracks.</td></tr>"


def _slugify(package: str) -> str:
    return package


def render_dashboard(metrics: dict[str, Any]) -> str:
    s = metrics["summary"]

    def items(pairs, n=None, country=False, prefix=""):
        out = []
        for label, value in pairs:
            if not value:
                continue
            lbl = _country_label(label) if country else f"{prefix}{label}"
            out.append({"label": lbl, "value": value})
        return out[:n] if n else out

    js_data = {
        "timeline": metrics["timeline"],
        "country_installs": items(metrics["country_installs"], 15, country=True),
        "device_installs": items(metrics["device_installs"], 12),
        "os_installs": items(
            [(f"API {k}" if k.isdigit() else k, v) for k, v in metrics["os_installs"]],
            12,
        ),
        "version_installs": items(
            [(f"v{k}", v) for k, v in metrics["version_installs"]], 12
        ),
        "language_installs": items(metrics["language_installs"], 10),
        "crashes_timeline": metrics["crashes_timeline"],
        "star_dist": {str(k): v for k, v in s["review_star_dist"].items()},
    }

    retention = (
        f"{(1 - s['total_uninstall_events'] / s['total_install_events']) * 100:.0f}"
        if s["total_install_events"] else "—"
    )
    net_earnings = (
        ", ".join(_ccy_pill(v, k) for k, v in s["earnings_net"].items())
        or "—"
    )

    return DASHBOARD_TMPL.format(
        css=CSS,
        title=html.escape(metrics["name"]),
        package=html.escape(metrics["package"]),
        generated_at=html.escape(metrics["generated_at"]),
        window_start=html.escape(s["window_start"]),
        window_end=html.escape(s["window_end"]),
        active_now=_fmt(s["active_devices_now"]),
        user_installs=_fmt(s["total_user_installs"]),
        install_events=_fmt(s["total_install_events"]),
        retention_pct=retention,
        uninstall_events=_fmt(s["total_uninstall_events"]),
        paid_orders=_fmt(s["paid_orders"]),
        paid_conv=f"{s['paid_conversion_pct']:.2f}",
        net_earnings=net_earnings,
        earnings_months=", ".join(s["earnings_months"]) or "—",
        avg_stars=s["review_avg_stars"],
        review_count=_fmt(s["review_count"]),
        crashes=_fmt(s["crashes_total"]),
        anrs=_fmt(s["anrs_total"]),
        sales_rows=_sales_rows(metrics["sales"]),
        revenue_pills=_revenue_pills(s["revenue_by_currency"]),
        paying_rows=_paying_rows(s["paying_countries"]),
        review_blocks=_review_blocks(metrics["reviews"]),
        catalog_rows=_catalog_rows(metrics["api"]),
        track_rows=_track_rows(metrics["api"]),
        data_json=json.dumps(js_data),
    )


def render_index(all_metrics: list[dict[str, Any]], generated_at: str) -> str:
    cards = []
    for m in all_metrics:
        s = m["summary"]
        cards.append(APP_CARD_TMPL.format(
            slug=_slugify(m["package"]),
            name=html.escape(m["name"]),
            package=html.escape(m["package"]),
            active=_fmt(s["active_devices_now"]),
            installs=_fmt(s["total_user_installs"]),
            orders=_fmt(s["paid_orders"]),
            rating=s["review_avg_stars"],
            window_start=html.escape(s["window_start"]),
            window_end=html.escape(s["window_end"]),
        ))
    return INDEX_TMPL.format(
        css=CSS,
        n_apps=len(all_metrics),
        generated_at=html.escape(generated_at),
        app_cards="\n".join(cards),
    )


def write_dashboard(metrics: dict[str, Any], output_dir: Path) -> Path:
    app_out = output_dir / _slugify(metrics["package"])
    app_out.mkdir(parents=True, exist_ok=True)
    p = app_out / "dashboard.html"
    p.write_text(render_dashboard(metrics), encoding="utf-8")
    return p


def write_index(all_metrics: list[dict[str, Any]], output_dir: Path, generated_at: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    p = output_dir / "index.html"
    p.write_text(render_index(all_metrics, generated_at), encoding="utf-8")
    return p
