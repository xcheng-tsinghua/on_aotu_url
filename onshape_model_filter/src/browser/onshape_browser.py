from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

from src.browser import selectors
from src.models.schemas import PublicCandidate

LOGGER = logging.getLogger(__name__)

DOCUMENT_ID_RE = re.compile(r"/documents/([^/?#]+)")


@dataclass(slots=True)
class BrowserClientConfig:
    base_url: str = os.getenv("ONSHAPE_BASE_URL", selectors.ONSHAPE_BASE_URL)
    public_url: str | None = os.getenv("ONSHAPE_PUBLIC_URL") or None
    user_data_dir: Path = Path(os.getenv("ONSHAPE_USER_DATA_DIR", ".playwright/onshape_profile"))
    headless: bool = False
    timeout_ms: int = 30_000
    manual_login_timeout_ms: int = 15 * 60 * 1000


@dataclass(slots=True)
class FeatureTreeInspection:
    candidate: PublicCandidate
    part_studio_name: str | None
    raw_feature_items: list[dict[str, Any]]
    screenshot_path: str | None
    warnings: list[str]


class BrowserOnshapeClient:
    """Playwright client for using the Onshape web UI, not the REST API."""

    def __init__(self, config: BrowserClientConfig) -> None:
        self.config = config
        self.playwright: Any | None = None
        self.context: Any | None = None
        self.page: Any | None = None

    async def __aenter__(self) -> "BrowserOnshapeClient":
        from playwright.async_api import async_playwright

        self.config.user_data_dir.mkdir(parents=True, exist_ok=True)
        self.playwright = await async_playwright().start()
        self.context = await self.playwright.chromium.launch_persistent_context(
            user_data_dir=str(self.config.user_data_dir),
            headless=self.config.headless,
            viewport={"width": 1440, "height": 950},
            accept_downloads=False,
        )
        self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
        self.page.set_default_timeout(self.config.timeout_ms)
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self.context is not None:
            await self.context.close()
        if self.playwright is not None:
            await self.playwright.stop()

    async def open_onshape(self) -> None:
        page = self._require_page()
        await page.goto(urljoin(self.config.base_url, "/documents"), wait_until="domcontentloaded")
        await page.wait_for_load_state("domcontentloaded")

    async def wait_for_login(self) -> None:
        page = self._require_page()
        if await self.is_logged_in():
            LOGGER.info("Onshape login session detected.")
            return

        LOGGER.info("Waiting for manual Onshape login in the browser window.")
        await page.goto(urljoin(self.config.base_url, "/signin"), wait_until="domcontentloaded")
        await page.wait_for_function(
            """
            () => {
              const url = window.location.href.toLowerCase();
              const body = document.body ? document.body.innerText.toLowerCase() : "";
              return !url.includes("/signin") &&
                (url.includes("/documents") || body.includes("public") || body.includes("my onshape"));
            }
            """,
            timeout=self.config.manual_login_timeout_ms,
        )
        await page.wait_for_load_state("domcontentloaded")
        LOGGER.info("Manual login appears complete.")

    async def is_logged_in(self) -> bool:
        page = self._require_page()
        current_url = page.url.lower()
        if "/signin" in current_url or "/login" in current_url:
            return False
        if "/documents" in current_url:
            return True
        return await self._any_selector_visible(selectors.PUBLIC_TAB_SELECTORS)

    async def open_public_page(self) -> None:
        page = self._require_page()
        if self.config.public_url:
            LOGGER.info("Opening configured Onshape public URL: %s", self.config.public_url)
            await page.goto(self.config.public_url, wait_until="domcontentloaded")
            await self._wait_for_document_surface()
            return

        LOGGER.info("Opening Onshape documents page and selecting the Public tab.")
        await page.goto(urljoin(self.config.base_url, "/documents"), wait_until="domcontentloaded")
        await self._wait_for_document_surface()

        for selector in selectors.PUBLIC_TAB_SELECTORS:
            locator = page.locator(selector).first()
            try:
                if await locator.count() and await locator.is_visible():
                    await locator.click()
                    await page.wait_for_timeout(1500)
                    await self._wait_for_document_surface()
                    return
            except Exception as exc:  # pragma: no cover - UI-specific fallback
                LOGGER.debug("Public selector failed (%s): %s", selector, exc)

        raise RuntimeError(
            "Could not find the Onshape Public tab. Update src/browser/selectors.py or set "
            "ONSHAPE_PUBLIC_URL to a stable public-documents page."
        )

    async def collect_public_candidates(
        self,
        *,
        max_candidates: int,
        max_scrolls: int,
    ) -> list[PublicCandidate]:
        page = self._require_page()
        seen: dict[str, PublicCandidate] = {}

        for scroll_index in range(max_scrolls + 1):
            for candidate in await self._read_visible_document_links():
                key = candidate.document_id or _stable_url_key(candidate.url)
                seen.setdefault(key, candidate)
                if len(seen) >= max_candidates:
                    break

            LOGGER.info(
                "Collected %s/%s candidate links after scroll %s.",
                len(seen),
                max_candidates,
                scroll_index,
            )
            if len(seen) >= max_candidates or scroll_index >= max_scrolls:
                break

            await self._scroll_public_list()
            await page.wait_for_timeout(1500)

        return list(seen.values())[:max_candidates]

    async def inspect_candidate(
        self,
        *,
        candidate: PublicCandidate,
        candidate_index: int,
        screenshot_dir: str | Path,
        inspect_multiple_part_studios: bool,
        max_part_studios_per_document: int,
    ) -> list[FeatureTreeInspection]:
        page = self._require_page()
        screenshot_dir = Path(screenshot_dir)
        screenshot_dir.mkdir(parents=True, exist_ok=True)

        LOGGER.info("Inspecting Onshape candidate: %s", candidate.url)
        await page.goto(candidate.url, wait_until="domcontentloaded")
        await self._wait_for_model_surface()

        part_locator, part_count = await self._find_part_studio_locator()
        if part_locator is None or part_count == 0:
            warning = "No Part Studio tab selector matched; attempting to inspect the current tab."
            LOGGER.warning(warning)
            screenshot_path = await self._take_candidate_screenshot(
                screenshot_dir=screenshot_dir,
                candidate=candidate,
                candidate_index=candidate_index,
                part_index=1,
            )
            return [
                FeatureTreeInspection(
                    candidate=candidate,
                    part_studio_name=None,
                    raw_feature_items=await self.extract_feature_tree_items(),
                    screenshot_path=screenshot_path,
                    warnings=[warning],
                )
            ]

        limit = min(max_part_studios_per_document, part_count)
        if not inspect_multiple_part_studios:
            limit = min(limit, 1)

        inspections: list[FeatureTreeInspection] = []
        for part_index in range(limit):
            tab = part_locator.nth(part_index)
            part_studio_name = await self._safe_locator_label(tab)
            try:
                if await tab.is_visible():
                    await tab.click()
                    await self._wait_for_model_surface()
            except Exception as exc:  # pragma: no cover - UI-specific fallback
                LOGGER.warning("Could not activate Part Studio tab %s: %s", part_index + 1, exc)

            screenshot_path = await self._take_candidate_screenshot(
                screenshot_dir=screenshot_dir,
                candidate=candidate,
                candidate_index=candidate_index,
                part_index=part_index + 1,
            )
            raw_items = await self.extract_feature_tree_items()
            warnings = [] if raw_items else ["No feature tree rows were extracted from the page."]
            inspections.append(
                FeatureTreeInspection(
                    candidate=candidate,
                    part_studio_name=part_studio_name,
                    raw_feature_items=raw_items,
                    screenshot_path=screenshot_path,
                    warnings=warnings,
                )
            )

        return inspections

    async def extract_feature_tree_items(self, max_items: int = 500) -> list[dict[str, Any]]:
        page = self._require_page()
        for selector in selectors.FEATURE_TREE_ITEM_SELECTORS:
            locator = page.locator(selector)
            try:
                count = min(await locator.count(), max_items)
            except Exception:  # pragma: no cover - UI-specific fallback
                continue
            if count == 0:
                continue

            items: list[dict[str, Any]] = []
            for index in range(count):
                row = locator.nth(index)
                try:
                    metadata = await row.evaluate(
                        """
                        (el) => {
                          const attrs = {};
                          for (const attr of el.attributes) attrs[attr.name] = attr.value;
                          const childLabels = Array.from(
                            el.querySelectorAll('[aria-label], [title], [class]')
                          ).map((child) => [
                            child.getAttribute('aria-label') || '',
                            child.getAttribute('title') || '',
                            child.getAttribute('class') || ''
                          ].join(' ')).join(' ');
                          return {
                            raw_text: el.innerText || el.textContent || '',
                            aria_label: el.getAttribute('aria-label') || '',
                            title: el.getAttribute('title') || '',
                            class_name: el.getAttribute('class') || '',
                            style: el.getAttribute('style') || '',
                            child_labels: childLabels,
                            attributes: attrs
                          };
                        }
                        """
                    )
                except Exception as exc:  # pragma: no cover - UI-specific fallback
                    LOGGER.debug("Could not read feature row %s: %s", index + 1, exc)
                    continue
                if str(metadata.get("raw_text") or "").strip() or str(
                    metadata.get("aria_label") or ""
                ).strip():
                    items.append(metadata)
            if items:
                LOGGER.info("Extracted %s feature tree rows with selector: %s", len(items), selector)
                return items
        return []

    async def _read_visible_document_links(self) -> list[PublicCandidate]:
        page = self._require_page()
        anchors = page.locator(selectors.DOCUMENT_LINK_SELECTOR)
        candidates: list[PublicCandidate] = []
        try:
            count = await anchors.count()
        except Exception:  # pragma: no cover - UI-specific fallback
            return candidates

        for index in range(min(count, 1000)):
            anchor = anchors.nth(index)
            try:
                href = await anchor.get_attribute("href")
                if not href:
                    continue
                url = _normalize_url(urljoin(self.config.base_url, href))
                document_id = _document_id(url)
                if not document_id:
                    continue
                document_name = (await anchor.inner_text()).strip() or await anchor.get_attribute("title")
                candidates.append(
                    PublicCandidate(
                        url=url,
                        document_name=document_name.strip() if document_name else None,
                        document_id=document_id,
                    )
                )
            except Exception as exc:  # pragma: no cover - UI-specific fallback
                LOGGER.debug("Could not read document link %s: %s", index + 1, exc)
        return candidates

    async def _scroll_public_list(self) -> None:
        page = self._require_page()
        for selector in selectors.PUBLIC_LIST_CONTAINER_SELECTORS:
            locator = page.locator(selector).first()
            try:
                if await locator.count() and await locator.is_visible():
                    await locator.evaluate(
                        "(el) => el.scrollBy({top: Math.max(el.clientHeight, 800), behavior: 'instant'})"
                    )
                    return
            except Exception:  # pragma: no cover - UI-specific fallback
                continue
        await page.mouse.wheel(0, 1200)

    async def _wait_for_document_surface(self) -> None:
        page = self._require_page()
        try:
            await page.wait_for_selector(selectors.DOCUMENT_LINK_SELECTOR, timeout=self.config.timeout_ms)
            return
        except Exception as exc:  # pragma: no cover - UI-specific fallback
            LOGGER.debug("Document link wait timed out: %s", exc)

        try:
            await page.locator("text=/Public/i").first().wait_for(timeout=5000)
        except Exception as exc:  # pragma: no cover - UI-specific fallback
            LOGGER.debug("Public text wait timed out: %s", exc)

    async def _wait_for_model_surface(self) -> None:
        page = self._require_page()
        for selector in selectors.VIEWPORT_READY_SELECTORS:
            try:
                await page.wait_for_selector(selector, timeout=min(self.config.timeout_ms, 15_000))
                break
            except Exception:  # pragma: no cover - UI-specific fallback
                continue
        await page.wait_for_timeout(1000)

    async def _find_part_studio_locator(self) -> tuple[Any | None, int]:
        page = self._require_page()
        for selector in selectors.PART_STUDIO_TAB_SELECTORS:
            locator = page.locator(selector)
            try:
                count = await locator.count()
            except Exception:  # pragma: no cover - UI-specific fallback
                continue
            if count:
                return locator, count
        return None, 0

    async def _take_candidate_screenshot(
        self,
        *,
        screenshot_dir: Path,
        candidate: PublicCandidate,
        candidate_index: int,
        part_index: int,
    ) -> str | None:
        page = self._require_page()
        safe_name = _safe_filename(candidate.document_name or candidate.document_id or "candidate")
        path = screenshot_dir / f"{candidate_index:04d}_part{part_index}_{safe_name}.png"
        try:
            await page.screenshot(path=str(path), full_page=True)
            return str(path)
        except Exception as exc:  # pragma: no cover - UI-specific fallback
            LOGGER.warning("Could not save screenshot for %s: %s", candidate.url, exc)
            return None

    async def _safe_locator_label(self, locator: Any) -> str | None:
        for getter in (
            lambda: locator.inner_text(),
            lambda: locator.get_attribute("title"),
            lambda: locator.get_attribute("aria-label"),
        ):
            try:
                value = await getter()
                if value and str(value).strip():
                    return str(value).strip()
            except Exception:  # pragma: no cover - UI-specific fallback
                continue
        return None

    async def _any_selector_visible(self, selector_values: tuple[str, ...]) -> bool:
        page = self._require_page()
        for selector in selector_values:
            try:
                locator = page.locator(selector).first()
                if await locator.count() and await locator.is_visible():
                    return True
            except Exception:  # pragma: no cover - UI-specific fallback
                continue
        return False

    def _require_page(self) -> Any:
        if self.page is None:
            raise RuntimeError("BrowserOnshapeClient has not been started.")
        return self.page


def _document_id(url: str) -> str | None:
    match = DOCUMENT_ID_RE.search(url)
    return match.group(1) if match else None


def _stable_url_key(url: str) -> str:
    split = urlsplit(url)
    return urlunsplit((split.scheme, split.netloc, split.path, "", ""))


def _normalize_url(url: str) -> str:
    split = urlsplit(url)
    return urlunsplit((split.scheme, split.netloc, split.path, split.query, ""))


def _safe_filename(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return safe[:80] or "candidate"
