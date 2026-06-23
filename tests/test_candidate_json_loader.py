from __future__ import annotations

import json

import pytest

from src.main import _load_candidates_from_json


def test_load_candidate_json_string_list(tmp_path) -> None:
    path = tmp_path / "candidates.json"
    path.write_text(
        json.dumps(
            [
                "https://cad.onshape.com/documents/doc1/w/workspace1",
                "https://cad.onshape.com/documents/doc2/w/workspace2/e/element2",
            ]
        ),
        encoding="utf-8",
    )

    candidates = _load_candidates_from_json(path)

    assert [candidate.url for candidate in candidates] == [
        "https://cad.onshape.com/documents/doc1/w/workspace1",
        "https://cad.onshape.com/documents/doc2/w/workspace2/e/element2",
    ]


def test_load_candidate_json_object_list(tmp_path) -> None:
    path = tmp_path / "candidates.json"
    path.write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "url": "https://cad.onshape.com/documents/doc1/w/workspace1/e/element1",
                        "document_name": "Example",
                        "document_id": "doc1",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    candidates = _load_candidates_from_json(path)

    assert len(candidates) == 1
    assert candidates[0].url.endswith("/element1")
    assert candidates[0].document_name == "Example"
    assert candidates[0].document_id == "doc1"


def test_load_candidate_json_rejects_non_onshape_entries(tmp_path) -> None:
    path = tmp_path / "candidates.json"
    path.write_text(json.dumps(["https://example.com/not-onshape"]), encoding="utf-8")

    with pytest.raises(RuntimeError, match="not an Onshape document URL"):
        _load_candidates_from_json(path)
