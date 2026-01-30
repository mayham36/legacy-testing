"""Base page object for Playwright automation."""
from abc import ABC, abstractmethod
from typing import Optional

from playwright.async_api import Page, Locator


class BasePage(ABC):
    """Base class for all page objects.

    Provides common functionality for page interactions including
    wait strategies and navigation helpers.
    """

    def __init__(self, page: Page) -> None:
        """Initialize the base page.

        Args:
            page: Playwright page instance.
        """
        self._page = page

    @property
    def page(self) -> Page:
        """Get the underlying Playwright page."""
        return self._page

    async def wait_for_load(self, timeout: int = 30000) -> None:
        """Wait for page to be ready.

        Args:
            timeout: Maximum wait time in milliseconds.
        """
        await self._page.wait_for_load_state("networkidle", timeout=timeout)

    async def wait_for_selector(
        self, selector: str, timeout: int = 30000, state: str = "visible"
    ) -> Locator:
        """Wait for a selector to be in the specified state.

        Args:
            selector: CSS or other selector string.
            timeout: Maximum wait time in milliseconds.
            state: Expected state ('visible', 'hidden', 'attached', 'detached').

        Returns:
            Locator for the matched element.
        """
        locator = self._page.locator(selector)
        await locator.wait_for(timeout=timeout, state=state)
        return locator

    async def safe_click(
        self, selector: str, timeout: int = 30000
    ) -> None:
        """Click an element with automatic waiting.

        Args:
            selector: CSS or other selector string.
            timeout: Maximum wait time in milliseconds.
        """
        await self._page.click(selector, timeout=timeout)

    async def safe_fill(
        self, selector: str, value: str, timeout: int = 30000
    ) -> None:
        """Fill an input with automatic waiting.

        Args:
            selector: CSS or other selector string.
            value: Value to fill.
            timeout: Maximum wait time in milliseconds.
        """
        locator = self._page.locator(selector)
        await locator.fill(value, timeout=timeout)

    async def get_text(
        self, selector: str, timeout: int = 30000
    ) -> Optional[str]:
        """Get text content of an element.

        Args:
            selector: CSS or other selector string.
            timeout: Maximum wait time in milliseconds.

        Returns:
            Text content or None if element not found.
        """
        try:
            locator = self._page.locator(selector)
            return await locator.text_content(timeout=timeout)
        except Exception:
            return None

    @property
    @abstractmethod
    def url_pattern(self) -> str:
        """Regex pattern to validate current URL.

        Subclasses must implement this to define valid URLs for the page.
        """
        pass
