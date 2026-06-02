from __future__ import annotations

import pytest

from src.parser.feature_tree_parser import FeatureTreeParser


@pytest.mark.parametrize(
    ("raw_text", "expected"),
    [
        ("Sketch 1", "Sketch"),
        ("extrude 1", "Extrude"),
        ("Revolve - main body", "Revolve"),
        ("SWEEP 2", "Sweep"),
        ("Loft 1", "Loft"),
        ("Chamfer 1", "Chamfer"),
        ("Fillet 1", "Fillet"),
        ("Plane 1", "Plane"),
        ("CPlane 1", "CPlane"),
        ("Import 1", "Import"),
        ("Derived 1", "Derived"),
        ("Hole 1", "Hole"),
        ("Shell 1", "Shell"),
        ("Pattern 1", "Pattern"),
        ("Mirror 1", "Mirror"),
        ("Boolean 1", "Boolean"),
    ],
)
def test_normalizes_feature_types_case_insensitively(raw_text: str, expected: str) -> None:
    assert FeatureTreeParser.normalize_feature_type(raw_text) == expected


def test_parse_feature_detects_suppressed_and_error_state() -> None:
    parser = FeatureTreeParser(strict_suppression_detection=True)

    result = parser.parse_feature_tree(
        [
            {
                "raw_text": "Shell 1",
                "aria_label": "Shell 1 suppressed",
                "class_name": "feature-row is-suppressed",
            },
            {
                "raw_text": "Extrude 1",
                "title": "Failed regeneration error",
                "class_name": "feature-row feature-error",
            },
        ]
    )

    assert result.reliable
    assert result.features[0].is_suppressed is True
    assert result.features[0].feature_type == "Shell"
    assert result.features[1].has_error is True
    assert result.features[1].feature_type == "Extrude"


def test_strict_parser_marks_missing_suppression_evidence_unreliable() -> None:
    parser = FeatureTreeParser(strict_suppression_detection=True)

    result = parser.parse_feature_tree(["Sketch 1"])

    assert not result.reliable
    assert "Suppression state could not be determined" in result.warnings[0]


def test_empty_feature_tree_is_unreliable() -> None:
    parser = FeatureTreeParser()

    result = parser.parse_feature_tree([])

    assert not result.reliable
    assert result.features == []


def test_header_only_feature_tree_is_unreliable() -> None:
    parser = FeatureTreeParser()

    result = parser.parse_feature_tree(["Features (88)"])

    assert not result.reliable
    assert "Only the feature tree header" in result.warnings[0]
