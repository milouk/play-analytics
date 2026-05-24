"""Runtime configuration — read entirely from environment variables.

Required env vars:
    DEVELOPER_ACCOUNT_ID    Google Play developer account ID. Find this in
                            Play Console > Settings > Developer account.
                            The reports bucket is `pubsite_prod_<id>`.
    APPS                    Comma-separated list of apps to analyse, each as
                            either `package.name` or `package.name:Pretty Name`.
                            Example: "app.foo,app.bar:Bar"
    GOOGLE_APPLICATION_CREDENTIALS_JSON
                            Service account JSON key as a string (preferred
                            for env-only configs).
    -- or --
    GOOGLE_APPLICATION_CREDENTIALS
                            Path to the JSON key file (volume-mounted).

Optional env vars:
    DATA_DIR                Where to cache downloaded reports. Default ./data
    OUTPUT_DIR              Where to write the dashboards.    Default ./output
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class App:
    package: str   # e.g. "app.llcloud.auradisplay"
    name: str      # display name; defaults to last segment of package


def _parse_apps(spec: str | None) -> list[App]:
    if not spec:
        sys.exit("APPS env var is required (comma-separated package[:name] list)")
    apps: list[App] = []
    for entry in spec.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if ":" in entry:
            pkg, name = entry.split(":", 1)
            apps.append(App(pkg.strip(), name.strip()))
        else:
            pkg = entry
            # Default display name: capitalised last segment of the package.
            apps.append(App(pkg, pkg.rsplit(".", 1)[-1].title()))
    if not apps:
        sys.exit("APPS parsed to an empty list")
    return apps


def _resolve_credentials_path() -> Path:
    """Return a usable filesystem path for the service account JSON.

    If GOOGLE_APPLICATION_CREDENTIALS is set, use it. Otherwise read the JSON
    content from GOOGLE_APPLICATION_CREDENTIALS_JSON and materialise it into
    a tempfile so libraries that want a path still work.
    """
    path_env = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if path_env:
        p = Path(path_env).expanduser()
        if not p.exists():
            sys.exit(f"GOOGLE_APPLICATION_CREDENTIALS points to missing file: {p}")
        return p
    raw = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON")
    if not raw:
        sys.exit(
            "Provide credentials via GOOGLE_APPLICATION_CREDENTIALS (path) "
            "or GOOGLE_APPLICATION_CREDENTIALS_JSON (json content)."
        )
    try:
        json.loads(raw)
    except json.JSONDecodeError as e:
        sys.exit(f"GOOGLE_APPLICATION_CREDENTIALS_JSON is not valid JSON: {e}")
    tmp = Path(tempfile.gettempdir()) / "play-analytics-sa-key.json"
    tmp.write_text(raw)
    tmp.chmod(0o600)
    return tmp


@dataclass(frozen=True)
class Config:
    developer_account_id: str
    apps: list[App]
    credentials_path: Path
    data_dir: Path
    output_dir: Path

    @property
    def reports_bucket(self) -> str:
        return f"pubsite_prod_{self.developer_account_id}"


def load() -> Config:
    dev_id = os.environ.get("DEVELOPER_ACCOUNT_ID")
    if not dev_id:
        sys.exit("DEVELOPER_ACCOUNT_ID env var is required")
    here = Path(__file__).resolve().parent
    data_dir = Path(os.environ.get("DATA_DIR", here / "data"))
    output_dir = Path(os.environ.get("OUTPUT_DIR", here / "output"))
    return Config(
        developer_account_id=dev_id.strip(),
        apps=_parse_apps(os.environ.get("APPS")),
        credentials_path=_resolve_credentials_path(),
        data_dir=data_dir,
        output_dir=output_dir,
    )
