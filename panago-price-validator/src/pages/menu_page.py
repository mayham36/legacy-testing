"""Page object for Panago menu page."""
import re
from decimal import Decimal
from typing import Optional

from playwright.async_api import Page

from .base_page import BasePage


class PanagoMenuPage(BasePage):
    """Page object for Panago store menu page.

    Encapsulates all selectors and interactions specific to the Panago
    ordering interface. Selectors are centralized here for easy maintenance
    when the site's DOM structure changes.

    NOTE: The selectors below are PLACEHOLDERS. Before running the automation,
    inspect panago.com with browser DevTools to find the actual selectors.
    """

    # Centralized selectors - VERIFIED from panago.com inspection (January 2026)
    SELECTORS = {
        # Location selection - React Autosuggest component
        "location_trigger": ".react-state-link-choose-location",
        "city_input": ".react-autosuggest__input",
        "autocomplete_container": ".react-autosuggest__suggestions-container",
        "autocomplete_suggestion": ".react-autosuggest__suggestion",
        "save_city_button": ".location-choice-panel .primary.button",
        "location_panel": ".location-choice-panel",
        # Store locator page
        "store_search_input": ".store-locations input[name='name']",
        "store_search_button": ".store-locations button[type='submit']",
        # Products - VERIFIED from panago.com/menu
        "product_card": "ul.products > li, .product-group",
        "product_name": ".product-title h4, h4.product-title, .product-header h4, h4.product-group-title",
        "product_price": ".product-header .price, .prices li span, .price",
        # Navigation - VERIFIED
        "category_tab": "ul.menu li a[href*='{category}']",
        "category_link": "a[href*='/menu/{category}'], ul.menu a[href*='{category}']",
        # Loading states
        "loading_spinner": ".loading, .spinner, [class*='loading']",
        "page_content": "ul.products, .product-group, main",
    }

    # Direct URL paths for categories
    CATEGORY_URLS = {
        "pizzas": "/menu/pizzas",
        "salads": "/menu/salads",
        "sides": "/menu/sides",
        "dips": "/menu/dips",
        "dessert": "/menu/dessert",
        "beverages": "/menu/beverages",
    }

    @property
    def url_pattern(self) -> str:
        """Regex pattern to validate current URL."""
        return r"https?://www\.panago\.com.*"

    async def select_location(self, city: str, timeout: int = 30000) -> None:
        """Select city via the React Autosuggest modal.

        The Panago website uses a city picker modal. This method:
        1. Opens the city picker modal
        2. Enters the city name
        3. Selects from autocomplete suggestions
        4. Saves the selection

        Args:
            city: City string to enter (e.g., "Vancouver, BC").
            timeout: Maximum wait time in milliseconds.
        """
        import asyncio

        # Click location trigger to open the city picker modal
        try:
            await self.safe_click(self.SELECTORS["location_trigger"], timeout=5000)
            await self.wait_for_selector(
                self.SELECTORS["location_panel"],
                timeout=5000,
                state="visible",
            )
        except Exception:
            # Modal might already be visible
            pass

        # Find and fill the city input
        city_input = self._page.locator(self.SELECTORS["city_input"])
        await city_input.click()
        await city_input.fill("")  # Clear existing value
        await city_input.fill(city)

        # Wait for autocomplete suggestions
        await asyncio.sleep(1)

        # Try to click a suggestion if available
        try:
            await self.wait_for_selector(
                self.SELECTORS["autocomplete_suggestion"],
                timeout=3000,
                state="visible",
            )
            await self.safe_click(f"{self.SELECTORS['autocomplete_suggestion']} >> nth=0")
        except Exception:
            # No suggestions, city might be exact match
            pass

        # Click Save City button
        await self.safe_click(self.SELECTORS["save_city_button"], timeout=timeout)
        await self.wait_for_load(timeout=timeout)

    async def navigate_to_category(self, category: str, timeout: int = 10000) -> None:
        """Navigate to a product category.

        Uses direct URL navigation for reliability rather than clicking links.

        Args:
            category: Category name (e.g., 'pizzas', 'salads').
            timeout: Maximum wait time in milliseconds.
        """
        # Use direct URL navigation (more reliable)
        category_url = self.CATEGORY_URLS.get(category, f"/menu/{category}")
        base_url = "https://www.panago.com"
        await self._page.goto(f"{base_url}{category_url}", wait_until="networkidle")

        # Wait for products to load
        try:
            await self.wait_for_selector(
                self.SELECTORS["product_card"],
                timeout=timeout,
                state="visible"
            )
        except Exception:
            # Products might not be visible, just wait for page content
            await self.wait_for_load(timeout=timeout)

    async def get_all_products(self) -> list[dict]:
        """Extract all products and prices from current category.

        Returns:
            List of dictionaries with product name, price, and raw text.
        """
        products = []
        cards = self._page.locator(self.SELECTORS["product_card"])
        count = await cards.count()

        for i in range(count):
            card = cards.nth(i)
            try:
                name_locator = card.locator(self.SELECTORS["product_name"])
                price_locator = card.locator(self.SELECTORS["product_price"])

                name = await name_locator.text_content()
                price_text = await price_locator.text_content()

                products.append({
                    "name": name.strip() if name else "",
                    "price": self._parse_price(price_text),
                    "raw_price_text": price_text or "",
                })
            except Exception:
                # Skip products that can't be extracted
                continue

        return products

    async def get_product_count(self) -> int:
        """Get count of visible products.

        Returns:
            Number of product cards visible on page.
        """
        cards = self._page.locator(self.SELECTORS["product_card"])
        return await cards.count()

    def _parse_price(self, price_text: Optional[str]) -> Optional[Decimal]:
        """Parse price string to Decimal.

        Handles various formats:
        - $19.99
        - $1,299.99
        - 19.99
        - From $14.99

        Args:
            price_text: Raw price string from page.

        Returns:
            Decimal price value or None if unparseable.
        """
        if not price_text:
            return None

        # Handle formats with commas
        cleaned = price_text.replace(",", "")

        # Extract numeric portion after optional $ sign
        match = re.search(r"\$?(\d+\.?\d*)", cleaned)
        if match:
            return Decimal(match.group(1))

        return None
