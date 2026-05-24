"""Fetch reports for all configured apps.

Uses the google-cloud-storage Python client (no gcloud SDK needed). Reports
land under ``<DATA_DIR>/<package>/``:

  data/<package>/stats/      install / crash / rating / store-performance
  data/<package>/reviews/    monthly review CSVs
  data/<package>/sales/      sales CSVs (unzipped)
  data/<package>/earnings/   earnings CSVs (unzipped)
  data/<package>/api/        live API snapshot
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

from google.cloud import storage
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from config import App, Config


def _log(msg: str) -> None:
    print(f"[fetch] {msg}", flush=True)


def _download_prefix(bucket: storage.Bucket, prefix: str, dest: Path) -> int:
    """Download all blobs starting with ``prefix`` into ``dest`` (idempotent).

    Skips blobs whose local size already matches (cheap incremental sync).
    """
    dest.mkdir(parents=True, exist_ok=True)
    count = 0
    for blob in bucket.list_blobs(prefix=prefix):
        if blob.name.endswith("/"):
            continue
        local = dest / Path(blob.name).name
        if local.exists() and local.stat().st_size == (blob.size or 0):
            continue
        blob.download_to_filename(str(local))
        count += 1
    return count


def _unzip_all(folder: Path) -> None:
    for zp in folder.glob("*.zip"):
        try:
            with zipfile.ZipFile(zp) as zf:
                zf.extractall(folder)
        except zipfile.BadZipFile:
            _log(f"warn: bad zip {zp.name}")


def _fetch_gcs_for_app(bucket: storage.Bucket, app: App, app_data: Path) -> None:
    pkg = app.package
    targets = [
        (f"stats/installs/installs_{pkg}_", app_data / "stats"),
        (f"stats/crashes/crashes_{pkg}_", app_data / "stats"),
        (f"stats/ratings/ratings_{pkg}_", app_data / "stats"),
        (f"stats/store_performance/store_performance_{pkg}_", app_data / "stats"),
        (f"stats/store_performance/total_store_performance_{pkg}_", app_data / "stats"),
        (f"reviews/reviews_{pkg}_", app_data / "reviews"),
    ]
    # Sales and earnings are per-developer-account (one zip per month covers
    # every package). Mirror them under each app dir for self-containment;
    # the parser filters by Package ID inside.
    targets += [
        ("sales/salesreport_", app_data / "sales"),
        ("earnings/earnings_", app_data / "earnings"),
    ]
    total = 0
    for prefix, dest in targets:
        n = _download_prefix(bucket, prefix, dest)
        if n:
            _log(f"  {pkg}: {prefix}* -> {n} new")
        total += n
    _unzip_all(app_data / "sales")
    _unzip_all(app_data / "earnings")
    if total == 0:
        _log(f"  {pkg}: already up to date")


def _fetch_api_for_app(pub, app: App, app_data: Path) -> None:
    pkg = app.package
    api_dir = app_data / "api"
    api_dir.mkdir(parents=True, exist_ok=True)
    snap: dict[str, object] = {}

    try:
        snap["onetime_products"] = (
            pub.monetization().onetimeproducts().list(packageName=pkg).execute()
        )
    except HttpError as e:
        snap["onetime_products"] = {"error": str(e)}

    try:
        snap["subscriptions"] = (
            pub.monetization().subscriptions().list(packageName=pkg).execute()
        )
    except HttpError as e:
        snap["subscriptions"] = {"error": str(e)}

    reviews: list[dict] = []
    token: str | None = None
    try:
        while True:
            kwargs: dict[str, object] = {"packageName": pkg, "maxResults": 100}
            if token:
                kwargs["token"] = token
            page = pub.reviews().list(**kwargs).execute()
            reviews.extend(page.get("reviews", []))
            token = page.get("tokenPagination", {}).get("nextPageToken")
            if not token:
                break
        snap["live_reviews"] = reviews
    except HttpError as e:
        snap["live_reviews"] = {"error": str(e)}

    try:
        edit = pub.edits().insert(packageName=pkg, body={}).execute()
        eid = edit["id"]
        try:
            snap["listings"] = pub.edits().listings().list(
                packageName=pkg, editId=eid
            ).execute()
            snap["tracks"] = pub.edits().tracks().list(
                packageName=pkg, editId=eid
            ).execute()
        finally:
            pub.edits().delete(packageName=pkg, editId=eid).execute()
    except HttpError as e:
        snap["tracks"] = {"error": str(e)}
        snap["listings"] = {"error": str(e)}

    (api_dir / "snapshot.json").write_text(json.dumps(snap, indent=2))


def run(cfg: Config) -> None:
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    creds = service_account.Credentials.from_service_account_file(
        str(cfg.credentials_path),
        scopes=[
            "https://www.googleapis.com/auth/androidpublisher",
            "https://www.googleapis.com/auth/devstorage.read_only",
        ],
    )
    storage_client = storage.Client(credentials=creds, project=None)
    bucket = storage_client.bucket(cfg.reports_bucket)
    _log(f"bucket gs://{cfg.reports_bucket}/")

    pub = build("androidpublisher", "v3", credentials=creds, cache_discovery=False)

    for app in cfg.apps:
        app_data = cfg.data_dir / app.package
        _log(f"app: {app.package} ({app.name})")
        _fetch_gcs_for_app(bucket, app, app_data)
        _fetch_api_for_app(pub, app, app_data)
    _log("done.")
