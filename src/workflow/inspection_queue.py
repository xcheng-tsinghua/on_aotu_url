from __future__ import annotations

import re
from collections import deque
from collections.abc import Iterable
from urllib.parse import urlsplit, urlunsplit

from src.models.schemas import PublicCandidate

DOCUMENT_ID_RE = re.compile(r"/documents/([^/?#]+)")
DOCUMENT_WORKSPACE_ELEMENT_RE = re.compile(
    r"/documents/([^/?#]+)(?:/w/([^/?#]+))?(?:/e/([^/?#]+))?"
)


class CandidateQueue:
    def __init__(
        self,
        already_inspected_keys: Iterable[str] = (),
        *,
        key_mode: str = "document",
    ) -> None:
        if key_mode not in {"document", "element"}:
            raise ValueError(f"Unsupported candidate key mode: {key_mode}")
        self.key_mode = key_mode
        self._seen_keys: set[str] = set(already_inspected_keys)
        self._pending: deque[PublicCandidate] = deque()

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    @property
    def unique_seen_count(self) -> int:
        return len(self._seen_keys)

    def add_candidates(
        self,
        candidates: Iterable[PublicCandidate],
        *,
        max_buffer: int,
    ) -> int:
        added = 0
        for candidate in candidates:
            if len(self._pending) >= max_buffer:
                break
            key = candidate_key(candidate, key_mode=self.key_mode)
            if key in self._seen_keys:
                continue
            self._seen_keys.add(key)
            self._pending.append(candidate)
            added += 1
        return added

    def next_candidate(self) -> PublicCandidate | None:
        if not self._pending:
            return None
        return self._pending.popleft()


def candidate_key(candidate_or_url: PublicCandidate | str, *, key_mode: str = "document") -> str:
    if key_mode not in {"document", "element"}:
        raise ValueError(f"Unsupported candidate key mode: {key_mode}")

    if isinstance(candidate_or_url, PublicCandidate):
        url = candidate_or_url.url
        document_id = candidate_or_url.document_id
    else:
        url = candidate_or_url
        document_id = None

    match = DOCUMENT_WORKSPACE_ELEMENT_RE.search(url)
    if match:
        document, workspace, element = match.groups()
        if key_mode == "element":
            if document and workspace and element:
                return f"element:{document}:w:{workspace}:e:{element}"
            if document and workspace:
                return f"workspace:{document}:w:{workspace}"
        return f"document:{document}"

    if document_id:
        return f"document:{document_id}"

    match = DOCUMENT_ID_RE.search(url)
    if match:
        return f"document:{match.group(1)}"

    split = urlsplit(url)
    stable = urlunsplit((split.scheme, split.netloc, split.path, "", ""))
    return f"url:{stable}"


def candidate_resume_keys(candidate_or_url: PublicCandidate | str, *, key_mode: str = "document") -> set[str]:
    key = candidate_key(candidate_or_url, key_mode=key_mode)
    if key_mode != "element":
        return {key}

    url = candidate_or_url.url if isinstance(candidate_or_url, PublicCandidate) else candidate_or_url
    keys = {key}
    match = DOCUMENT_WORKSPACE_ELEMENT_RE.search(url)
    if not match:
        return keys

    document, workspace, _element = match.groups()
    if document:
        keys.add(f"document:{document}")
    if document and workspace:
        keys.add(f"workspace:{document}:w:{workspace}")
    return keys


def inspected_count(results_count_this_run: int) -> int:
    return results_count_this_run


def should_continue_inspecting(*, inspected_this_run: int, target_inspected_count: int) -> bool:
    if target_inspected_count <= 0:
        return True
    return inspected_this_run < target_inspected_count
