from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from src.models.schemas import CandidateResult, CandidateStatus
from src.rules.feature_rule_evaluator import rejection_reason_histogram


class ResultExporter:
    def __init__(self, output_dir: str | Path) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def export(
        self,
        *,
        results: list[CandidateResult],
        total_public_candidates_collected: int,
        source: str = "Onshape Public list",
    ) -> dict[str, Path]:
        passed = [result for result in results if result.status == CandidateStatus.PASSED]
        rejected = [result for result in results if result.status == CandidateStatus.REJECTED]
        uncertain = [result for result in results if result.status == CandidateStatus.UNCERTAIN]

        paths = {
            "passed_candidates": self.output_dir / "passed_candidates.json",
            "rejected_candidates": self.output_dir / "rejected_candidates.json",
            "uncertain_candidates": self.output_dir / "uncertain_candidates.json",
            "all_candidates": self.output_dir / "all_candidates.csv",
            "summary": self.output_dir / "summary.json",
        }

        self._write_json(paths["passed_candidates"], passed)
        self._write_json(paths["rejected_candidates"], rejected)
        self._write_json(paths["uncertain_candidates"], uncertain)
        self._write_csv(paths["all_candidates"], results)
        self._write_summary(
            paths["summary"],
            results=results,
            total_public_candidates_collected=total_public_candidates_collected,
            source=source,
        )
        return paths

    def load_existing_results(self) -> list[CandidateResult]:
        results: list[CandidateResult] = []
        for filename in (
            "passed_candidates.json",
            "rejected_candidates.json",
            "uncertain_candidates.json",
        ):
            path = self.output_dir / filename
            if not path.exists():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, list):
                continue
            for item in payload:
                try:
                    results.append(CandidateResult.model_validate(item))
                except Exception:
                    continue
        return results

    def _write_json(self, path: Path, results: list[CandidateResult]) -> None:
        payload = [result.to_output_dict() for result in results]
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def _write_csv(self, path: Path, results: list[CandidateResult]) -> None:
        fieldnames = [
            "url",
            "document_name",
            "part_studio_name",
            "status",
            "reason",
            "active_feature_histogram",
            "active_unsupported_features",
            "suppressed_unsupported_features",
            "has_active_import",
            "has_active_derived",
            "has_active_error",
            "has_feature_folders",
            "feature_folders",
            "screenshot_path",
        ]
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for result in results:
                row = result.to_output_dict()
                row["active_feature_histogram"] = json.dumps(
                    row["active_feature_histogram"], ensure_ascii=False, sort_keys=True
                )
                row["active_unsupported_features"] = json.dumps(
                    row["active_unsupported_features"], ensure_ascii=False
                )
                row["suppressed_unsupported_features"] = json.dumps(
                    row["suppressed_unsupported_features"], ensure_ascii=False
                )
                row["feature_folders"] = json.dumps(row["feature_folders"], ensure_ascii=False)
                writer.writerow(row)

    def _write_summary(
        self,
        path: Path,
        *,
        results: list[CandidateResult],
        total_public_candidates_collected: int,
        source: str,
    ) -> None:
        total_inspected = len(results)
        num_passed = sum(1 for result in results if result.status == CandidateStatus.PASSED)
        num_rejected = sum(1 for result in results if result.status == CandidateStatus.REJECTED)
        num_uncertain = sum(1 for result in results if result.status == CandidateStatus.UNCERTAIN)
        summary: dict[str, Any] = {
            "source": source,
            "total_public_candidates_collected": total_public_candidates_collected,
            "total_inspected": total_inspected,
            "num_passed": num_passed,
            "num_rejected": num_rejected,
            "num_uncertain": num_uncertain,
            "pass_rate": num_passed / total_inspected if total_inspected else 0.0,
            "rejection_reason_histogram": rejection_reason_histogram(results),
        }
        path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
