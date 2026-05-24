"""play-analytics CLI.

Reads config from env vars, fetches Play Console reports for every app
listed in $APPS, and renders per-app dashboards + a top-level index.

    python main.py             # fetch + render
    python main.py --no-fetch  # reuse cached data only
    python main.py --serve     # also start http.server on $PORT (default 8080)
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


def main() -> int:
    ap = argparse.ArgumentParser(prog="play-analytics", description=__doc__)
    ap.add_argument("--no-fetch", action="store_true", help="reuse cached data, skip download")
    ap.add_argument("--serve", action="store_true",
                    help="after rendering, serve OUTPUT_DIR on $PORT (default 8080)")
    args = ap.parse_args()

    cfg = config.load()

    if args.no_fetch:
        print("[main] skipping fetch (--no-fetch)")
    else:
        fetch.run(cfg)

    all_metrics = []
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    for app in cfg.apps:
        app_data = cfg.data_dir / app.package
        if not app_data.exists():
            print(f"[main] no data for {app.package} — skipping")
            continue
        metrics = parse.parse_app(app_data, app)
        metrics["generated_at"] = generated_at
        dash_path = dashboard.write_dashboard(metrics, cfg.output_dir)
        md_path = report_md.write(metrics, cfg.output_dir)
        all_metrics.append(metrics)
        s = metrics["summary"]
        print(
            f"  {app.package}: {s['active_devices_now']:,} active · "
            f"{s['total_user_installs']:,} installs · "
            f"{s['paid_orders']} sales · "
            f"{s['review_avg_stars']}★"
        )
        print(f"    -> {dash_path}")
        print(f"    -> {md_path}")

    if all_metrics:
        index = dashboard.write_index(all_metrics, cfg.output_dir, generated_at)
        print(f"\n  index: {index}")

    if args.serve or os.environ.get("SERVE") == "true":
        port = int(os.environ.get("PORT", "8080"))
        handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(cfg.output_dir))
        with socketserver.TCPServer(("0.0.0.0", port), handler) as httpd:
            print(f"\n[serve] http://0.0.0.0:{port}/  (Ctrl-C to stop)")
            try:
                httpd.serve_forever()
            except KeyboardInterrupt:
                pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
