from __future__ import annotations

from src.models.schemas import CandidateStatus, Feature
from src.rules.feature_rule_evaluator import evaluate_candidate_features


def feature(
    feature_type: str,
    *,
    index: int = 1,
    is_suppressed: bool = False,
    has_error: bool = False,
    suppression_state_known: bool = True,
) -> Feature:
    return Feature(
        index=index,
        raw_text=f"{feature_type} {index}",
        feature_name=f"{feature_type} {index}",
        feature_type=feature_type,
        is_suppressed=is_suppressed,
        has_error=has_error,
        is_import=feature_type == "Import",
        is_derived=feature_type == "Derived",
        suppression_state_known=suppression_state_known,
    )


def test_allowed_active_features_pass_and_count_histogram() -> None:
    result = evaluate_candidate_features(
        url="https://cad.onshape.com/documents/doc1",
        features=[feature("Sketch", index=1), feature("Extrude", index=2), feature("Fillet", index=3)],
    )

    assert result.status == CandidateStatus.PASSED
    assert result.active_feature_histogram["Sketch"] == 1
    assert result.active_feature_histogram["Extrude"] == 1
    assert result.active_feature_histogram["Fillet"] == 1
    assert not result.active_unsupported_features


def test_active_import_rejects_candidate() -> None:
    result = evaluate_candidate_features(
        url="https://cad.onshape.com/documents/doc1",
        features=[feature("Sketch", index=1), feature("Import", index=2)],
    )

    assert result.status == CandidateStatus.REJECTED
    assert result.has_active_import is True
    assert "active Import feature found" in result.reason


def test_active_derived_rejects_candidate() -> None:
    result = evaluate_candidate_features(
        url="https://cad.onshape.com/documents/doc1",
        features=[feature("Derived")],
    )

    assert result.status == CandidateStatus.REJECTED
    assert result.has_active_derived is True
    assert "active Derived feature found" in result.reason


def test_active_unsupported_feature_rejects_candidate() -> None:
    result = evaluate_candidate_features(
        url="https://cad.onshape.com/documents/doc1",
        features=[feature("Hole")],
    )

    assert result.status == CandidateStatus.REJECTED
    assert result.active_unsupported_features[0].feature_type == "Hole"
    assert "active unsupported feature found" in result.reason


def test_active_error_rejects_even_for_allowed_feature() -> None:
    result = evaluate_candidate_features(
        url="https://cad.onshape.com/documents/doc1",
        features=[feature("Extrude", has_error=True)],
    )

    assert result.status == CandidateStatus.REJECTED
    assert result.has_active_error is True
    assert "active feature has error status" in result.reason


def test_suppressed_unsupported_feature_is_recorded_but_allowed_by_default() -> None:
    result = evaluate_candidate_features(
        url="https://cad.onshape.com/documents/doc1",
        features=[feature("Sketch", index=1), feature("Shell", index=2, is_suppressed=True)],
    )

    assert result.status == CandidateStatus.PASSED
    assert result.suppressed_unsupported_features[0].feature_type == "Shell"
    assert not result.active_unsupported_features


def test_suppressed_unsupported_feature_can_be_disallowed() -> None:
    result = evaluate_candidate_features(
        url="https://cad.onshape.com/documents/doc1",
        features=[feature("Sketch", index=1), feature("Shell", index=2, is_suppressed=True)],
        allow_suppressed_unsupported=False,
    )

    assert result.status == CandidateStatus.REJECTED
    assert "suppressed unsupported feature is disallowed" in result.reason


def test_unknown_suppression_state_marks_candidate_uncertain() -> None:
    result = evaluate_candidate_features(
        url="https://cad.onshape.com/documents/doc1",
        features=[feature("Sketch", suppression_state_known=False)],
    )

    assert result.status == CandidateStatus.UNCERTAIN
    assert "Suppression state could not be determined" in result.reason


def test_unreliable_extraction_marks_candidate_uncertain() -> None:
    result = evaluate_candidate_features(
        url="https://cad.onshape.com/documents/doc1",
        features=[],
        extraction_reliable=False,
        extraction_warnings=["No feature tree rows were extracted from the page."],
    )

    assert result.status == CandidateStatus.UNCERTAIN
    assert "Feature tree extraction unreliable" in result.reason


def test_feature_tree_folders_reject_even_when_features_are_allowed() -> None:
    result = evaluate_candidate_features(
        url="https://cad.onshape.com/documents/doc1/w/workspace1/e/element1",
        features=[feature("Sketch", index=1), feature("Extrude", index=2)],
        feature_folders=["Base (8)", "Driven Gear (6)"],
    )

    assert result.status == CandidateStatus.REJECTED
    assert result.has_feature_folders is True
    assert result.feature_folders == ["Base (8)", "Driven Gear (6)"]
    assert "feature tree contains folders" in result.reason


def test_feature_tree_folders_reject_before_unreliable_extraction() -> None:
    result = evaluate_candidate_features(
        url="https://cad.onshape.com/documents/doc1/w/workspace1/e/element1",
        features=[],
        extraction_reliable=False,
        extraction_warnings=["Feature tree extraction incomplete."],
        feature_folders=["Base (8)"],
    )

    assert result.status == CandidateStatus.REJECTED
    assert result.has_feature_folders is True
    assert result.reason == "feature tree contains folders: Base (8)"


def test_min_active_feature_count_rejects_reliable_empty_models() -> None:
    result = evaluate_candidate_features(
        url="https://cad.onshape.com/documents/doc1",
        features=[],
        extraction_reliable=True,
        min_active_feature_count=1,
    )

    assert result.status == CandidateStatus.REJECTED
    assert "below minimum" in result.reason
