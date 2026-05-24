"""play-analytics CLI.

Reads config from env vars, fetches Play Console reports for every app
listed in $APPS, and renders per-app dashboards (multi-window) + a
top-level index.

    python main.py             # fetch + render
    python main.py --no-fetch  # reuse cached data only

Env vars:
    WINDOWS=7,30,all           # which time-window dashboards to render
                                 (default "7,30,all"). Each renders as a
                                 separate dashboard-NNd.html file with
                                 a tab strip linking them.
    SERVE=true PORT=8080       # also start an HTTP server after rendering.
    CRON_SCHEDULE='0 6 * * *'  # if set, run this script on the given cron
                                 (handled by the container entrypoint).
"""
from __future__ import annotations

import argparse
import http.server
import os
import socketserver
from datetime import datetime, timezone
from functools import partial

import config
import dashboard
import fetch
import parse
import report_md


def _parse_windows(spec: str | None) -> list[int | None]:
    """Parse '7,30,all' → [7, 30, None]. None means 'all time'."""
    if not spec:
        return [7, 30, None]
    out: list[int | None] = []
    for token in spec.split(","):
        t = token.strip().lower()
        if not t:
            continue
        if t in ("all", "lifetime", "*"):
            out.append(None)
        else:
            try:
                n = int(t.rstrip("d"))
                if n > 0:
                    out.append(n)
            except ValueError:
                pass
    return out or [None]


def main() -> int:
    ap = argparse.ArgumentParser(prog="play-analytics", description=__doc__)
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--serve", action="store_true")
    args = ap.parse_args()

    cfg = config.load()
    windows = _parse_windows(os.environ.get("WINDOWS"))

    if args.no_fetch:
        print("[main] skipping fetch (--no-fetch)")
    else:
        fetch.run(cfg)

    all_summaries: list[dict] = []
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

    for app in cfg.apps:
        app_data = cfg.data_dir / app.package
        if not app_data.exists():
            print(f"[main] no data for {app.package} — skipping")
            continue
        full_metrics = parse.parse_app(app_data, app)
        full_metrics["generated_at"] = generated_at

        per_window: list[dict] = []
        for w in windows:
            m = parse.filter_to_window(full_metrics, w)
            m["windows"] = windows
            m["current_window"] = w
            # Pricing decisions look at lifetime signal, not the visible
            # window — a buyer from 6 months ago is still a buyer.
            m["_pricing_source"] = full_metrics
            per_window.append(m)

        # Render each window variant of the HTML dashboard.
        for m in per_window:
            dashboard.write_dashboard(m, cfg.output_dir)
        # Markdown summary uses the broadest window only (most useful for PRs).
        report_md.write(per_window[-1], cfg.output_dir)

        # Index uses the broadest window for headline KPIs.
        all_summaries.append(per_window[-1])
        s = per_window[-1]["summary"]
        print(
            f"  {app.package}: {s['active_devices_now']:,} active · "
            f"{s['total_user_installs']:,} installs · "
            f"{s['paid_orders']} sales · "
            f"{s['review_avg_stars']}★  ({len(per_window)} window(s) rendered)"
        )

    if all_summaries:
        dashboard.write_index(all_summaries, cfg.output_dir, generated_at)
        print(f"\n  index: {cfg.output_dir / 'index.html'}")

    if args.serve or os.environ.get("SERVE") == "true":
        port = int(os.environ.get("PORT", "8080"))
        handler = partial(http.server.SimpleHTTPRequestHandler,
                          directory=str(cfg.output_dir))
        with socketserver.TCPServer(("0.0.0.0", port), handler) as httpd:
            print(f"\n[serve] http://0.0.0.0:{port}/  (Ctrl-C to stop)")
            try:
                httpd.serve_forever()
            except KeyboardInterrupt:
                pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
