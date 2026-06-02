"""Centralized Onshape UI selectors.

Onshape is a complex single-page application, so these selectors are best-effort
DOM hooks rather than a public contract. Keep all UI selector maintenance here.
"""

ONSHAPE_BASE_URL = "https://cad.onshape.com"

LOGIN_EMAIL_SELECTORS = (
    'input[type="email"]',
    'input[name="email"]',
    'input[name="username"]',
    'input[id*="email" i]',
    'input[id*="username" i]',
    'input[autocomplete="username"]',
    '[aria-label*="email" i]',
    '[placeholder*="email" i]',
)

LOGIN_PASSWORD_SELECTORS = (
    'input[type="password"]',
    'input[name="password"]',
    'input[id*="password" i]',
    'input[autocomplete="current-password"]',
    '[aria-label*="password" i]',
    '[placeholder*="password" i]',
)

LOGIN_CONTINUE_SELECTORS = (
    'button:has-text("Continue")',
    '[role="button"]:has-text("Continue")',
    'input[type="submit"][value*="Continue" i]',
)

LOGIN_SUBMIT_SELECTORS = (
    'button[type="submit"]',
    'input[type="submit"]',
    'button:has-text("Sign in")',
    'button:has-text("Log in")',
    '[role="button"]:has-text("Sign in")',
    '[role="button"]:has-text("Log in")',
)

LOGIN_ERROR_SELECTORS = (
    '[role="alert"]',
    '[class*="error" i]',
    '[class*="invalid" i]',
    '[data-testid*="error" i]',
    'text=/invalid|incorrect|failed|try again|verify|captcha|two-factor|two factor/i',
)

LOGGED_IN_SURFACE_SELECTORS = (
    'a[href*="/documents/"]',
    'text=/My Onshape|Recently opened|Created by me|Public/i',
    '[aria-label*="Create" i]',
    '[class*="document" i]',
)

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
    '#os-tab-bar tab-list-item:has-text("Part Studio")',
    '#os-tab-bar .os-tab-bar-tab:has-text("Part Studio")',
    '#os-tab-bar [title*="Part Studio"]',
    '#os-tab-bar [aria-label*="Part Studio"]',
    'tab-list-item:has-text("Part Studio")',
    '.os-tab-bar-tab:has-text("Part Studio")',
)

FEATURE_TREE_ITEM_SELECTORS = (
    "#feature-list .os-list-item.ns-user-feature",
    "#feature-list .ns-user-feature",
    "#feature-list-container .os-list-item.ns-user-feature",
    '[data-testid*="feature-tree"] [role="treeitem"]',
    '[class*="feature-tree"] [role="treeitem"]',
    '[class*="featureTree"] [role="treeitem"]',
    '[role="tree"] [role="treeitem"]',
    '[class*="featureTree"] [class*="feature"]',
)

FEATURE_TREE_SCROLL_CONTAINER_SELECTORS = (
    "#feature-list .pane-section-scroll-container",
    "#feature-list-container .pane-section-scroll-container",
    "#feature-list",
    "#feature-list-container",
)

VIEWPORT_READY_SELECTORS = (
    "canvas",
    '[class*="graphics"]',
    '[class*="viewport"]',
)
