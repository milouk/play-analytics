"""Mirror one app's one-time-product regional price list onto another.

Reads the SOURCE product's per-region prices from Google Play and writes the
same prices onto the TARGET product, region by region (matching currency). Use
it to clone a tuned PPP price list (e.g. AuraDisplay `pro_lifetime`, with its
20-region cuts + eurozone/US anchor) onto a sibling app (Tessera `pro_lifetime`)
so both ship the identical per-country list.

Default is dry-run: prints the full target-current -> source-new diff and refuses
to write. Pass --apply to send the PATCH (single atomic call via
`pricing.apply_changes`), then refetch to verify each region.

    python mirror_pricing.py --source app.llcloud.auradisplay \
                             --target app.llcloud.tessera \
                             --product pro_lifetime            # dry-run
    python mirror_pricing.py --source ... --target ... --apply # commit
    python mirror_pricing.py --source ... --target ... --only TR,EG --apply

Credentials: GOOGLE_APPLICATION_CREDENTIALS (path) — same service account as
the other tools; it must have access to BOTH packages.
"""
from __future__ import annotations

import argparse
import os
import sys

from google.oauth2 import service_account
from googleapiclient.discovery import build

import pricing


def _build_pub():
    path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not path or not os.path.exists(path):
        sys.exit("set GOOGLE_APPLICATION_CREDENTIALS to the service-account JSON path")
    creds = service_account.Credentials.from_service_account_file(
        path, scopes=["https://www.googleapis.com/auth/androidpublisher"],
    )
    return build("androidpublisher", "v3", credentials=creds, cache_discovery=False)


def _configs(product: dict) -> list[dict]:
    opts = product.get("purchaseOptions") or [{}]
    return opts[0].get("regionalPricingAndAvailabilityConfigs") or []


def _same_price(a: dict, b: dict) -> bool:
    return (a.get("currencyCode") == b.get("currencyCode")
            and int(a.get("units", 0)) == int(b.get("units", 0))
            and a.get("nanos", 0) == b.get("nanos", 0))


def _usd(price: dict) -> str:
    u = pricing.price_to_usd(price)
    return f"${u:.2f}" if u is not None else "?"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", required=True, help="package to copy the price list FROM")
    ap.add_argument("--target", required=True, help="package to write the price list TO")
    ap.add_argument("--product", default="pro_lifetime", help="product id (must exist in both)")
    ap.add_argument("--only", help="comma-separated region codes to limit the plan")
    ap.add_argument("--apply", action="store_true", help="actually send the PATCH")
    args = ap.parse_args()

    pub = _build_pub()
    otp = pub.monetization().onetimeproducts()
    print(f"Fetching {args.source}/{args.product} and {args.target}/{args.product}…")
    src = otp.get(packageName=args.source, productId=args.product).execute()
    tgt = otp.get(packageName=args.target, productId=args.product).execute()

    src_by = {c["regionCode"]: c.get("price", {}) for c in _configs(src)}
    tgt_by = {c["regionCode"]: c.get("price", {}) for c in _configs(tgt)}

    only = {c.strip().upper() for c in args.only.split(",")} if args.only else None

    plan: dict[str, dict] = {}
    unchanged = 0
    ccy_mismatch: list[str] = []
    for region, src_price in src_by.items():
        if only and region not in only:
            continue
        if region not in tgt_by:
            continue  # region not offered by target — reported below, can't PATCH
        cur = tgt_by[region]
        sc, tc = src_price.get("currencyCode"), cur.get("currencyCode")
        if sc and tc and sc != tc:
            ccy_mismatch.append(f"{region}({tc}!={sc})")
            continue
        if _same_price(cur, src_price):
            unchanged += 1
            continue
        plan[region] = src_price

    src_only = sorted(set(src_by) - set(tgt_by))
    tgt_only = sorted(set(tgt_by) - set(src_by))

    us_src, us_tgt = src_by.get("US"), tgt_by.get("US")
    if us_src:
        print(f"  source US anchor : {pricing.fmt_local_price(us_src)}")
    if us_tgt:
        print(f"  target US current: {pricing.fmt_local_price(us_tgt)}")
    print(f"  {len(plan)} change(s) · {unchanged} already-equal · "
          f"{len(src_only)} source-only · {len(tgt_only)} target-only region(s)")
    print()
    print(f"  {'Region':6s}  {'Target now':>16s}  {'~USD':>7s}  ->  {'New (source)':>16s}  {'~USD':>7s}")
    print(f"  {'-'*6}  {'-'*16}  {'-'*7}      {'-'*16}  {'-'*7}")
    for region in sorted(plan):
        new, cur = plan[region], tgt_by[region]
        print(f"  {region:6s}  {pricing.fmt_local_price(cur):>16s}  {_usd(cur):>7s}  ->  "
              f"{pricing.fmt_local_price(new):>16s}  {_usd(new):>7s}")
    print()
    if ccy_mismatch:
        print(f"  ! currency mismatch (skipped): {', '.join(ccy_mismatch)}")
    if src_only:
        print(f"  (source-only, can't set on target: {', '.join(src_only)})")
    if tgt_only:
        print(f"  (target-only, left unchanged: {', '.join(tgt_only)})")
    print()

    if not plan:
        print("Nothing to do — target already matches source.")
        return 0
    if not args.apply:
        print("[dry-run] no write made. Pass --apply to send the PATCH.")
        return 0

    print(f"PATCHing {len(plan)} region(s) on {args.target}…")
    try:
        result = pricing.apply_changes(pub, args.target, args.product, plan)
    except Exception as e:  # noqa: BLE001 — surface any API failure verbatim
        print(f"PATCH failed: {type(e).__name__}: {e}")
        return 1
    ok = sum(1 for v in result.values() if v["ok"])
    print(f"  {ok}/{len(result)} verified")
    for rg, v in result.items():
        if not v["ok"]:
            print(f"  ! {rg}: did not take — got {pricing.fmt_local_price(v['got'])}")
    return 0 if ok == len(result) else 1


if __name__ == "__main__":
    raise SystemExit(main())
