"""Apply PPP-tier-based price changes to a one-time product on Google Play.

Default is dry-run: prints every planned change side-by-side and refuses to
write. Pass ``--apply`` to send the PATCH (single API call, atomic across
all changes), then refetch to verify each region.

    python apply_pricing.py <package> <productId>            # dry-run
    python apply_pricing.py <package> <productId> --apply    # commit
    python apply_pricing.py <package> <productId> --only TR,EG,NG --apply

Requires the same env-var credentials as ``main.py``
(GOOGLE_APPLICATION_CREDENTIALS or _JSON).
"""
from __future__ import annotations

import argparse
import sys
from typing import Iterable

from google.oauth2 import service_account
from googleapiclient.discovery import build

import config
import parse
import pricing


def _build_pub(cfg: config.Config):
    creds = service_account.Credentials.from_service_account_file(
        str(cfg.credentials_path),
        scopes=["https://www.googleapis.com/auth/androidpublisher"],
    )
    return build("androidpublisher", "v3", credentials=creds, cache_discovery=False)


def _filter_recs(recs: list[pricing.Recommendation], only: Iterable[str] | None) -> list[pricing.Recommendation]:
    actionable = [r for r in recs if r.verdict in ("cut", "raise") and r.suggested_price]
    if only:
        wanted = {c.strip().upper() for c in only}
        actionable = [r for r in actionable if r.region in wanted]
    return actionable


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("package")
    ap.add_argument("product_id")
    ap.add_argument("--only", help="comma-separated region codes to limit the plan")
    ap.add_argument("--apply", action="store_true", help="actually send the PATCH")
    args = ap.parse_args()

    cfg = config.load()
    app = next((a for a in cfg.apps if a.package == args.package), None)
    if app is None:
        sys.exit(f"{args.package} not in APPS env var")

    # Re-parse cached metrics for install/buyer signal.
    app_data = cfg.data_dir / app.package
    if not app_data.exists():
        sys.exit(f"no cached data for {app.package} — run `python main.py` first")
    metrics = parse.parse_app(app_data, app)

    pub = _build_pub(cfg)
    print(f"Fetching {app.package}/{args.product_id}…")
    product = pub.monetization().onetimeproducts().get(
        packageName=app.package, productId=args.product_id
    ).execute()

    country_installs = dict(metrics["country_installs"])
    buyers: dict[str, int] = {}
    for s in metrics["sales"]:
        if s["status"] == "Charged" and s["country"]:
            buyers[s["country"]] = buyers.get(s["country"], 0) + 1

    recs, anchor = pricing.recommend_for_product(product, country_installs, buyers)
    plan = _filter_recs(recs, args.only.split(",") if args.only else None)

    print(f"  anchor (US): ${anchor:,.2f}  ·  {len(plan)} change(s) planned")
    print()
    print(f"  {'Region':6s}  {'Installs':>8s}  {'Buyers':>6s}  "
          f"{'Current':>16s}  {'~USD':>7s}  →  {'Suggested':>16s}  {'~USD':>7s}")
    print(f"  {'-'*6}  {'-'*8}  {'-'*6}  {'-'*16}  {'-'*7}     {'-'*16}  {'-'*7}")
    for r in plan:
        cur = pricing.fmt_local_price(r.current_price)
        sug = pricing.fmt_local_price(r.suggested_price) if r.suggested_price else "?"
        cur_usd = f"${r.current_usd:,.2f}" if r.current_usd is not None else "?"
        sug_usd = f"${r.suggested_usd:,.2f}" if r.suggested_usd is not None else "?"
        print(f"  {r.region:6s}  {r.installs:>8}  {r.buyers:>6}  "
              f"{cur:>16s}  {cur_usd:>7s}  →  {sug:>16s}  {sug_usd:>7s}")
    print()

    if not plan:
        print("Nothing to do.")
        return 0

    held = [r for r in recs if r.verdict == "hold"]
    if held:
        print(f"  (also: {len(held)} region(s) marked 'hold' — over target but have "
              f"buyers; NOT included in this plan: {', '.join(r.region for r in held)})")
        print()

    if not args.apply:
        print("[dry-run] no write made. Pass --apply to send the PATCH.")
        return 0

    region_to_price = {r.region: r.suggested_price for r in plan if r.suggested_price}
    print(f"PATCHing {len(region_to_price)} region(s)…")
    try:
        result = pricing.apply_changes(pub, app.package, args.product_id, region_to_price)
    except Exception as e:
        print(f"PATCH failed: {type(e).__name__}: {e}")
        return 1
    ok_count = sum(1 for v in result.values() if v["ok"])
    print(f"  {ok_count}/{len(result)} verified")
    failures = [(rg, v["got"]) for rg, v in result.items() if not v["ok"]]
    for rg, got in failures:
        print(f"  ! {rg}: did not take — got {pricing.fmt_local_price(got)}")
    return 0 if ok_count == len(result) else 1


if __name__ == "__main__":
    raise SystemExit(main())
