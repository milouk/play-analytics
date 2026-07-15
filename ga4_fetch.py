#!/usr/bin/env python3
"""Fetch AuraDisplay telemetry from Google Analytics 4 (Firebase Analytics).

The scriptable equivalent of the old Sentry REST pulls, now that product
telemetry lives in Firebase Analytics instead of Sentry.captureMessage.

Auth: reuses the play-deploy service account (GOOGLE_APPLICATION_CREDENTIALS).
That SA must be granted Viewer on the GA4 property (Admin -> Property Access
Management) and the Analytics Data API must be enabled on the GCP project.

Usage:
    export GA4_PROPERTY_ID=123456789          # GA4 Admin -> Property Settings
    export GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa.json
    .venv/bin/python ga4_fetch.py             # last 28d event counts
    .venv/bin/python ga4_fetch.py --realtime  # last 30 min (fast verify)
    .venv/bin/python ga4_fetch.py --event onboarding_grant_result --by granted

Custom event PARAMETERS (oem, installer, granted, ...) only appear in
reports once registered as Custom Dimensions in GA4 (Admin -> Custom
definitions -> Create custom dimension, scope=Event, matching the param
name). Until then, --by on a custom param returns "(not set)". Event
NAMES and counts work with no setup.
"""
from __future__ import annotations
import argparse, json, os, sys
import google.auth.transport.requests
from google.oauth2 import service_account

SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]
BASE = "https://analyticsdata.googleapis.com/v1beta/properties"

# AuraDisplay GA4 (Firebase project: llcloudapps).
# Account ID: 401275069  (the Analytics ACCOUNT — not what the Data API
# takes). The Data API needs the PROPERTY ID (GA4 Admin -> Property
# Settings); set it via GA4_PROPERTY_ID. The play-deploy SA must have
# Viewer on that property.
GA4_ACCOUNT_ID = "401275069"


def session():
    key = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not key or not os.path.exists(key):
        sys.exit("GOOGLE_APPLICATION_CREDENTIALS not set / file missing")
    creds = service_account.Credentials.from_service_account_file(key, scopes=SCOPES)
    return google.auth.transport.requests.AuthorizedSession(creds)


def prop() -> str:
    p = os.environ.get("GA4_PROPERTY_ID")
    if not p:
        sys.exit("GA4_PROPERTY_ID not set (GA4 Admin -> Property Settings)")
    return p


def run(sess, path, body):
    r = sess.post(f"{BASE}/{prop()}:{path}", json=body)
    if r.status_code != 200:
        sys.exit(f"GA4 API {r.status_code}: {r.text[:400]}")
    return r.json()


def rows(resp):
    for row in resp.get("rows", []):
        dims = [d["value"] for d in row.get("dimensionValues", [])]
        mets = [m["value"] for m in row.get("metricValues", [])]
        yield dims, mets


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--realtime", action="store_true", help="last 30 min")
    ap.add_argument("--days", type=int, default=28)
    ap.add_argument("--event", help="filter to one event name")
    ap.add_argument("--by", help="break down by this custom-dimension param")
    a = ap.parse_args()
    sess = session()

    breakdown = ["eventName"] + ([f"customEvent:{a.by}"] if a.by else [])
    dims = [{"name": d} for d in breakdown]

    if a.realtime:
        body = {"dimensions": dims, "metrics": [{"name": "eventCount"}]}
        resp = run(sess, "runRealtimeReport", body)
        title = "REALTIME (last 30 min)"
    else:
        body = {
            "dateRanges": [{"startDate": f"{a.days}daysAgo", "endDate": "today"}],
            "dimensions": dims,
            "metrics": [{"name": "eventCount"}],
            "orderBys": [{"metric": {"metricName": "eventCount"}, "desc": True}],
        }
        resp = run(sess, "runReport", body)
        title = f"LAST {a.days}d"

    print(f"== AuraDisplay telemetry — {title} ==")
    any_row = False
    for dimvals, metvals in rows(resp):
        name = dimvals[0]
        if a.event and name != a.event:
            continue
        any_row = True
        extra = f"  {a.by}={dimvals[1]}" if a.by else ""
        print(f"  {name:36} {metvals[0]:>8}{extra}")
    if not any_row:
        print("  (no data — newly-configured properties take up to 24h for"
              " standard reports; use --realtime for near-instant verification)")


if __name__ == "__main__":
    main()
