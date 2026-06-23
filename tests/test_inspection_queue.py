from __future__ import annotations

from src.models.schemas import PublicCandidate
from src.workflow.inspection_queue import (
    CandidateQueue,
    candidate_key,
    should_continue_inspecting,
)


def test_target_inspected_count_stopping_logic() -> None:
    assert should_continue_inspecting(inspected_this_run=0, target_inspected_count=2)
    assert should_continue_inspecting(inspected_this_run=1, target_inspected_count=2)
    assert not should_continue_inspecting(inspected_this_run=2, target_inspected_count=2)
    assert not should_continue_inspecting(inspected_this_run=3, target_inspected_count=2)


def test_candidate_deduplication_prefers_document_id() -> None:
    queue = CandidateQueue()
    added = queue.add_candidates(
        [
            PublicCandidate(
                url="https://cad.onshape.com/documents/doc1/w/workspace1",
                document_name="A",
            ),
            PublicCandidate(
                url="https://cad.onshape.com/documents/doc1/w/workspace2",
                document_name="A duplicate",
            ),
            PublicCandidate(
                url="https://cad.onshape.com/documents/doc2/w/workspace1",
                document_name="B",
            ),
        ],
        max_buffer=10,
    )

    assert added == 2
    assert queue.pending_count == 2
    assert queue.next_candidate().document_name == "A"
    assert queue.next_candidate().document_name == "B"
    assert queue.next_candidate() is None


def test_candidate_queue_skips_resume_keys() -> None:
    inspected_key = candidate_key("https://cad.onshape.com/documents/doc1/w/workspace1")
    queue = CandidateQueue(already_inspected_keys={inspected_key})

    added = queue.add_candidates(
        [
            PublicCandidate(url="https://cad.onshape.com/documents/doc1/w/workspace1"),
            PublicCandidate(url="https://cad.onshape.com/documents/doc2/w/workspace1"),
        ],
        max_buffer=10,
    )

    assert added == 1
    assert queue.next_candidate().url.endswith("/doc2/w/workspace1")


def test_element_key_mode_keeps_distinct_elements_in_same_document() -> None:
    queue = CandidateQueue(key_mode="element")
    added = queue.add_candidates(
        [
            PublicCandidate(url="https://cad.onshape.com/documents/doc1/w/workspace1/e/element1"),
            PublicCandidate(url="https://cad.onshape.com/documents/doc1/w/workspace1/e/element2"),
            PublicCandidate(url="https://cad.onshape.com/documents/doc1/w/workspace1/e/element1"),
        ],
        max_buffer=10,
    )

    assert added == 2
    assert queue.next_candidate().url.endswith("/element1")
    assert queue.next_candidate().url.endswith("/element2")


def test_document_key_mode_still_dedupes_by_document() -> None:
    assert (
        candidate_key("https://cad.onshape.com/documents/doc1/w/workspace1/e/element1")
        == "document:doc1"
    )
    assert (
        candidate_key(
            "https://cad.onshape.com/documents/doc1/w/workspace1/e/element1",
            key_mode="element",
        )
        == "element:doc1:w:workspace1:e:element1"
    )
