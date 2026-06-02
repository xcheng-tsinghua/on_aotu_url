from __future__ import annotations

import re
from collections import deque
from collections.abc import Iterable
from urllib.parse import urlsplit, urlunsplit

from src.models.schemas import PublicCandidate

DOCUMENT_ID_RE = re.compile(r"/documents/([^/?#]+)")


class CandidateQueue:
    def __init__(self, already_inspected_keys: Iterable[str] = ()) -> None:
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
            key = candidate_key(candidate)
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


def candidate_key(candidate_or_url: PublicCandidate | str) -> str:
    if isinstance(candidate_or_url, PublicCandidate):
        if candidate_or_url.document_id:
            return f"document:{candidate_or_url.document_id}"
        url = candidate_or_url.url
    else:
        url = candidate_or_url

    match = DOCUMENT_ID_RE.search(url)
    if match:
        return f"document:{match.group(1)}"

    split = urlsplit(url)
    stable = urlunsplit((split.scheme, split.netloc, split.path, "", ""))
    return f"url:{stable}"


def inspected_count(results_count_this_run: int) -> int:
    return results_count_this_run


def should_continue_inspecting(*, inspected_this_run: int, target_inspected_count: int) -> bool:
    return inspected_this_run < target_inspected_count
