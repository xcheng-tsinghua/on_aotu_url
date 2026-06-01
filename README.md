# Onshape Public CAD Model Filter

Browser-automation tool for collecting high-quality public CAD models from the Onshape Public model list. It uses Playwright to drive the Onshape web interface, lets the user log in manually, inspects Part Studio feature trees, and exports deterministic rule-based results as JSON and CSV.

## What It Does

1. Opens Onshape in a persistent Chromium profile.
2. Waits for the user to log in manually if no reusable session exists.
3. Navigates to the Onshape Public documents area.
4. Scrolls the public model list to collect candidate document links.
5. Opens each candidate document and inspects Part Studio feature trees.
6. Parses visible feature rows into structured records.
7. Applies deterministic whitelist/rejection rules.
8. Writes passed, rejected, uncertain, CSV, and summary reports.

## Why Browser Automation

This project intentionally does not use the Onshape REST API. The goal is to filter models exactly from the public model list exposed in the Onshape web UI, without API keys, OAuth setup, paid services, or hidden search queries.

It also does not use MiniMax, LLM APIs, OCR, or any paid API. All pass/reject decisions come from deterministic Python rules that can be unit tested.

## No Search Keywords

The candidate source is the Onshape Public list itself. The tool scrolls that list and collects visible public document links; there is no `--query` option and no requirement for the user to provide keywords.

## Install

Use Python 3.10+.

```bash
cd onshape_model_filter
pip install -r requirements.txt
playwright install chromium
```

Optional environment variables can be copied from `.env.example` into your shell or a local `.env` workflow:

```bash
ONSHAPE_BASE_URL=https://cad.onshape.com
ONSHAPE_PUBLIC_URL=
ONSHAPE_USER_DATA_DIR=.playwright/onshape_profile
```

The code reads environment variables directly. It does not require `python-dotenv`.

## Manual Login And Persistent Profile

The first run should use a visible browser:

```bash
python -m src.main --headless false --max-candidates 100 --max-scrolls 30 --output-dir outputs/results
```

If you are not logged in, Chromium opens the Onshape sign-in page and waits. Log in manually in that browser window. The tool never asks for, types, or stores your password.

Playwright stores the browser session under:

```text
.playwright/onshape_profile
```

Later runs reuse that local profile and can usually skip manual login. Keep this directory private; it contains browser cookies/session state.

## CLI

```bash
python -m src.main --max-candidates 100 --max-scrolls 30 --headless false --output-dir outputs/results --timeout-ms 30000 --min-active-feature-count 1 --allow-suppressed-unsupported true --inspect-multiple-part-studios false  --max-part-studios-per-document 1 --delay-between-candidates-ms 2000
```

Arguments:

- `--max-candidates`: maximum public document candidates to inspect.
- `--max-scrolls`: maximum downward scroll actions in the Public list.
- `--headless`: `true` or `false`; first login requires `false`.
- `--output-dir`: report output directory.
- `--timeout-ms`: Playwright timeout for UI waits.
- `--min-active-feature-count`: reject reliable models with fewer active features.
- `--allow-suppressed-unsupported`: allow suppressed unsupported features without rejection.
- `--inspect-multiple-part-studios`: inspect more than the first Part Studio.
- `--max-part-studios-per-document`: cap Part Studios inspected per document.
- `--delay-between-candidates-ms`: polite delay between candidate documents.

## Rule Logic

Allowed active, unsuppressed feature types:

- `Sketch`
- `Extrude`
- `Revolve`
- `Sweep`
- `Loft`
- `Chamfer`
- `Fillet`
- `Plane`
- `CPlane`

Reject when an active, unsuppressed feature is:

- `Import`
- `Derived`
- outside the whitelist
- marked with an error or failed regeneration status

Suppressed unsupported features are recorded in the output. By default, they do not reject a model because they do not affect the final model.

If the feature tree cannot be extracted or suppression status cannot be determined reliably, the candidate is marked `uncertain`, not `passed`.

## Outputs

Reports are written to `outputs/results` by default:

- `passed_candidates.json`
- `rejected_candidates.json`
- `uncertain_candidates.json`
- `all_candidates.csv`
- `summary.json`

Screenshots are written to `outputs/screenshots`.

`summary.json` includes:

```json
{
  "source": "Onshape Public list",
  "total_public_candidates_collected": 0,
  "total_inspected": 0,
  "num_passed": 0,
  "num_rejected": 0,
  "num_uncertain": 0,
  "pass_rate": 0.0,
  "rejection_reason_histogram": {}
}
```

## Updating Selectors

Onshape is a complex single-page web app and its DOM can change. UI selectors are centralized in:

```text
src/browser/selectors.py
```

If collection or feature extraction stops working, update:

- `PUBLIC_TAB_SELECTORS`
- `PUBLIC_LIST_CONTAINER_SELECTORS`
- `PART_STUDIO_TAB_SELECTORS`
- `FEATURE_TREE_ITEM_SELECTORS`

If your Onshape account has a stable Public documents URL, set `ONSHAPE_PUBLIC_URL` and the tool will navigate directly to it.

## Known Limitations

- Onshape UI selectors may need maintenance when the web app changes.
- The first version avoids OCR and relies on DOM-accessible feature tree text/metadata.
- If Onshape hides feature state only in canvas pixels or inaccessible icons, the model is marked `uncertain`.
- The tool is intentionally slow and polite; it is not designed for high-frequency scraping.
- Public documents may contain multiple tabs and workspaces; the default inspects the first detected Part Studio.

## Tests

The browser workflow requires a live Onshape session and is not unit-tested against the site. The deterministic parser and rule evaluator are covered by pytest:

```bash
pytest
```
