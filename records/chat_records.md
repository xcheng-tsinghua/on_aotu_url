Build a new project from scratch: an Onshape Public CAD Model Filter.

Goal:
Create a browser-automation-based tool that uses the Onshape web interface to collect high-quality public CAD models from the Onshape Public model list.

Important constraints:

1. Do NOT use the Onshape REST API.
2. Do NOT use MiniMax or any LLM API.
3. Do NOT use any paid API.
4. Do NOT require the user to provide search keywords.
5. Use Playwright browser automation only.
6. The user will manually log in to an Onshape account in the browser.
7. After login, the tool should automatically open the Onshape Public tab/page, scroll the public model list to load more public models, open candidate models, inspect their Part Studio feature trees, and filter them using deterministic rules.
8. The filtering logic must be deterministic, rule-based, reproducible, and explainable.
9. The tool should collect Onshape model links that satisfy the rules and export the results as JSON and CSV.

Definition of a high-quality Onshape model:
A model is considered high-quality only if all active, unsuppressed modeling features belong to the allowed command whitelist.

Allowed active feature types:

* Sketch
* Extrude
* Revolve
* Sweep
* Loft
* Chamfer
* Fillet
* Plane
* CPlane

Rejection rules:

1. If the model contains an active, unsuppressed Import feature, reject it.
2. If the model contains an active, unsuppressed Derived feature, reject it.
3. If the model contains any active, unsuppressed feature outside the whitelist, reject it.
4. If any active feature has an error or failed regeneration status, reject it.
5. If the feature tree cannot be read reliably, mark the model as uncertain instead of passing it.

Suppressed feature rule:
If the model contains unsupported features outside the whitelist, but those features are suppressed and do not affect the final model, the model can still pass. These suppressed unsupported features should be recorded in the output but should not cause rejection.

The first version should be a Python project using:

* Python 3.10+
* Playwright
* Pydantic
* pandas or csv/json standard libraries
* pytest for tests

Project structure:
onshape_model_filter/
README.md
requirements.txt
.env.example
src/
main.py
browser/
onshape_browser.py
selectors.py
parser/
feature_tree_parser.py
rules/
feature_rule_evaluator.py
models/
schemas.py
export/
result_exporter.py
utils/
logging_utils.py
tests/
test_feature_rule_evaluator.py
test_feature_tree_parser.py
outputs/
screenshots/
results/

Main workflow:

1. Start Playwright Chromium in persistent browser context so that the login session can be reused.
2. Open Onshape.
3. If the user is not logged in, wait for the user to manually log in.
4. After login is detected, automatically navigate to the Onshape Public tab/page.
5. Scroll the public model list downward to progressively load more public models.
6. Collect candidate public model cards/links from the loaded list.
7. Deduplicate candidate URLs.
8. Open each candidate public model.
9. Find available Part Studios in the document.
10. Open the first valid Part Studio, or inspect multiple Part Studios if configured.
11. Wait until the model viewport and left-side feature tree are fully loaded.
12. Extract the feature tree from the page.
13. Parse each feature into structured data.
14. Evaluate the model using deterministic rules.
15. Save screenshots and structured results.
16. Continue until the configured maximum number of candidates has been inspected.
17. Export passed, rejected, uncertain, and summary reports.

Persistent login:
Use Playwright persistent context with a local user data directory, for example:

* user_data_dir = ".playwright/onshape_profile"

The first run should open a non-headless browser and wait for manual login.
After login, the browser session should be reused in later runs.

Do not ask the user to provide Onshape API keys.
Do not store passwords.
Do not automate password input.
Only reuse the browser session cookies/profile created by the user’s manual login.

Public list collection:
The tool should automatically open the Onshape Public area after login.

Implement:
BrowserOnshapeClient.open_public_page()

This function should navigate to the Onshape documents/home page and select the Public tab or directly navigate to the public documents page if a stable URL is available.

Then implement:
BrowserOnshapeClient.collect_public_candidates(max_candidates, max_scrolls)

Behavior:

1. Read currently visible public model cards.
2. Extract candidate document title and URL when available.
3. Scroll the public list downward.
4. Wait for new cards to load.
5. Add newly discovered candidates.
6. Stop when max_candidates is reached or max_scrolls is reached.
7. Deduplicate by URL or document ID if possible.

Candidate source:
The candidate source should be the public model list shown in the Onshape web UI, not a keyword search result.

Feature data schema:
Each extracted feature should include:
{
"index": int,
"raw_text": string,
"feature_name": string,
"feature_type": string,
"is_suppressed": bool,
"has_error": bool,
"is_import": bool,
"is_derived": bool
}

Candidate result schema:
{
"url": string,
"document_name": string | null,
"part_studio_name": string | null,
"status": "passed" | "rejected" | "uncertain",
"reason": string,
"active_feature_histogram": {
"Sketch": int,
"Extrude": int,
"Revolve": int,
"Sweep": int,
"Loft": int,
"Chamfer": int,
"Fillet": int,
"Plane": int,
"CPlane": int
},
"active_unsupported_features": [
{
"index": int,
"feature_name": string,
"feature_type": string,
"raw_text": string
}
],
"suppressed_unsupported_features": [
{
"index": int,
"feature_name": string,
"feature_type": string,
"raw_text": string
}
],
"has_active_import": bool,
"has_active_derived": bool,
"has_active_error": bool,
"screenshot_path": string | null
}

Command-line interface:
Implement a CLI like this:

python -m src.main 
--max-candidates 100 
--max-scrolls 30 
--headless false 
--output-dir outputs/results

CLI arguments:

* --max-candidates: maximum number of public model candidates to inspect
* --max-scrolls: maximum number of downward scroll actions on the Public model list
* --headless: true or false
* --output-dir: output directory
* --timeout-ms: default 30000
* --min-active-feature-count: optional, default 1
* --allow-suppressed-unsupported: default true
* --inspect-multiple-part-studios: default false
* --max-part-studios-per-document: default 1
* --delay-between-candidates-ms: default 2000

No --query argument is needed.

Browser automation requirements:

1. Use Playwright Chromium.
2. Support both headless and non-headless modes.
3. Use persistent browser context so login can be reused.
4. On first run, launch with headless=false so the user can manually log in.
5. Detect whether login has completed before continuing.
6. Add robust wait logic for page loading.
7. Take a screenshot for every inspected candidate.
8. Avoid relying on OCR.
9. Prefer DOM extraction from the Onshape feature tree.
10. If DOM selectors are unstable, centralize selectors in src/browser/selectors.py for easier maintenance.
11. Add retry logic when a page fails to load.
12. Do not perform high-frequency aggressive scraping. Add a configurable delay between candidates.
13. When feature tree extraction fails, mark the candidate as uncertain rather than passed.

Feature type inference:
Implement a parser that maps raw feature text or accessible labels to normalized feature types.

Examples:

* "Sketch 1" -> Sketch
* "Extrude 1" -> Extrude
* "Revolve 1" -> Revolve
* "Sweep 1" -> Sweep
* "Loft 1" -> Loft
* "Chamfer 1" -> Chamfer
* "Fillet 1" -> Fillet
* "Plane 1" -> Plane
* "CPlane 1" -> CPlane
* "Import 1" -> Import
* "Derived 1" -> Derived
* "Hole 1" -> Hole
* "Shell 1" -> Shell
* "Pattern 1" -> Pattern
* "Mirror 1" -> Mirror
* "Boolean 1" -> Boolean

The parser should be case-insensitive and should tolerate small formatting differences.

Suppressed feature detection:
Implement robust detection for suppressed features using available DOM attributes, CSS classes, icons, aria-labels, title attributes, or text decorations.
If suppression status cannot be determined reliably for a feature, mark that feature as uncertain and mark the candidate as uncertain.

Error feature detection:
Detect feature errors using available DOM classes, icons, red indicators, warning icons, aria-labels, title attributes, or other visible indicators.
If error status cannot be determined reliably, mark it as false only when there is no visible error indicator. If the feature tree contains explicit regeneration errors, reject the candidate.

Rule evaluator:
Implement the rule evaluator as a pure function that can be unit-tested without opening a browser.

Pseudo logic:
allowed_active_features = {
"Sketch",
"Extrude",
"Revolve",
"Sweep",
"Loft",
"Chamfer",
"Fillet",
"Plane",
"CPlane"
}

For each feature:

* If feature.is_suppressed is true:

  * If feature.feature_type is not in allowed_active_features:
    record it in suppressed_unsupported_features
  * Continue
* If feature.has_error is true:
  reject candidate
* If feature.feature_type is "Import":
  reject candidate
* If feature.feature_type is "Derived":
  reject candidate
* If feature.feature_type is not in allowed_active_features:
  reject candidate
* Otherwise:
  count it in active_feature_histogram

If all active features are allowed and no active error/import/derived exists:
pass candidate

If the feature tree cannot be extracted or feature states cannot be determined reliably:
mark candidate as uncertain

Outputs:
Generate:

1. passed_candidates.json
2. rejected_candidates.json
3. uncertain_candidates.json
4. all_candidates.csv
5. summary.json

summary.json should include:
{
"source": "Onshape Public list",
"total_public_candidates_collected": int,
"total_inspected": int,
"num_passed": int,
"num_rejected": int,
"num_uncertain": int,
"pass_rate": float,
"rejection_reason_histogram": object
}

README requirements:
Write a clear README explaining:

1. What this tool does.
2. Why it does not use Onshape API.
3. Why it does not require search keywords.
4. How the user logs in manually.
5. How the persistent browser profile works.
6. How to install dependencies.
7. How to install Playwright browser.
8. How to run the CLI.
9. How to interpret outputs.
10. Known limitations.
11. How to update selectors if Onshape UI changes.

Installation commands:
pip install -r requirements.txt
playwright install chromium

Important implementation principles:

* Keep browser automation, feature parsing, rule evaluation, and exporting separated.
* Do not mix rule logic with Playwright code.
* Make the rule evaluator highly testable.
* Log every inspected URL and every rejection reason.
* Treat uncertain extraction as uncertain, not as passed.
* The first version does not need a web frontend.
* The first version does not need an LLM.
* The first version should focus on reliability and clean data output.
