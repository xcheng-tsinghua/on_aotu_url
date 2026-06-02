from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from src.models.schemas import Feature, FeatureTreeParseResult


FEATURE_TYPE_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("CPlane", (r"\bc\s*plane\b", r"\bcplane\b", r"\bconstruction\s+plane\b")),
    ("Sketch", (r"\bsketch\b",)),
    ("Extrude", (r"\bextrude\b",)),
    ("Revolve", (r"\brevolve\b",)),
    ("Sweep", (r"\bsweep\b",)),
    ("Loft", (r"\bloft\b",)),
    ("Chamfer", (r"\bchamfer\b",)),
    ("Fillet", (r"\bfillet\b",)),
    ("Plane", (r"\bplane\b",)),
    ("Import", (r"\bimport\b",)),
    ("Derived", (r"\bderived\b",)),
    ("Hole", (r"\bhole\b",)),
    ("Shell", (r"\bshell\b",)),
    ("Pattern", (r"\bpattern\b", r"\blinear\s+pattern\b", r"\bcircular\s+pattern\b")),
    ("Mirror", (r"\bmirror\b",)),
    ("Boolean", (r"\bboolean\b",)),
)

SUPPRESSED_PATTERNS = (
    r"\bsuppressed\b",
    r"\bis-suppressed\b",
    r"\bfeature-suppressed\b",
    r"\bdisabled\b",
    r"\bline-through\b",
)

ERROR_PATTERNS = (
    r"\berror\b",
    r"\bfailed\b",
    r"\bfail\b",
    r"\bregen(?:eration)?\s+failed\b",
    r"\binvalid\b",
    r"\bwarning\b",
)

STATE_EVIDENCE_KEYS = (
    "aria_label",
    "aria-label",
    "title",
    "class_name",
    "class",
    "style",
    "data_suppressed",
    "data-suppressed",
)


class FeatureTreeParser:
    """Parse DOM-derived Onshape feature rows into deterministic feature records."""

    def __init__(self, strict_suppression_detection: bool = False) -> None:
        self.strict_suppression_detection = strict_suppression_detection

    def parse_feature_tree(self, raw_items: list[Mapping[str, Any] | str]) -> FeatureTreeParseResult:
        warnings: list[str] = []
        features: list[Feature] = []

        if not raw_items:
            return FeatureTreeParseResult(
                features=[],
                warnings=["No feature tree rows were extracted from the page."],
            )

        for index, item in enumerate(raw_items, start=1):
            try:
                feature = self.parse_feature(index=index, item=item)
            except ValueError as exc:
                warnings.append(f"Feature row {index} could not be parsed: {exc}")
                continue

            if not feature.suppression_state_known:
                warnings.append(
                    f"Suppression state could not be determined for feature {index}: "
                    f"{feature.feature_name}"
                )
            features.append(feature)

        if not features:
            warnings.append("No readable features remained after parsing feature rows.")
        elif self._looks_like_feature_tree_header_only(features):
            warnings.append(
                "Only the feature tree header was extracted; individual features were not read reliably."
            )

        return FeatureTreeParseResult(features=features, warnings=warnings)

    def parse_feature(self, index: int, item: Mapping[str, Any] | str) -> Feature:
        entry = self._coerce_entry(item)
        raw_text = self._clean_text(str(entry.get("raw_text") or ""))
        labels = self._combined_evidence(entry)

        if not raw_text and not labels:
            raise ValueError("empty feature text and metadata")

        feature_name = raw_text or self._clean_text(labels)
        feature_type = self.normalize_feature_type(
            str(entry.get("feature_type") or entry.get("data_feature_type") or labels or raw_text)
        )
        is_suppressed = self._has_any_pattern(labels, SUPPRESSED_PATTERNS)
        has_error = self._has_any_pattern(labels, ERROR_PATTERNS)
        suppression_state_known = self._suppression_state_is_known(entry, is_suppressed)

        return Feature(
            index=index,
            raw_text=raw_text or labels,
            feature_name=feature_name,
            feature_type=feature_type,
            is_suppressed=is_suppressed,
            has_error=has_error,
            is_import=feature_type == "Import",
            is_derived=feature_type == "Derived",
            suppression_state_known=suppression_state_known,
        )

    @staticmethod
    def normalize_feature_type(text: str) -> str:
        cleaned = FeatureTreeParser._clean_text(text)
        for normalized, patterns in FEATURE_TYPE_PATTERNS:
            if any(re.search(pattern, cleaned, flags=re.IGNORECASE) for pattern in patterns):
                return normalized
        return "Unknown"

    @staticmethod
    def _coerce_entry(item: Mapping[str, Any] | str) -> dict[str, Any]:
        if isinstance(item, str):
            return {"raw_text": item}
        return dict(item)

    @staticmethod
    def _clean_text(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _has_any_pattern(text: str, patterns: tuple[str, ...]) -> bool:
        return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)

    def _combined_evidence(self, entry: Mapping[str, Any]) -> str:
        values: list[str] = []
        for key, value in entry.items():
            if value is None:
                continue
            if isinstance(value, Mapping):
                values.extend(str(inner_value) for inner_value in value.values() if inner_value is not None)
            elif isinstance(value, (list, tuple, set)):
                values.extend(str(inner_value) for inner_value in value if inner_value is not None)
            elif isinstance(value, (str, int, float, bool)):
                values.append(str(value))
        return self._clean_text(" ".join(values))

    def _suppression_state_is_known(self, entry: Mapping[str, Any], is_suppressed: bool) -> bool:
        if not self.strict_suppression_detection:
            return True
        if is_suppressed:
            return True
        return any(entry.get(key) not in (None, "") for key in STATE_EVIDENCE_KEYS)

    @staticmethod
    def _looks_like_feature_tree_header_only(features: list[Feature]) -> bool:
        if len(features) != 1:
            return False
        text = features[0].raw_text.strip()
        return bool(re.fullmatch(r"Features\s*\(\d+\)", text, flags=re.IGNORECASE))
