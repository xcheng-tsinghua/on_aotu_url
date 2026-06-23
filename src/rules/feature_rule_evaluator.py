from __future__ import annotations

from collections import Counter

from src.models.schemas import (
    ALLOWED_ACTIVE_FEATURE_TYPES,
    CandidateResult,
    CandidateStatus,
    Feature,
    UnsupportedFeature,
)


def evaluate_candidate_features(
    *,
    url: str,
    features: list[Feature],
    document_name: str | None = None,
    part_studio_name: str | None = None,
    extraction_reliable: bool = True,
    extraction_warnings: list[str] | None = None,
    screenshot_path: str | None = None,
    feature_folders: list[str] | None = None,
    min_active_feature_count: int = 1,
    allow_suppressed_unsupported: bool = True,
) -> CandidateResult:
    """Evaluate an Onshape Part Studio feature list with deterministic rules."""

    warnings = extraction_warnings or []
    detected_feature_folders = feature_folders or []
    histogram = _empty_histogram()
    active_unsupported: list[UnsupportedFeature] = []
    suppressed_unsupported: list[UnsupportedFeature] = []
    rejection_reasons: list[str] = []
    active_feature_count = 0
    has_active_import = False
    has_active_derived = False
    has_active_error = False

    if detected_feature_folders:
        return _result(
            url=url,
            document_name=document_name,
            part_studio_name=part_studio_name,
            status=CandidateStatus.REJECTED,
            reason="feature tree contains folders: " + ", ".join(detected_feature_folders),
            histogram=histogram,
            active_unsupported=active_unsupported,
            suppressed_unsupported=suppressed_unsupported,
            has_active_import=False,
            has_active_derived=False,
            has_active_error=False,
            has_feature_folders=True,
            feature_folders=detected_feature_folders,
            screenshot_path=screenshot_path,
        )

    if not extraction_reliable:
        return _result(
            url=url,
            document_name=document_name,
            part_studio_name=part_studio_name,
            status=CandidateStatus.UNCERTAIN,
            reason=_format_uncertain_reason(warnings),
            histogram=histogram,
            active_unsupported=active_unsupported,
            suppressed_unsupported=suppressed_unsupported,
            has_active_import=False,
            has_active_derived=False,
            has_active_error=False,
            has_feature_folders=False,
            feature_folders=detected_feature_folders,
            screenshot_path=screenshot_path,
        )

    unknown_state_features = [feature for feature in features if not feature.suppression_state_known]
    if unknown_state_features:
        names = ", ".join(_feature_label(feature) for feature in unknown_state_features[:5])
        return _result(
            url=url,
            document_name=document_name,
            part_studio_name=part_studio_name,
            status=CandidateStatus.UNCERTAIN,
            reason=f"Suppression state could not be determined reliably for: {names}",
            histogram=histogram,
            active_unsupported=active_unsupported,
            suppressed_unsupported=suppressed_unsupported,
            has_active_import=False,
            has_active_derived=False,
            has_active_error=False,
            has_feature_folders=False,
            feature_folders=detected_feature_folders,
            screenshot_path=screenshot_path,
        )

    for feature in features:
        unsupported = _unsupported_feature(feature)

        if feature.is_suppressed:
            if feature.feature_type not in ALLOWED_ACTIVE_FEATURE_TYPES:
                suppressed_unsupported.append(unsupported)
                if not allow_suppressed_unsupported:
                    rejection_reasons.append(
                        f"suppressed unsupported feature is disallowed: {_feature_label(feature)}"
                    )
            continue

        active_feature_count += 1

        if feature.has_error:
            has_active_error = True
            rejection_reasons.append(f"active feature has error status: {_feature_label(feature)}")

        if feature.is_import or feature.feature_type == "Import":
            has_active_import = True
            active_unsupported.append(unsupported)
            rejection_reasons.append(f"active Import feature found: {_feature_label(feature)}")
            continue

        if feature.is_derived or feature.feature_type == "Derived":
            has_active_derived = True
            active_unsupported.append(unsupported)
            rejection_reasons.append(f"active Derived feature found: {_feature_label(feature)}")
            continue

        if feature.feature_type not in ALLOWED_ACTIVE_FEATURE_TYPES:
            active_unsupported.append(unsupported)
            rejection_reasons.append(
                f"active unsupported feature found: {_feature_label(feature)}"
            )
            continue

        histogram[feature.feature_type] += 1

    if active_feature_count < min_active_feature_count:
        rejection_reasons.append(
            f"active feature count {active_feature_count} is below minimum {min_active_feature_count}"
        )

    if rejection_reasons:
        return _result(
            url=url,
            document_name=document_name,
            part_studio_name=part_studio_name,
            status=CandidateStatus.REJECTED,
            reason="; ".join(dict.fromkeys(rejection_reasons)),
            histogram=histogram,
            active_unsupported=active_unsupported,
            suppressed_unsupported=suppressed_unsupported,
            has_active_import=has_active_import,
            has_active_derived=has_active_derived,
            has_active_error=has_active_error,
            has_feature_folders=False,
            feature_folders=detected_feature_folders,
            screenshot_path=screenshot_path,
        )

    return _result(
        url=url,
        document_name=document_name,
        part_studio_name=part_studio_name,
        status=CandidateStatus.PASSED,
        reason="All active, unsuppressed features are in the allowed whitelist.",
        histogram=histogram,
        active_unsupported=active_unsupported,
        suppressed_unsupported=suppressed_unsupported,
        has_active_import=has_active_import,
        has_active_derived=has_active_derived,
        has_active_error=has_active_error,
        has_feature_folders=False,
        feature_folders=detected_feature_folders,
        screenshot_path=screenshot_path,
    )


def rejection_reason_histogram(results: list[CandidateResult]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for result in results:
        if result.status != CandidateStatus.REJECTED:
            continue
        for reason in result.reason.split("; "):
            counts[reason] += 1
    return dict(counts)


def _empty_histogram() -> dict[str, int]:
    return {feature_type: 0 for feature_type in ALLOWED_ACTIVE_FEATURE_TYPES}


def _unsupported_feature(feature: Feature) -> UnsupportedFeature:
    return UnsupportedFeature(
        index=feature.index,
        feature_name=feature.feature_name,
        feature_type=feature.feature_type,
        raw_text=feature.raw_text,
    )


def _feature_label(feature: Feature) -> str:
    return f"{feature.feature_type} at index {feature.index} ({feature.feature_name})"


def _format_uncertain_reason(warnings: list[str]) -> str:
    if warnings:
        return "Feature tree extraction unreliable: " + "; ".join(warnings)
    return "Feature tree extraction unreliable."


def _result(
    *,
    url: str,
    document_name: str | None,
    part_studio_name: str | None,
    status: CandidateStatus,
    reason: str,
    histogram: dict[str, int],
    active_unsupported: list[UnsupportedFeature],
    suppressed_unsupported: list[UnsupportedFeature],
    has_active_import: bool,
    has_active_derived: bool,
    has_active_error: bool,
    has_feature_folders: bool,
    feature_folders: list[str],
    screenshot_path: str | None,
) -> CandidateResult:
    return CandidateResult(
        url=url,
        document_name=document_name,
        part_studio_name=part_studio_name,
        status=status,
        reason=reason,
        active_feature_histogram=histogram,
        active_unsupported_features=active_unsupported,
        suppressed_unsupported_features=suppressed_unsupported,
        has_active_import=has_active_import,
        has_active_derived=has_active_derived,
        has_active_error=has_active_error,
        has_feature_folders=has_feature_folders,
        feature_folders=feature_folders,
        screenshot_path=screenshot_path,
    )
