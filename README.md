<h1 align="center">play-analytics</h1>

<p align="center"><em>a self-hosted dashboard for Google Play Console data — installs, retention, crashes, sales, reviews, all in one HTML page</em></p>

<p align="center">
  <a href="https://github.com/milouk/play-analytics/actions/workflows/build.yml"><img alt="build" src="https://github.com/milouk/play-analytics/actions/workflows/build.yml/badge.svg"></a>
  <a href="https://github.com/milouk/play-analytics/pkgs/container/play-analytics"><img alt="ghcr" src="https://img.shields.io/badge/ghcr.io-milouk%2Fplay--analytics-2496ED?logo=docker&logoColor=white"></a>
  <a href="https://github.com/milouk/play-analytics/commits/main"><img alt="last commit" src="https://img.shields.io/github/last-commit/milouk/play-analytics?logo=github"></a>
  <a href="LICENSE"><img alt="license" src="https://img.shields.io/badge/license-MIT-blue.svg"></a>
</p>

> Pulls every metric Google Play exposes for your apps — daily install
> reports, crash & ANR counts, ratings, store-listing visitors, monthly
> sales & earnings CSVs, in-app product catalogs, and live reviews — then
> renders a self-contained dark-mode HTML dashboard for each app and a
> top-level index that links to all of them. **One developer account,
> any number of apps**, one image, configured entirely with env vars.

## Quickstart

```bash
docker run --rm \
  -e DEVELOPER_ACCOUNT_ID=1234567890123456789 \
  -e APPS="com.example.app1:My App,com.example.app2:Other App" \
  -e GOOGLE_APPLICATION_CREDENTIALS_JSON="$(cat key.json)" \
  -v "$(pwd)/output:/app/output" \
  ghcr.io/milouk/play-analytics:latest
open output/index.html
```

Or with the built-in HTTP server:

```bash
docker run --rm -p 8080:8080 \
  -e DEVELOPER_ACCOUNT_ID=... -e APPS=... \
  -e GOOGLE_APPLICATION_CREDENTIALS_JSON="$(cat key.json)" \
  -e SERVE=true \
  ghcr.io/milouk/play-analytics:latest
# → http://localhost:8080/
```

## What you get

For each app in `$APPS`:

- `output/<package>/dashboard.html` — single-file HTML, dark theme, Chart.js
- `output/<package>/report.md` — Markdown summary (PR/Slack-friendly)

Plus:

- `output/index.html` — landing page with a card per app

Each dashboard surfaces:

| Section | Metrics |
|---|---|
| **Headline KPIs** | active devices today · user installs · net retention · paid orders · paid conversion · net earnings · avg rating · crashes / ANRs |
| **Growth** | daily user installs (bars) overlaid with active devices (line) |
| **Geography & audience** | installs by country (top 15) · language · device · Android OS · app version |
| **Quality** | daily crashes & ANRs · star distribution from review CSVs |
| **Monetisation** | every charged sales transaction · revenue by currency · paying countries |
| **Voice of customer** | full review text with stars, device, version, developer reply |
| **Catalog** | live in-app product list + subscription list + release tracks |

## What it reads

Two sources, both via the service-account key:

1. **`gs://pubsite_prod_<developer_account_id>/`** — the GCS bucket where Play
   writes your daily install/crash/rating CSVs and monthly sales/earnings zips.
   Folders: `stats/installs/`, `stats/crashes/`, `stats/ratings/`,
   `stats/store_performance/`, `reviews/`, `sales/`, `earnings/`.
2. **Android Publisher API v3** — live catalog (`monetization.onetimeproducts`,
   `monetization.subscriptions`), the trailing ~7-day review window
   (`reviews.list`), and current release tracks + localised listings.

Downloads are incremental (skips files whose local size matches the blob),
so a re-run after a fresh report drop is fast.

## One-time setup

You need three things: a **service account**, the **developer account ID**,
and **read access** for that service account on the reports bucket.

### 1. Service account

In Google Cloud Console → IAM → Service Accounts → **Create**. No GCP roles
needed; the permissions live in Play Console and on the bucket. Download
the JSON key — this is the file you pass via
`GOOGLE_APPLICATION_CREDENTIALS_JSON`.

### 2. Grant the service account access in Play Console

Play Console → Users and permissions → **Invite new user** → use the
service account email. Grant at minimum:

- **App permissions**: View app information and download bulk reports
  *(for every app in `$APPS`)*
- **Account permissions** (optional, enables live catalog/listings):
  View store listings, View financial data

### 3. Grant bucket read access

The reports bucket lives in a Google-managed project, not yours. The
service account needs to be added as a reader:

```bash
gsutil iam ch \
  serviceAccount:play-analytics@your-project.iam.gserviceaccount.com:roles/storage.objectViewer \
  gs://pubsite_prod_<your-developer-account-id>
```

Run this once from a Google account that has Owner on the dev account.

### 4. Find your developer account ID

Play Console → Settings → Developer account → Account details →
**Account ID**. It's a 19-digit number.

### 5. Enumerate your apps

Use the package name from Play Console — `app.foo.bar` style. Pretty
names are optional but recommended.

```env
APPS=app.acme.notes:Acme Notes,app.acme.timer:Acme Timer
```

## Configuration

All via env vars. See [`.env.example`](.env.example) for the full list.

| Variable | Required | Purpose |
|---|---|---|
| `DEVELOPER_ACCOUNT_ID` | yes | 19-digit ID from Play Console |
| `APPS` | yes | comma-separated `package[:Pretty Name]` list |
| `GOOGLE_APPLICATION_CREDENTIALS_JSON` | one of | JSON content as a string (env-friendly) |
| `GOOGLE_APPLICATION_CREDENTIALS` | one of | filesystem path to the JSON key |
| `DATA_DIR` | no | cache for downloaded reports — default `/app/data` |
| `OUTPUT_DIR` | no | where dashboards go — default `/app/output` |
| `SERVE` | no | `true` to serve `OUTPUT_DIR` over HTTP after rendering |
| `PORT` | no | server port if `SERVE=true` — default `8080` |

## Running it

### Docker (recommended)

```bash
docker run --rm \
  -e DEVELOPER_ACCOUNT_ID=... \
  -e APPS="pkg.a:App A,pkg.b:App B" \
  -e GOOGLE_APPLICATION_CREDENTIALS_JSON="$(cat key.json)" \
  -v "$(pwd)/data:/app/data" \
  -v "$(pwd)/output:/app/output" \
  ghcr.io/milouk/play-analytics:latest
```

Mounting `data/` is optional but makes re-runs near-instant (it's used as
a cache).

### Docker Compose (set-and-forget self-host)

```bash
cp .env.example .env
# edit .env
docker compose up -d
```

The compose file enables `SERVE=true` and exposes port 8080.

### GitHub Actions (scheduled, no server)

```yaml
name: refresh dashboards
on:
  schedule: [{ cron: "0 6 * * *" }]
  workflow_dispatch:

jobs:
  refresh:
    runs-on: ubuntu-latest
    permissions: { contents: write }
    steps:
      - uses: actions/checkout@v4
      - run: |
          docker run --rm \
            -e DEVELOPER_ACCOUNT_ID=${{ secrets.PLAY_DEV_ID }} \
            -e APPS=${{ vars.PLAY_APPS }} \
            -e GOOGLE_APPLICATION_CREDENTIALS_JSON='${{ secrets.GOOGLE_SA_JSON }}' \
            -v ${{ github.workspace }}/output:/app/output \
            ghcr.io/milouk/play-analytics:latest
      - uses: peaceiris/actions-gh-pages@v4
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          publish_dir: ./output
```

This publishes your dashboards to GitHub Pages on a schedule, no
server required.

### Locally with Python (no Docker)

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
export DEVELOPER_ACCOUNT_ID=...
export APPS="pkg.a:App A"
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json
.venv/bin/python main.py            # fetch + render
.venv/bin/python main.py --no-fetch # rerender from cache
.venv/bin/python main.py --serve    # also start http.server on 8080
```

## How it's built

- **Python 3.12**, stdlib + four Google client libs (no pandas, no flask, no jinja)
- `google-cloud-storage` for the reports bucket (drops the gcloud SDK dependency entirely)
- `google-api-python-client` for the live Android Publisher API
- HTML rendered from string templates with embedded `Chart.js` (single
  `<script>` tag from jsDelivr CDN); each dashboard is a self-contained file
- ~10 MB final image, multi-arch (`linux/amd64`, `linux/arm64`)

## Caveats

- **Reports lag ~48 h.** Today's data is never present.
- **`Daily Device Uninstalls` is unreliable in Google's reports** (often
  all zero). This tool uses `Uninstall events` + `Daily User Uninstalls`
  for retention math; the dashboard shows real numbers.
- The Publisher API's `reviews.list` returns only the trailing ~7 days.
  The monthly review CSVs in the bucket are the source of truth for
  full history.
- **Net earnings only appear once a month finalises** (around the 15th of
  the following month).

## License

[MIT](LICENSE) © Michael Loukeris

## Acknowledgements

Pulls data exclusively from the [Google Play Developer Reports][1] and
the [Android Publisher API v3][2]. No third-party APIs or telemetry.

[1]: https://support.google.com/googleplay/android-developer/answer/6135870
[2]: https://developers.google.com/android-publisher
