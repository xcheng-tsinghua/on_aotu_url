# Onshape Public CAD Model Filter

Browser-automation tool for collecting high-quality public CAD models from the Onshape Public model list. It uses Playwright to drive the Onshape web interface, logs in with a configured disposable test account, inspects Part Studio feature trees, and exports deterministic rule-based results as JSON and CSV.

## What It Does

1. Opens Onshape in a persistent Chromium profile.
2. Loads test-account credentials from `.env`.
3. Skips login if the browser profile is already authenticated.
4. Logs in automatically when needed.
5. Uses candidate links from `--candidates-json` when provided; otherwise navigates to the Onshape Public documents area.
6. Scrolls the public model list to maintain a deduplicated candidate queue when no JSON file is provided.
7. Opens candidates until the target inspected count is reached.
8. Records the opened Part Studio URL after Onshape fills the element id (`/e/...`).
9. Scrolls each Part Studio feature tree panel to collect all feature rows.
10. Parses feature rows into structured records.
11. Applies deterministic whitelist/rejection rules.
12. Writes passed, rejected, uncertain, CSV, feature artifacts, and summary reports incrementally.

## Why Browser Automation

This project intentionally does not use the Onshape REST API. The goal is to filter models exactly from the public model list exposed in the Onshape web UI, without API keys, OAuth setup, paid services, or hidden search queries.

It also does not use MiniMax, LLM APIs, OCR, or any paid API. All pass/reject decisions come from deterministic Python rules that can be unit tested.

## No Search Keywords

The candidate source is the Onshape Public list itself. The tool scrolls that list and collects visible public document links; there is no `--query` option and no requirement for the user to provide keywords.

## Install

Use Python 3.10+.

```bash
pip install -r requirements.txt
playwright install chromium
```

Optional environment variables can be copied from `.env.example` into your shell or a local `.env` workflow:

```bash
ONSHAPE_BASE_URL=https://cad.onshape.com
ONSHAPE_EMAIL=
ONSHAPE_PASSWORD=
ONSHAPE_PUBLIC_URL=
ONSHAPE_USER_DATA_DIR=.playwright/onshape_profile
```

The CLI uses `python-dotenv` to load `.env` automatically.

## Automated Login And Persistent Profile

Create a local `.env` file with a disposable test-account login:

```bash
ONSHAPE_EMAIL=your-test-account@example.com
ONSHAPE_PASSWORD=your-test-password
```

Do not commit `.env`; it is already ignored by `.gitignore`.

Run with a visible browser while debugging:

```bash
python -m src.main --target-inspected-count 100 --headless false --max-scrolls 300 --output-dir outputs/results
```

Run from a local candidate-link JSON file instead of the Public tab:

```bash
python -m src.main --candidates-json candidates.json --headless false --output-dir outputs/results
```

If the persistent browser profile is already logged in, the tool skips credential entry. Otherwise it opens the Onshape sign-in page, fills `ONSHAPE_EMAIL` and `ONSHAPE_PASSWORD`, submits the login form, and waits for the documents page to load.

The password is never printed in logs. If login fails, the tool stops and writes a screenshot to `outputs/screenshots/login_failed.png`.

Playwright stores the browser session under:

```text
.playwright/onshape_profile
```

Later runs reuse that local profile and can usually skip login. Keep this directory private; it contains browser cookies/session state.

## CLI

```bash
python -m src.main --target-inspected-count 0 --max-scrolls 0 --headless false --output-dir outputs/results --timeout-ms 30000 --scroll-patience 50 --resume true --min-active-feature-count 5 --allow-suppressed-unsupported true --inspect-multiple-part-studios false --max-part-studios-per-document 1 --delay-between-candidates-ms 2000

python -m src.main --candidates-json candidates.json --headless false --output-dir outputs/results

```

Arguments:

- `--target-inspected-count`: number of validation results to produce in this run; this includes `passed`, `rejected`, and `uncertain`. The default `0` means no count limit.
- `--max-candidates-buffer`: maximum uninspected Public-list candidate links to keep in memory.
- `--max-scrolls`: maximum downward scroll actions in the Public list. The default `0` means no scroll count limit.
- `--scroll-patience`: stop collecting after this many consecutive Public-list scrolls add no new candidates. Set `0` to disable this stop condition.
- `--resume`: when true, load previous output JSON files and skip already inspected URLs.
- `--debug-one-url`: inspect one Onshape document URL, save feature-tree artifacts, evaluate it, and print the result.
- `--candidates-json`: read candidate document or Part Studio links from a JSON file after login, instead of opening the Public tab.
- `--headless`: `true` or `false`.
- `--output-dir`: report output directory.
- `--timeout-ms`: Playwright timeout for UI waits.
- `--min-active-feature-count`: reject reliable models with fewer active features.
- `--allow-suppressed-unsupported`: allow suppressed unsupported features without rejection.
- `--inspect-multiple-part-studios`: inspect more than the first Part Studio.
- `--max-part-studios-per-document`: cap Part Studios inspected per document.
- `--delay-between-candidates-ms`: polite delay between candidate documents.

For a long JSON-file run, the shortest command is:

```bash
python -m src.main --candidates-json candidates.json --output-dir outputs/results --headless false
```

With the defaults, this runs until every uninspected candidate in the JSON file is consumed. For a long Public-list run, omit `--candidates-json`; the default `--target-inspected-count 0` keeps validating until Public collection is exhausted by the scroll/patience settings.

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

Reject when the Part Studio feature tree contains feature folders, because collapsed folders can hide features that are not reliably extracted from the visible tree.

Suppressed unsupported features are recorded in the output. By default, they do not reject a model because they do not affect the final model.

If the feature tree cannot be extracted completely, or suppression status cannot be determined reliably, the candidate is marked `uncertain`, not `passed`.

## Outputs

Reports are written to `outputs/results` by default:

- `passed_candidates.json`
- `rejected_candidates.json`
- `uncertain_candidates.json`
- `all_candidates.csv`
- `summary.json`

Candidate URLs are recorded from the opened Part Studio page, so successful browser loads include the document id, workspace id, and element id (`/documents/{did}/w/{wid}/e/{eid}`).

Screenshots are written to `outputs/screenshots`.

Per-candidate feature extraction artifacts are written to `outputs/results/feature_artifacts` by default:

- viewport screenshot path is recorded in the candidate result
- `*_feature_tree_before.png`
- `*_feature_tree_after.png`
- `*_extracted_features.json`

The extractor scrolls the left-side feature tree container itself, not the browser page, and deduplicates feature rows while scanning from top to bottom.

Candidate JSON files can be a list of URL strings:

```json
[
  "https://cad.onshape.com/documents/{did}/w/{wid}",
  "https://cad.onshape.com/documents/{did}/w/{wid}/e/{eid}"
]
```

They can also be an object with `candidates` or `urls`; object entries may include `url`, `document_name`, and `document_id`.

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
- `FEATURE_TREE_FOLDER_ROW_SELECTORS`

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
