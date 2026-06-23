from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from src.browser.onshape_browser import BrowserClientConfig, BrowserOnshapeClient
from src.export.result_exporter import ResultExporter
from src.models.schemas import CandidateResult, PublicCandidate
from src.parser.feature_tree_parser import FeatureTreeParser
from src.rules.feature_rule_evaluator import evaluate_candidate_features
from src.utils.logging_utils import configure_logging
from src.workflow.inspection_queue import (
    CandidateQueue,
    candidate_key,
    should_continue_inspecting,
)

LOGGER = logging.getLogger(__name__)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Filter high-quality public Onshape CAD models using browser automation only."
    )
    parser.add_argument(
        "--target-inspected-count",
        type=int,
        default=100,
        help="Number of validation results to produce in this run.",
    )
    parser.add_argument(
        "--max-candidates",
        type=int,
        default=None,
        help="Deprecated compatibility alias for --max-candidates-buffer.",
    )
    parser.add_argument("--max-candidates-buffer", type=int, default=1000)
    parser.add_argument("--max-scrolls", type=int, default=300)
    parser.add_argument("--scroll-patience", type=int, default=10)
    parser.add_argument("--resume", type=_parse_bool, default=True)
    parser.add_argument("--debug-one-url", type=str, default=None)
    parser.add_argument(
        "--candidates-json",
        "--candidate-json",
        type=Path,
        default=None,
        help="Optional JSON file containing candidate Onshape document or Part Studio URLs.",
    )
    parser.add_argument("--headless", type=_parse_bool, default=False)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/results"))
    parser.add_argument("--timeout-ms", type=int, default=30_000)
    parser.add_argument("--min-active-feature-count", type=int, default=1)
    parser.add_argument("--allow-suppressed-unsupported", type=_parse_bool, default=True)
    parser.add_argument("--inspect-multiple-part-studios", type=_parse_bool, default=False)
    parser.add_argument("--max-part-studios-per-document", type=int, default=1)
    parser.add_argument("--delay-between-candidates-ms", type=int, default=2000)
    parser.add_argument("--verbose", action="store_true")
    return parser


async def run(args: argparse.Namespace) -> int:
    config = BrowserClientConfig(headless=args.headless, timeout_ms=args.timeout_ms)
    screenshot_dir = Path("outputs/screenshots")
    feature_artifact_dir = args.output_dir / "feature_artifacts"
    parser = FeatureTreeParser(strict_suppression_detection=True)
    exporter = ResultExporter(args.output_dir)
    existing_results = exporter.load_existing_results() if args.resume else []
    results: list[CandidateResult] = list(existing_results)
    key_mode = "element" if args.candidates_json else "document"
    inspected_before_run = {candidate_key(result.url, key_mode=key_mode) for result in existing_results}
    total_public_candidates_collected = 0

    if args.max_candidates is not None:
        LOGGER.warning(
            "--max-candidates is deprecated; treating it as --max-candidates-buffer for this run."
        )
    max_candidates_buffer = args.max_candidates or args.max_candidates_buffer

    async with BrowserOnshapeClient(config) as client:
        await client.ensure_logged_in()

        if args.debug_one_url:
            candidate = PublicCandidate(url=args.debug_one_url)
            debug_results = await _inspect_candidate(
                client=client,
                parser=parser,
                args=args,
                candidate=candidate,
                validation_index=1,
                screenshot_dir=screenshot_dir,
                feature_artifact_dir=feature_artifact_dir,
            )
            results.extend(debug_results)
            total_public_candidates_collected = 1
            exporter.export(results=results, total_public_candidates_collected=1)
            for result in debug_results:
                print(json.dumps(result.to_output_dict(), ensure_ascii=False, indent=2))
            return 0

        if args.candidates_json:
            file_candidates = _load_candidates_from_json(args.candidates_json)
            queue = CandidateQueue(already_inspected_keys=inspected_before_run, key_mode="element")
            added = queue.add_candidates(file_candidates, max_buffer=len(file_candidates))
            total_public_candidates_collected = len(file_candidates)
            LOGGER.info(
                "Loaded %s candidates from %s; queued %s after dedupe/resume filtering.",
                len(file_candidates),
                args.candidates_json,
                added,
            )
            inspected_this_run = 0
            validation_index = len(existing_results) + 1

            while should_continue_inspecting(
                inspected_this_run=inspected_this_run,
                target_inspected_count=args.target_inspected_count,
            ):
                candidate = queue.next_candidate()
                if candidate is None:
                    LOGGER.warning(
                        "Stopping before target: no uninspected candidates remain in %s "
                        "(inspected_this_run=%s, target=%s).",
                        args.candidates_json,
                        inspected_this_run,
                        args.target_inspected_count,
                    )
                    break

                candidate_results = await _inspect_candidate(
                    client=client,
                    parser=parser,
                    args=args,
                    candidate=candidate,
                    validation_index=validation_index,
                    screenshot_dir=screenshot_dir,
                    feature_artifact_dir=feature_artifact_dir,
                )
                validation_index += 1

                for result in candidate_results:
                    if not should_continue_inspecting(
                        inspected_this_run=inspected_this_run,
                        target_inspected_count=args.target_inspected_count,
                    ):
                        break
                    results.append(result)
                    inspected_this_run += 1
                    exporter.export(
                        results=results,
                        total_public_candidates_collected=total_public_candidates_collected,
                    )
                    LOGGER.info(
                        "Incrementally saved JSON-file result %s/%s for %s: %s.",
                        inspected_this_run,
                        args.target_inspected_count,
                        result.url,
                        result.status.value,
                    )

                if args.delay_between_candidates_ms > 0 and queue.pending_count > 0:
                    await asyncio.sleep(args.delay_between_candidates_ms / 1000)

            paths = exporter.export(
                results=results,
                total_public_candidates_collected=total_public_candidates_collected,
            )
            for name, path in paths.items():
                LOGGER.info("Wrote %s to %s", name, path)
            return 0

        await client.open_public_page()

        queue = CandidateQueue(already_inspected_keys=inspected_before_run)
        inspected_this_run = 0
        scrolls_used = 0
        no_new_scrolls = 0
        validation_index = len(existing_results) + 1

        visible_added = queue.add_candidates(
            await client.read_visible_public_candidates(),
            max_buffer=max_candidates_buffer,
        )
        LOGGER.info("Added %s visible Public candidates to the inspection queue.", visible_added)

        while should_continue_inspecting(
            inspected_this_run=inspected_this_run,
            target_inspected_count=args.target_inspected_count,
        ):
            if queue.pending_count == 0:
                await client.open_public_page()
                added = queue.add_candidates(
                    await client.read_visible_public_candidates(),
                    max_buffer=max_candidates_buffer,
                )
                if added:
                    no_new_scrolls = 0

                while (
                    queue.pending_count == 0
                    and scrolls_used < args.max_scrolls
                    and no_new_scrolls < args.scroll_patience
                ):
                    changed = await client.scroll_public_list_once()
                    scrolls_used += 1
                    await asyncio.sleep(1.0)
                    added = queue.add_candidates(
                        await client.read_visible_public_candidates(),
                        max_buffer=max_candidates_buffer,
                    )
                    if added:
                        LOGGER.info(
                            "Added %s new candidates after Public scroll %s/%s.",
                            added,
                            scrolls_used,
                            args.max_scrolls,
                        )
                        no_new_scrolls = 0
                        break
                    no_new_scrolls += 1
                    LOGGER.info(
                        "Public scroll %s/%s added no new candidates (patience %s/%s, changed=%s).",
                        scrolls_used,
                        args.max_scrolls,
                        no_new_scrolls,
                        args.scroll_patience,
                        changed,
                    )

                if queue.pending_count == 0:
                    LOGGER.warning(
                        "Stopping before target: no uninspected candidates remain "
                        "(inspected_this_run=%s, target=%s, scrolls_used=%s).",
                        inspected_this_run,
                        args.target_inspected_count,
                        scrolls_used,
                    )
                    break

            candidate = queue.next_candidate()
            if candidate is None:
                continue

            candidate_results = await _inspect_candidate(
                client=client,
                parser=parser,
                args=args,
                candidate=candidate,
                validation_index=validation_index,
                screenshot_dir=screenshot_dir,
                feature_artifact_dir=feature_artifact_dir,
            )
            validation_index += 1

            for result in candidate_results:
                if not should_continue_inspecting(
                    inspected_this_run=inspected_this_run,
                    target_inspected_count=args.target_inspected_count,
                ):
                    break
                results.append(result)
                inspected_this_run += 1
                exporter.export(
                    results=results,
                    total_public_candidates_collected=queue.unique_seen_count,
                )
                LOGGER.info(
                    "Incrementally saved result %s/%s for %s: %s.",
                    inspected_this_run,
                    args.target_inspected_count,
                    result.url,
                    result.status.value,
                )

            if args.delay_between_candidates_ms > 0:
                await asyncio.sleep(args.delay_between_candidates_ms / 1000)

        total_public_candidates_collected = queue.unique_seen_count

    paths = exporter.export(
        results=results,
        total_public_candidates_collected=total_public_candidates_collected,
    )
    for name, path in paths.items():
        LOGGER.info("Wrote %s to %s", name, path)
    return 0


async def _inspect_candidate(
    *,
    client: BrowserOnshapeClient,
    parser: FeatureTreeParser,
    args: argparse.Namespace,
    candidate: PublicCandidate,
    validation_index: int,
    screenshot_dir: Path,
    feature_artifact_dir: Path,
) -> list[CandidateResult]:
    try:
        inspections = await client.inspect_candidate(
            url=candidate.url,
            document_name=candidate.document_name,
            document_id=candidate.document_id,
            candidate_index=validation_index,
            screenshot_dir=screenshot_dir,
            inspect_multiple_part_studios=args.inspect_multiple_part_studios,
            max_part_studios_per_document=max(1, args.max_part_studios_per_document),
            feature_artifact_dir=feature_artifact_dir,
        )
    except Exception as exc:
        LOGGER.exception("Candidate inspection failed for %s", candidate.url)
        return [
            evaluate_candidate_features(
                url=candidate.url,
                document_name=candidate.document_name,
                part_studio_name=None,
                features=[],
                extraction_reliable=False,
                extraction_warnings=[f"candidate inspection failed: {exc}"],
                min_active_feature_count=args.min_active_feature_count,
            )
        ]

    results: list[CandidateResult] = []
    for inspection in inspections:
        parse_result = parser.parse_feature_tree(inspection.raw_feature_items)
        warnings = [*inspection.warnings, *parse_result.warnings]
        _write_extracted_features_json(
            path=inspection.extracted_features_path,
            inspection=inspection,
            features=parse_result.features,
            warnings=warnings,
        )
        result = evaluate_candidate_features(
            url=inspection.candidate.url,
            document_name=inspection.candidate.document_name,
            part_studio_name=inspection.part_studio_name,
            features=parse_result.features,
            extraction_reliable=not warnings,
            extraction_warnings=warnings,
            screenshot_path=inspection.screenshot_path,
            feature_folders=inspection.feature_folders,
            min_active_feature_count=args.min_active_feature_count,
            allow_suppressed_unsupported=args.allow_suppressed_unsupported,
        )
        LOGGER.info("Result for %s: %s - %s", inspection.candidate.url, result.status.value, result.reason)
        results.append(result)
    return results


def _write_extracted_features_json(
    *,
    path: str | None,
    inspection: object,
    features: list[object],
    warnings: list[str],
) -> None:
    if path is None:
        return
    feature_path = Path(path)
    feature_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "url": inspection.candidate.url,
        "document_name": inspection.candidate.document_name,
        "part_studio_name": inspection.part_studio_name,
        "feature_count": len(features),
        "feature_folders": inspection.feature_folders,
        "warnings": warnings,
        "feature_tree_before_screenshot_path": inspection.feature_tree_before_screenshot_path,
        "feature_tree_after_screenshot_path": inspection.feature_tree_after_screenshot_path,
        "features": [feature.model_dump(mode="json") for feature in features],
    }
    feature_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_candidates_from_json(path: Path) -> list[PublicCandidate]:
    if not path.exists():
        raise RuntimeError(f"Candidate JSON file not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Candidate JSON file is not valid JSON: {path}") from exc

    if isinstance(payload, dict):
        if isinstance(payload.get("candidates"), list):
            entries = payload["candidates"]
        elif isinstance(payload.get("urls"), list):
            entries = payload["urls"]
        else:
            raise RuntimeError(
                "Candidate JSON object must contain a list under 'candidates' or 'urls'."
            )
    elif isinstance(payload, list):
        entries = payload
    else:
        raise RuntimeError("Candidate JSON must be a list, or an object with 'candidates' or 'urls'.")

    candidates: list[PublicCandidate] = []
    for index, entry in enumerate(entries, start=1):
        document_name: str | None = None
        document_id: str | None = None
        if isinstance(entry, str):
            url = entry.strip()
        elif isinstance(entry, dict):
            raw_url = entry.get("url") or entry.get("link")
            if not isinstance(raw_url, str):
                raise RuntimeError(f"Candidate JSON entry {index} is missing a string 'url' field.")
            url = raw_url.strip()
            raw_name = entry.get("document_name") or entry.get("name")
            if isinstance(raw_name, str) and raw_name.strip():
                document_name = raw_name.strip()
            raw_document_id = entry.get("document_id")
            if isinstance(raw_document_id, str) and raw_document_id.strip():
                document_id = raw_document_id.strip()
        else:
            raise RuntimeError(f"Candidate JSON entry {index} must be a URL string or object.")

        if not url:
            raise RuntimeError(f"Candidate JSON entry {index} has an empty URL.")
        if "/documents/" not in url:
            raise RuntimeError(f"Candidate JSON entry {index} is not an Onshape document URL: {url}")
        candidates.append(
            PublicCandidate(url=url, document_name=document_name, document_id=document_id)
        )

    if not candidates:
        raise RuntimeError(f"Candidate JSON file contains no candidates: {path}")
    return candidates


def main() -> int:
    load_dotenv(dotenv_path=Path.cwd() / ".env")
    args = build_arg_parser().parse_args()
    configure_logging(verbose=args.verbose)
    if args.debug_one_url and args.candidates_json:
        print(
            "--debug-one-url and --candidates-json cannot be used together.",
            file=sys.stderr,
        )
        return 2
    missing = [
        name
        for name in ("ONSHAPE_EMAIL", "ONSHAPE_PASSWORD")
        if not os.getenv(name)
    ]
    if missing:
        print(
            "Missing required environment variables: "
            + ", ".join(missing)
            + ". Add them to .env or your shell environment.",
            file=sys.stderr,
        )
        return 2
    return asyncio.run(run(args))


def _parse_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"Expected true or false, got {value!r}")


if __name__ == "__main__":
    raise SystemExit(main())
