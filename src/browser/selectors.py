"""Centralized Onshape UI selectors.

Onshape is a complex single-page application, so these selectors are best-effort
DOM hooks rather than a public contract. Keep all UI selector maintenance here.
"""

ONSHAPE_BASE_URL = "https://cad.onshape.com"

DOCUMENT_LINK_SELECTOR = 'a[href*="/documents/"]'

PUBLIC_TAB_SELECTORS = (
    'text="Public"',
    '[role="tab"]:has-text("Public")',
    'button:has-text("Public")',
    'a:has-text("Public")',
    '[aria-label*="Public"]',
)

PUBLIC_LIST_CONTAINER_SELECTORS = (
    '[data-testid*="document"]',
    '[class*="document-list"]',
    '[class*="documents-list"]',
    '[class*="grid"]',
    "main",
    "body",
)

PART_STUDIO_TAB_SELECTORS = (
    '[title*="Part Studio"]',
    '[aria-label*="Part Studio"]',
    '[class*="tab"]:has-text("Part Studio")',
    'text=/Part Studio/i',
)

FEATURE_TREE_ITEM_SELECTORS = (
    '[data-testid*="feature-tree"] [role="treeitem"]',
    '[class*="feature-tree"] [role="treeitem"]',
    '[class*="featureTree"] [role="treeitem"]',
    '[role="tree"] [role="treeitem"]',
    '[class*="feature-list"] [class*="feature"]',
    '[class*="featureTree"] [class*="feature"]',
)

VIEWPORT_READY_SELECTORS = (
    "canvas",
    '[class*="graphics"]',
    '[class*="viewport"]',
)
