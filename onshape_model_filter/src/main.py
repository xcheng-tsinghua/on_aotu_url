from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from src.browser.onshape_browser import BrowserClientConfig, BrowserOnshapeClient
from src.export.result_exporter import ResultExporter
from src.models.schemas import CandidateResult, PublicCandidate
from src.parser.feature_tree_parser import FeatureTreeParser
from src.rules.feature_rule_evaluator import evaluate_candidate_features
from src.utils.logging_utils import configure_logging

LOGGER = logging.getLogger(__name__)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Filter high-quality public Onshape CAD models using browser automation only."
    )
    parser.add_argument("--max-candidates", type=int, default=100)
    parser.add_argument("--max-scrolls", type=int, default=30)
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
    parser = FeatureTreeParser(strict_suppression_detection=True)
    results: list[CandidateResult] = []
    candidates: list[PublicCandidate] = []

    async with BrowserOnshapeClient(config) as client:
        await client.open_onshape()
        await client.wait_for_login()
        await client.open_public_page()
        candidates = await client.collect_public_candidates(
            max_candidates=args.max_candidates,
            max_scrolls=args.max_scrolls,
        )

        LOGGER.info("Collected %s total public candidates.", len(candidates))
        for index, candidate in enumerate(candidates, start=1):
            try:
                inspections = await client.inspect_candidate(
                    candidate=candidate,
                    candidate_index=index,
                    screenshot_dir=screenshot_dir,
                    inspect_multiple_part_studios=args.inspect_multiple_part_studios,
                    max_part_studios_per_document=max(1, args.max_part_studios_per_document),
                )
            except Exception as exc:
                LOGGER.exception("Candidate inspection failed for %s", candidate.url)
                inspections = []
                results.append(
                    evaluate_candidate_features(
                        url=candidate.url,
                        document_name=candidate.document_name,
                        part_studio_name=None,
                        features=[],
                        extraction_reliable=False,
                        extraction_warnings=[f"candidate inspection failed: {exc}"],
                        min_active_feature_count=args.min_active_feature_count,
                    )
                )

            for inspection in inspections:
                parse_result = parser.parse_feature_tree(inspection.raw_feature_items)
                warnings = [*inspection.warnings, *parse_result.warnings]
                result = evaluate_candidate_features(
                    url=candidate.url,
                    document_name=candidate.document_name,
                    part_studio_name=inspection.part_studio_name,
                    features=parse_result.features,
                    extraction_reliable=not warnings,
                    extraction_warnings=warnings,
                    screenshot_path=inspection.screenshot_path,
                    min_active_feature_count=args.min_active_feature_count,
                    allow_suppressed_unsupported=args.allow_suppressed_unsupported,
                )
                LOGGER.info("Result for %s: %s - %s", candidate.url, result.status.value, result.reason)
                results.append(result)

            if args.delay_between_candidates_ms > 0:
                await asyncio.sleep(args.delay_between_candidates_ms / 1000)

    exporter = ResultExporter(args.output_dir)
    paths = exporter.export(
        results=results,
        total_public_candidates_collected=len(candidates),
    )
    for name, path in paths.items():
        LOGGER.info("Wrote %s to %s", name, path)
    return 0


def main() -> int:
    args = build_arg_parser().parse_args()
    configure_logging(verbose=args.verbose)
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
