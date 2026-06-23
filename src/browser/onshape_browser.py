from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

from src.browser import selectors
from src.models.schemas import PublicCandidate

LOGGER = logging.getLogger(__name__)

DOCUMENT_ID_RE = re.compile(r"/documents/([^/?#]+)")


@dataclass(slots=True)
class BrowserClientConfig:
    base_url: str = field(default_factory=lambda: os.getenv("ONSHAPE_BASE_URL", selectors.ONSHAPE_BASE_URL))
    public_url: str | None = field(default_factory=lambda: os.getenv("ONSHAPE_PUBLIC_URL") or None)
    user_data_dir: Path = field(
        default_factory=lambda: Path(os.getenv("ONSHAPE_USER_DATA_DIR", ".playwright/onshape_profile"))
    )
    headless: bool = False
    timeout_ms: int = 30_000
    login_timeout_ms: int = 90_000
    login_failure_screenshot_path: Path = Path("outputs/screenshots/login_failed.png")


@dataclass(slots=True)
class FeatureTreeInspection:
    candidate: PublicCandidate
    part_studio_name: str | None
    raw_feature_items: list[dict[str, Any]]
    feature_folders: list[str]
    screenshot_path: str | None
    warnings: list[str]
    feature_tree_before_screenshot_path: str | None = None
    feature_tree_after_screenshot_path: str | None = None
    extracted_features_path: str | None = None


@dataclass(slots=True)
class FeatureTreeExtraction:
    raw_feature_items: list[dict[str, Any]]
    feature_folders: list[str]
    warnings: list[str]
    before_screenshot_path: str | None = None
    after_screenshot_path: str | None = None


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

    async def ensure_logged_in(self) -> None:
        email = os.getenv("ONSHAPE_EMAIL")
        password = os.getenv("ONSHAPE_PASSWORD")
        missing = [name for name, value in (("ONSHAPE_EMAIL", email), ("ONSHAPE_PASSWORD", password)) if not value]
        if missing:
            raise RuntimeError(
                "Missing required environment variables: "
                + ", ".join(missing)
                + ". Add them to .env or your shell environment."
            )

        page = self._require_page()
        await page.goto(urljoin(self.config.base_url, "/documents"), wait_until="domcontentloaded")
        await page.wait_for_load_state("domcontentloaded")
        if await self.is_logged_in():
            LOGGER.info("Onshape login session detected.")
            return

        await self.login(email=email or "", password=password or "")

    async def login(self, email: str, password: str) -> None:
        if not email or not password:
            raise RuntimeError("ONSHAPE_EMAIL and ONSHAPE_PASSWORD must both be set before login.")

        page = self._require_page()
        LOGGER.info("Opening Onshape login page for configured test account.")
        await page.goto(urljoin(self.config.base_url, "/signin"), wait_until="domcontentloaded")
        await page.wait_for_load_state("domcontentloaded")

        if await self.is_logged_in():
            LOGGER.info("Onshape session became logged in before credential entry.")
            return

        email_locator = await self._wait_for_first_visible_locator(selectors.LOGIN_EMAIL_SELECTORS)
        if email_locator is None:
            await self._save_login_failure_screenshot()
            raise RuntimeError("Could not find Onshape login email field.")

        LOGGER.info("Entering configured Onshape email.")
        await email_locator.fill(email)

        password_locator = await self._first_visible_locator(selectors.LOGIN_PASSWORD_SELECTORS)
        if password_locator is None:
            continue_locator = await self._first_visible_locator(selectors.LOGIN_CONTINUE_SELECTORS)
            if continue_locator is None:
                await email_locator.press("Enter")
            else:
                await continue_locator.click()
            password_locator = await self._wait_for_first_visible_locator(selectors.LOGIN_PASSWORD_SELECTORS)

        if password_locator is None:
            await self._save_login_failure_screenshot()
            raise RuntimeError("Could not find Onshape login password field after submitting email.")

        LOGGER.info("Entering configured Onshape password; password is not logged.")
        await password_locator.fill(password)

        submit_locator = await self._first_visible_locator(selectors.LOGIN_SUBMIT_SELECTORS)
        if submit_locator is None:
            await password_locator.press("Enter")
        else:
            await submit_locator.click()

        try:
            await self._wait_for_login_success_or_failure()
        except Exception as exc:
            await self._save_login_failure_screenshot()
            error_text = await self._visible_login_error_text()
            suffix = f" Visible login error: {error_text}" if error_text else ""
            raise RuntimeError(f"Onshape login did not complete successfully.{suffix}") from exc

        if not await self._wait_until_logged_in(timeout_ms=30_000):
            await self._save_login_failure_screenshot()
            error_text = await self._visible_login_error_text()
            suffix = f" Visible login error: {error_text}" if error_text else ""
            raise RuntimeError(f"Onshape login failed.{suffix}")

        LOGGER.info("Onshape automated login succeeded.")

    async def is_logged_in(self) -> bool:
        page = self._require_page()
        current_url = page.url.lower()
        if "/signin" in current_url or "/login" in current_url:
            if await self._first_visible_locator(selectors.LOGIN_PASSWORD_SELECTORS) is not None:
                return False

        body_text = await self._visible_body_text()
        has_logged_in_text = any(
            token in body_text
            for token in ("owned by me", "recently opened", "created by me", "public", "shared with me")
        )
        if "/documents" in current_url and has_logged_in_text:
            return True
        if "/documents" in current_url and await self._any_selector_visible(selectors.LOGGED_IN_SURFACE_SELECTORS):
            return True
        return await self._any_selector_visible(selectors.LOGGED_IN_SURFACE_SELECTORS)

    async def open_public_page(self) -> None:
        page = self._require_page()
        if self.config.public_url:
            LOGGER.info("Opening configured Onshape public URL: %s", self.config.public_url)
            await page.goto(self.config.public_url, wait_until="domcontentloaded")
            await self._wait_for_document_surface()
            return

        LOGGER.info("Opening Onshape documents page and selecting the Public tab.")
        await page.goto(urljoin(self.config.base_url, "/documents"), wait_until="domcontentloaded")
        await self._wait_for_documents_home()

        for selector in selectors.PUBLIC_TAB_SELECTORS:
            locator = page.locator(selector).first
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

    async def collect_public_candidates(self, max_candidates: int, max_scrolls: int) -> list[PublicCandidate]:
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

            await self.scroll_public_list_once()
            await page.wait_for_timeout(1500)

        return list(seen.values())[:max_candidates]

    async def read_visible_public_candidates(self) -> list[PublicCandidate]:
        return await self._read_visible_document_links()

    async def scroll_public_list_once(self) -> bool:
        return await self._scroll_public_list()

    async def inspect_candidate(
        self,
        *,
        url: str,
        document_name: str | None = None,
        document_id: str | None = None,
        candidate_index: int,
        screenshot_dir: str | Path,
        inspect_multiple_part_studios: bool,
        max_part_studios_per_document: int,
        feature_artifact_dir: str | Path | None = None,
    ) -> list[FeatureTreeInspection]:
        page = self._require_page()
        screenshot_dir = Path(screenshot_dir)
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        artifact_dir = Path(feature_artifact_dir) if feature_artifact_dir is not None else None
        if artifact_dir is not None:
            artifact_dir.mkdir(parents=True, exist_ok=True)
        candidate = PublicCandidate(url=url, document_name=document_name, document_id=document_id or _document_id(url))

        LOGGER.info("Inspecting Onshape candidate: %s", candidate.url)
        await page.goto(candidate.url, wait_until="domcontentloaded")
        await self._wait_for_model_surface()
        candidate = self._candidate_from_current_page(candidate)

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
            extraction = await self.extract_feature_tree(
                artifact_prefix=self._feature_artifact_prefix(
                    artifact_dir=artifact_dir,
                    candidate=candidate,
                    candidate_index=candidate_index,
                    part_index=1,
                )
            )
            return [
                FeatureTreeInspection(
                    candidate=candidate,
                    part_studio_name=None,
                    raw_feature_items=extraction.raw_feature_items,
                    feature_folders=extraction.feature_folders,
                    screenshot_path=screenshot_path,
                    warnings=extraction.warnings if extraction.raw_feature_items else [warning, *extraction.warnings],
                    feature_tree_before_screenshot_path=extraction.before_screenshot_path,
                    feature_tree_after_screenshot_path=extraction.after_screenshot_path,
                    extracted_features_path=self._extracted_features_path(
                        artifact_dir=artifact_dir,
                        candidate=candidate,
                        candidate_index=candidate_index,
                        part_index=1,
                    ),
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

            active_candidate = self._candidate_from_current_page(candidate)
            screenshot_path = await self._take_candidate_screenshot(
                screenshot_dir=screenshot_dir,
                candidate=active_candidate,
                candidate_index=candidate_index,
                part_index=part_index + 1,
            )
            extraction = await self.extract_feature_tree(
                artifact_prefix=self._feature_artifact_prefix(
                    artifact_dir=artifact_dir,
                    candidate=active_candidate,
                    candidate_index=candidate_index,
                    part_index=part_index + 1,
                )
            )
            warnings = extraction.warnings if extraction.raw_feature_items else [
                "No feature tree rows were extracted from the page.",
                *extraction.warnings,
            ]
            inspections.append(
                FeatureTreeInspection(
                    candidate=active_candidate,
                    part_studio_name=part_studio_name,
                    raw_feature_items=extraction.raw_feature_items,
                    feature_folders=extraction.feature_folders,
                    screenshot_path=screenshot_path,
                    warnings=warnings,
                    feature_tree_before_screenshot_path=extraction.before_screenshot_path,
                    feature_tree_after_screenshot_path=extraction.after_screenshot_path,
                    extracted_features_path=self._extracted_features_path(
                        artifact_dir=artifact_dir,
                        candidate=active_candidate,
                        candidate_index=candidate_index,
                        part_index=part_index + 1,
                    ),
                )
            )

        return inspections

    async def extract_feature_tree_items(self, max_items: int = 500) -> list[dict[str, Any]]:
        extraction = await self.extract_feature_tree(max_items=max_items)
        return extraction.raw_feature_items

    async def extract_feature_tree(
        self,
        *,
        max_items: int = 2000,
        max_scroll_steps: int = 300,
        scroll_patience: int = 4,
        artifact_prefix: Path | None = None,
    ) -> FeatureTreeExtraction:
        page = self._require_page()
        container = await self._feature_tree_scroll_container()
        warnings: list[str] = []
        before_screenshot_path: str | None = None
        after_screenshot_path: str | None = None

        if container is None:
            warnings.append(
                "Could not locate the feature tree scroll container; extraction may be incomplete."
            )
            return FeatureTreeExtraction(
                raw_feature_items=await self._read_visible_feature_tree_items(max_items=max_items),
                feature_folders=await self._read_visible_feature_tree_folders(),
                warnings=warnings,
            )

        try:
            await container.evaluate("(el) => { el.scrollTop = 0; }")
            await self._wheel_feature_tree(container, delta_y=-1200, repetitions=10)
            await page.wait_for_timeout(300)
        except Exception as exc:  # pragma: no cover - UI-specific fallback
            warnings.append(f"Could not reset feature tree scroll position: {exc}")

        expected_feature_count = await self._expected_user_feature_count()
        if expected_feature_count is not None:
            LOGGER.info("Expecting %s user feature rows from the feature tree.", expected_feature_count)

        if artifact_prefix is not None:
            before_screenshot_path = await self._take_locator_screenshot(
                container,
                artifact_prefix.with_name(f"{artifact_prefix.name}_feature_tree_before.png"),
            )

        seen: dict[str, dict[str, Any]] = {}
        folder_seen: dict[str, str] = {}
        no_new_steps = 0
        reached_bottom = False

        for _ in range(max_scroll_steps):
            visible_items = await self._read_visible_feature_tree_items(max_items=max_items)
            visible_folders = await self._read_visible_feature_tree_folders()
            added = 0
            for item in visible_items:
                key = _feature_row_key(item)
                if key in seen:
                    continue
                item["extraction_order"] = len(seen) + 1
                seen[key] = item
                added += 1
            folder_added = 0
            for folder_name in visible_folders:
                key = _folder_row_key(folder_name)
                if key in folder_seen:
                    continue
                folder_seen[key] = folder_name
                folder_added += 1

            if len(seen) >= max_items:
                warnings.append(f"Stopped feature extraction after reaching max_items={max_items}.")
                break
            if expected_feature_count is not None and len(seen) >= expected_feature_count:
                reached_bottom = True
                break

            metrics = await self._scroll_metrics(container)
            can_use_native_scroll = (
                metrics is not None
                and metrics["scroll_height"] > metrics["client_height"] + 2
            )
            reached_bottom = bool(
                can_use_native_scroll
                and metrics is not None
                and metrics["scroll_top"] + metrics["client_height"] >= metrics["scroll_height"] - 2
            )
            if reached_bottom:
                break

            no_new_steps = 0 if added or folder_added else no_new_steps + 1
            if no_new_steps >= scroll_patience:
                warnings.append(
                    "Feature tree scrolling stopped before reaching the bottom after repeated scrolls "
                    "with no newly extracted rows."
                )
                break

            if can_use_native_scroll and metrics is not None:
                previous_scroll_top = metrics["scroll_top"]
                try:
                    await container.evaluate(
                        """
                        (el) => {
                          const delta = Math.max(Math.floor(el.clientHeight * 0.85), 180);
                          el.scrollTop = Math.min(el.scrollTop + delta, el.scrollHeight);
                        }
                        """
                    )
                    await page.wait_for_timeout(250)
                except Exception as exc:  # pragma: no cover - UI-specific fallback
                    warnings.append(f"Could not scroll feature tree container: {exc}")
                    break

                next_metrics = await self._scroll_metrics(container)
                if next_metrics is None:
                    warnings.append("Could not verify feature tree scroll movement.")
                    break
                if abs(next_metrics["scroll_top"] - previous_scroll_top) < 1:
                    await self._wheel_feature_tree(container, delta_y=600, repetitions=1)
            else:
                await self._wheel_feature_tree(container, delta_y=600, repetitions=1)

        if not reached_bottom:
            final_metrics = await self._scroll_metrics(container)
            if expected_feature_count is not None and len(seen) >= expected_feature_count:
                reached_bottom = True
            elif (
                final_metrics is not None
                and final_metrics["scroll_height"] > final_metrics["client_height"] + 2
            ):
                reached_bottom = (
                    final_metrics["scroll_top"] + final_metrics["client_height"]
                    >= final_metrics["scroll_height"] - 2
                )
            if not reached_bottom:
                if expected_feature_count is not None:
                    warnings.append(
                        f"Feature tree extraction incomplete: expected {expected_feature_count} "
                        f"features from the header but extracted {len(seen)}."
                    )
                elif not any("Feature tree" in warning for warning in warnings):
                    warnings.append("Feature tree bottom was not reached; extraction is incomplete.")

        if artifact_prefix is not None:
            after_screenshot_path = await self._take_locator_screenshot(
                container,
                artifact_prefix.with_name(f"{artifact_prefix.name}_feature_tree_after.png"),
            )

        items = sorted(seen.values(), key=lambda item: int(item.get("extraction_order") or 0))
        feature_folders = list(folder_seen.values())
        LOGGER.info(
            "Extracted %s feature tree rows and detected %s feature folders after scrolling.",
            len(items),
            len(feature_folders),
        )
        return FeatureTreeExtraction(
            raw_feature_items=items,
            feature_folders=feature_folders,
            warnings=warnings,
            before_screenshot_path=before_screenshot_path,
            after_screenshot_path=after_screenshot_path,
        )

    async def _read_visible_feature_tree_items(self, max_items: int) -> list[dict[str, Any]]:
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
                            attributes: attrs,
                            dom_id: el.getAttribute('id') || '',
                            data_feature_id: el.getAttribute('data-feature-id') || '',
                            data_node_id: el.getAttribute('data-node-id') || '',
                            y_position: Math.round(el.getBoundingClientRect().top)
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

    async def _read_visible_feature_tree_folders(self) -> list[str]:
        page = self._require_page()
        for selector in selectors.FEATURE_TREE_FOLDER_ROW_SELECTORS:
            locator = page.locator(selector)
            try:
                count = await locator.count()
            except Exception:  # pragma: no cover - UI-specific fallback
                continue
            if count == 0:
                continue

            folders: list[str] = []
            for index in range(min(count, 300)):
                row = locator.nth(index)
                try:
                    folder_name = await row.evaluate(
                        """
                        (el) => {
                          const text = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
                          if (!text || /^Default geometry$/i.test(text) || /^Features\\s*\\(/i.test(text)) {
                            return '';
                          }
                          if (/^Parts\\s*\\(/i.test(text)) {
                            return '';
                          }

                          const classText = el.getAttribute('class') || '';
                          const childHints = Array.from(
                            el.querySelectorAll('[aria-label], [title], [class], svg, use')
                          ).map((child) => [
                            child.getAttribute('aria-label') || '',
                            child.getAttribute('title') || '',
                            child.getAttribute('class') || '',
                            child.getAttribute('href') || '',
                            child.getAttribute('xlink:href') || ''
                          ].join(' ')).join(' ').toLowerCase();
                          const rowHints = [
                            classText,
                            el.getAttribute('aria-label') || '',
                            el.getAttribute('title') || '',
                            childHints
                          ].join(' ').toLowerCase();

                          const hasCountSuffix = /\\(\\d+\\)$/.test(text);
                          const hasFolderHint = rowHints.includes('folder') || rowHints.includes('#svg-icon-folder');
                          const expandable =
                            el.hasAttribute('aria-expanded') ||
                            !!el.querySelector('[aria-expanded]') ||
                            rowHints.includes('expand') ||
                            rowHints.includes('collapse');

                          if (hasFolderHint && hasCountSuffix) {
                            return text;
                          }
                          if (/\\bns-user-feature\\b|\\bns-default-feature\\b/.test(classText)) {
                            return '';
                          }
                          if (expandable && hasCountSuffix) {
                            return text;
                          }
                          return '';
                        }
                        """
                    )
                except Exception as exc:  # pragma: no cover - UI-specific fallback
                    LOGGER.debug("Could not read feature folder row %s: %s", index + 1, exc)
                    continue
                if isinstance(folder_name, str) and folder_name.strip():
                    folders.append(folder_name.strip())
            if folders:
                LOGGER.info("Detected %s visible feature folders with selector: %s", len(folders), selector)
                return folders
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

    async def _scroll_public_list(self) -> bool:
        page = self._require_page()
        for selector in selectors.PUBLIC_LIST_CONTAINER_SELECTORS:
            locator = page.locator(selector).first
            try:
                if await locator.count() and await locator.is_visible():
                    changed = await locator.evaluate(
                        """
                        (el) => {
                          const before = el.scrollTop;
                          el.scrollBy({top: Math.max(el.clientHeight, 800), behavior: 'instant'});
                          return Math.abs(el.scrollTop - before) > 1;
                        }
                        """
                    )
                    return bool(changed)
            except Exception:  # pragma: no cover - UI-specific fallback
                continue
        await page.mouse.wheel(0, 1200)
        return True

    async def _wait_for_document_surface(self) -> None:
        page = self._require_page()
        try:
            await page.wait_for_selector(selectors.DOCUMENT_LINK_SELECTOR, timeout=self.config.timeout_ms)
            return
        except Exception as exc:  # pragma: no cover - UI-specific fallback
            LOGGER.debug("Document link wait timed out: %s", exc)

        try:
            await page.locator("text=/Public/i").first.wait_for(timeout=5000)
        except Exception as exc:  # pragma: no cover - UI-specific fallback
            LOGGER.debug("Public text wait timed out: %s", exc)

    async def _wait_for_documents_home(self) -> None:
        page = self._require_page()
        try:
            await page.wait_for_function(
                """
                () => {
                  const body = document.body ? document.body.innerText.toLowerCase() : "";
                  return body.includes("owned by me") ||
                    body.includes("recently opened") ||
                    body.includes("created by me") ||
                    body.includes("public");
                }
                """,
                timeout=min(self.config.timeout_ms, 20_000),
            )
        except Exception as exc:  # pragma: no cover - UI-specific fallback
            LOGGER.debug("Documents home wait timed out: %s", exc)

    async def _wait_for_login_success_or_failure(self) -> None:
        page = self._require_page()
        await page.wait_for_function(
            """
            () => {
              const url = window.location.href.toLowerCase();
              const body = document.body ? document.body.innerText.toLowerCase() : "";
              const hasPassword = !!document.querySelector('input[type="password"]');
              const loginFailed = /invalid|incorrect|failed|try again|captcha|two-factor|two factor/.test(body);
              const loggedInUrl = url.includes('/documents');
              const loggedInText = /my onshape|recently opened|created by me|public/.test(body);
              return loginFailed || (!hasPassword && (loggedInUrl || loggedInText));
            }
            """,
            timeout=self.config.login_timeout_ms,
        )
        await page.wait_for_load_state("domcontentloaded")

    async def _wait_until_logged_in(self, timeout_ms: int) -> bool:
        page = self._require_page()
        deadline = time.monotonic() + timeout_ms / 1000
        while time.monotonic() < deadline:
            if await self.is_logged_in():
                return True
            await page.wait_for_timeout(500)
        return False

    async def _visible_login_error_text(self) -> str | None:
        page = self._require_page()
        for selector in selectors.LOGIN_ERROR_SELECTORS:
            locator = page.locator(selector).first
            try:
                if await locator.count() and await locator.is_visible():
                    text = (await locator.inner_text()).strip()
                    if text:
                        return re.sub(r"\s+", " ", text)[:300]
            except Exception:  # pragma: no cover - UI-specific fallback
                continue
        return None

    async def _save_login_failure_screenshot(self) -> None:
        page = self._require_page()
        path = self.config.login_failure_screenshot_path
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            await page.screenshot(path=str(path), full_page=True)
            LOGGER.error("Saved Onshape login failure screenshot to %s", path)
        except Exception as exc:  # pragma: no cover - UI-specific fallback
            LOGGER.warning("Could not save Onshape login failure screenshot: %s", exc)

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

    async def _feature_tree_scroll_container(self) -> Any | None:
        return await self._first_visible_locator(selectors.FEATURE_TREE_SCROLL_CONTAINER_SELECTORS)

    async def _expected_user_feature_count(self) -> int | None:
        page = self._require_page()
        try:
            text = await page.locator("#feature-list .features-title").first.inner_text(timeout=2000)
        except Exception:  # pragma: no cover - UI-specific fallback
            try:
                text = await page.locator("text=/Features\\s*\\(\\d+\\)/").first.inner_text(timeout=2000)
            except Exception:
                return None
        match = re.search(r"Features\s*\((\d+)\)", text)
        if not match:
            return None

        total_feature_rows = int(match.group(1))
        default_geometry_rows = 0
        try:
            default_rows = page.locator("#feature-list .os-list-item.ns-default-feature")
            count = await default_rows.count()
            for index in range(count):
                row_text = (await default_rows.nth(index).inner_text()).strip()
                if row_text and not re.fullmatch(r"Default geometry", row_text, flags=re.IGNORECASE):
                    default_geometry_rows += 1
        except Exception:  # pragma: no cover - UI-specific fallback
            default_geometry_rows = 0

        LOGGER.info(
            "Feature tree header reports %s total rows; excluding %s default geometry rows.",
            total_feature_rows,
            default_geometry_rows,
        )
        return max(total_feature_rows - default_geometry_rows, 0)

    async def _wheel_feature_tree(self, locator: Any, *, delta_y: int, repetitions: int) -> None:
        try:
            await locator.hover()
        except Exception:  # pragma: no cover - UI-specific fallback
            pass
        page = self._require_page()
        for _ in range(repetitions):
            await page.mouse.wheel(0, delta_y)
            await page.wait_for_timeout(80)

    async def _scroll_metrics(self, locator: Any) -> dict[str, float] | None:
        try:
            metrics = await locator.evaluate(
                """
                (el) => ({
                  scroll_top: el.scrollTop,
                  client_height: el.clientHeight,
                  scroll_height: el.scrollHeight
                })
                """
            )
        except Exception:  # pragma: no cover - UI-specific fallback
            return None
        return {
            "scroll_top": float(metrics.get("scroll_top", 0)),
            "client_height": float(metrics.get("client_height", 0)),
            "scroll_height": float(metrics.get("scroll_height", 0)),
        }

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

    async def _take_locator_screenshot(self, locator: Any, path: Path) -> str | None:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            await locator.screenshot(path=str(path))
            return str(path)
        except Exception as exc:  # pragma: no cover - UI-specific fallback
            LOGGER.warning("Could not save feature tree screenshot to %s: %s", path, exc)
            return None

    def _feature_artifact_prefix(
        self,
        *,
        artifact_dir: Path | None,
        candidate: PublicCandidate,
        candidate_index: int,
        part_index: int,
    ) -> Path | None:
        if artifact_dir is None:
            return None
        safe_name = _safe_filename(candidate.document_name or candidate.document_id or "candidate")
        return artifact_dir / f"{candidate_index:04d}_part{part_index}_{safe_name}"

    def _extracted_features_path(
        self,
        *,
        artifact_dir: Path | None,
        candidate: PublicCandidate,
        candidate_index: int,
        part_index: int,
    ) -> str | None:
        prefix = self._feature_artifact_prefix(
            artifact_dir=artifact_dir,
            candidate=candidate,
            candidate_index=candidate_index,
            part_index=part_index,
        )
        if prefix is None:
            return None
        return str(prefix.with_name(f"{prefix.name}_extracted_features.json"))

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
        return await self._first_visible_locator(selector_values) is not None

    async def _first_visible_locator(self, selector_values: tuple[str, ...]) -> Any | None:
        page = self._require_page()
        for selector in selector_values:
            try:
                locators = page.locator(selector)
                count = min(await locators.count(), 25)
                for index in range(count):
                    locator = locators.nth(index)
                    if await locator.is_visible():
                        return locator
            except Exception:  # pragma: no cover - UI-specific fallback
                continue
        return None

    async def _visible_body_text(self) -> str:
        page = self._require_page()
        try:
            text = await page.evaluate("() => document.body ? document.body.innerText : ''")
        except Exception:  # pragma: no cover - UI-specific fallback
            return ""
        return re.sub(r"\s+", " ", str(text)).strip().lower()

    def _candidate_from_current_page(self, candidate: PublicCandidate) -> PublicCandidate:
        page = self._require_page()
        current_url = _normalize_url(page.url)
        if not _document_id(current_url):
            return candidate
        return candidate.model_copy(
            update={
                "url": current_url,
                "document_id": candidate.document_id or _document_id(current_url),
            }
        )

    async def _wait_for_first_visible_locator(
        self,
        selector_values: tuple[str, ...],
        timeout_ms: int | None = None,
    ) -> Any | None:
        page = self._require_page()
        deadline = time.monotonic() + (timeout_ms or self.config.timeout_ms) / 1000
        while time.monotonic() < deadline:
            locator = await self._first_visible_locator(selector_values)
            if locator is not None:
                return locator
            await page.wait_for_timeout(250)
        return None

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


def _feature_row_key(item: dict[str, Any]) -> str:
    attributes = item.get("attributes") or {}
    if isinstance(attributes, dict):
        for key in ("id", "data-feature-id", "data-node-id", "data-id"):
            value = attributes.get(key)
            if value:
                return f"{key}:{value}"
    for key in ("dom_id", "data_feature_id", "data_node_id"):
        value = item.get(key)
        if value:
            return f"{key}:{value}"
    text = re.sub(r"\s+", " ", str(item.get("raw_text") or "")).strip().lower()
    return f"text:{text}"


def _folder_row_key(folder_name: str) -> str:
    text = re.sub(r"\s+", " ", folder_name).strip().lower()
    return f"folder:{text}"
