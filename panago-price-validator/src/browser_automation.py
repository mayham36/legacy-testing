"""Playwright browser automation with parallel execution."""
import asyncio
import random
import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional

import structlog
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from .models import AutomationConfig, PriceRecord, LocationConfig
from .config_loader import load_locations

logger = structlog.get_logger()


class PanagoAutomation:
    """High-performance pricing validation with parallel processing.

    Uses Playwright to automate browser interactions with the Panago website,
    collecting prices from all product categories across multiple store locations.
    Parallel execution with bounded concurrency achieves significant speedup.
    """

    # Resource types to block for faster page loads
    BLOCKED_RESOURCES = [
        "**/*.png",
        "**/*.jpg",
        "**/*.jpeg",
        "**/*.gif",
        "**/*.webp",
        "**/*.woff",
        "**/*.woff2",
        "**/*.ttf",
        "**/analytics*",
        "**/tracking*",
        "**/google-analytics*",
        "**/gtag*",
        "**/gtm*",
        "**/facebook*",
        "**/twitter*",
    ]

    # Product categories to scrape - matches panago.com URL structure
    # Note: "Sides" contains wings, breadstuff, etc. on the actual site
    CATEGORIES = ["pizzas", "salads", "sides", "dips", "dessert", "beverages"]

    # Menu URL paths for each category
    # Note: /menu/pizzas may redirect, so we use a subcategory
    CATEGORY_URLS = {
        "pizzas": "/menu/pizzas/meat",  # Use meat pizzas as main pizza page
        "salads": "/menu/salads",
        "sides": "/menu/sides",  # Contains wings, breadstuff, etc.
        "dips": "/menu/dips",
        "dessert": "/menu/dessert",
        "beverages": "/menu/beverages",
    }

    # Page selectors - VERIFIED from panago.com inspection (January 2026)
    SELECTORS = {
        # Location selection - React Autosuggest component
        "location_trigger": ".react-state-link-choose-location",
        "city_input": ".react-autosuggest__input",
        "autocomplete_container": ".react-autosuggest__suggestions-container",
        "autocomplete_suggestion": ".react-autosuggest__suggestion",
        "save_city_button": ".location-choice-panel .primary.button",
        "location_panel": ".location-choice-panel",
        # Store locator page (/locations)
        "store_search_input": ".store-locations input[name='name']",
        "store_search_button": ".store-locations button[type='submit']",
        # Product elements - verified from panago.com/menu
        "product_card": "ul.products > li, .product-group",
        "product_name": ".product-title h4, h4.product-title, .product-header h4, .product-group-title",
        "product_price": ".product-header .price, .prices li span, .price",
        # Size/price pairs for products with multiple sizes (pizzas, etc.)
        "price_list_item": ".prices li",
        "price_size_label": "label",
        "price_value": "span",
        # Dips/extras use a different format: "Product Name / $1.25" in a label
        "product_price_label": ".qty-picker label span",
        # Navigation
        "category_link": "ul.menu li a[href*='{category}']",
        # Loading states
        "loading_spinner": ".loading, .spinner, [class*='loading']",
    }

    def __init__(
        self,
        config: AutomationConfig,
        locations_path: Optional[Path] = None,
        base_url: str = "https://www.panago.com",
        min_delay_ms: int = 3000,
        max_delay_ms: int = 6000,
    ) -> None:
        """Initialize the automation engine.

        Args:
            config: Automation configuration settings.
            locations_path: Path to locations YAML file (optional).
            base_url: Base URL for the target environment (QA or Production).
            min_delay_ms: Minimum delay between actions in milliseconds.
            max_delay_ms: Maximum delay between actions in milliseconds.
        """
        self.config = config
        self.base_url = base_url
        self.min_delay_ms = min_delay_ms
        self.max_delay_ms = max_delay_ms
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._locations_path = locations_path
        self._locations: list[LocationConfig] = []

    def run_price_collection(self) -> list[PriceRecord]:
        """Synchronous entry point - runs async collection.

        Returns:
            List of all collected price records.
        """
        return asyncio.run(self._run_async())

    async def _run_async(self) -> list[PriceRecord]:
        """Async implementation with parallel browser contexts.

        Returns:
            List of all collected price records.
        """
        self._semaphore = asyncio.Semaphore(self.config.max_concurrent)
        all_prices: list[PriceRecord] = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=self.config.headless,
                args=[
                    "--disable-gpu",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                ],
            )

            # Load locations from config
            locations = self._get_locations()
            if not locations:
                logger.warning("no_locations_configured")
                await browser.close()
                return all_prices

            logger.info(
                "starting_collection",
                location_count=len(locations),
                max_concurrent=self.config.max_concurrent,
            )

            # Process all locations in parallel (bounded by semaphore)
            tasks = [
                self._validate_location(browser, loc)
                for loc in locations
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Collect successful results
            for i, result in enumerate(results):
                if isinstance(result, list):
                    all_prices.extend(result)
                elif isinstance(result, Exception):
                    logger.error(
                        "location_failed",
                        location=locations[i].store_name,
                        error=str(result),
                    )

            await browser.close()

        logger.info("collection_complete", total_prices=len(all_prices))
        return all_prices

    def _get_locations(self) -> list[LocationConfig]:
        """Get location configurations.

        Returns:
            List of LocationConfig objects.
        """
        if self._locations:
            return self._locations

        if self._locations_path and self._locations_path.exists():
            self._locations = load_locations(self._locations_path)
        else:
            # Default test locations if no config provided
            self._locations = [
                LocationConfig("Vancouver Downtown", "1234 Main Street, Vancouver, BC V5K 0A1", "BC"),
                LocationConfig("Calgary Centre", "5678 Centre Street, Calgary, AB T2E 2R8", "AB"),
                LocationConfig("Toronto East", "910 Queen Street, Toronto, ON M4M 1J5", "ON"),
            ]
            logger.warning("using_default_locations", count=len(self._locations))

        return self._locations

    def set_locations(self, locations: list[LocationConfig]) -> None:
        """Set locations programmatically.

        Args:
            locations: List of LocationConfig objects.
        """
        self._locations = locations

    async def _validate_location(
        self, browser: Browser, location: LocationConfig
    ) -> list[PriceRecord]:
        """Validate prices for a single location with concurrency control.

        Args:
            browser: Playwright browser instance.
            location: Location configuration to validate.

        Returns:
            List of price records for the location.
        """
        async with self._semaphore:
            context = await self._create_optimized_context(browser)

            try:
                page = await context.new_page()
                return await self._collect_prices(page, location)
            finally:
                await context.close()

    async def _create_optimized_context(self, browser: Browser) -> BrowserContext:
        """Create browser context with resource blocking.

        Args:
            browser: Playwright browser instance.

        Returns:
            Configured browser context.
        """
        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            locale="en-CA",
            service_workers="block",  # Required for route interception
        )

        # Block unnecessary resources for faster loading
        for pattern in self.BLOCKED_RESOURCES:
            await context.route(pattern, lambda route: route.abort())

        return context

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((TimeoutError, ConnectionError)),
        reraise=True,
    )
    async def _collect_prices(
        self, page: Page, location: LocationConfig
    ) -> list[PriceRecord]:
        """Collect all product prices for a single location with retry.

        Includes comprehensive rate limiting to minimize site impact.

        Args:
            page: Playwright page instance.
            location: Location to collect prices for.

        Returns:
            List of price records.
        """
        logger.info(
            "collecting_prices",
            store=location.store_name,
            province=location.province,
            base_url=self.base_url,
        )

        # Initial delay before starting
        await self._wait_with_jitter()

        await page.goto(self.base_url, wait_until="domcontentloaded")

        # Delay after page load
        await self._wait_with_jitter()

        # Select location
        await self._select_location(page, location.address)

        # Delay after location selection
        await self._wait_with_jitter()

        # Collect prices from all categories
        prices: list[PriceRecord] = []
        total_categories = len(self.CATEGORIES)

        for idx, category in enumerate(self.CATEGORIES, 1):
            try:
                logger.info(
                    "scraping_category",
                    category=category,
                    progress=f"{idx}/{total_categories}",
                    store=location.store_name,
                )

                category_prices = await self._scrape_category(
                    page, category, location
                )
                prices.extend(category_prices)

                logger.info(
                    "category_complete",
                    category=category,
                    products_found=len(category_prices),
                )

                # Delay between categories (use full configured delay)
                if idx < total_categories:
                    await self._wait_with_jitter()

            except Exception as e:
                logger.warning(
                    "category_scrape_failed",
                    category=category,
                    store=location.store_name,
                    error=str(e),
                )
                # Still wait even on failure to maintain rate limiting
                await self._wait_with_jitter()

        logger.info(
            "collected_location",
            store=location.store_name,
            price_count=len(prices),
        )
        return prices

    async def _select_location(self, page: Page, city: str) -> None:
        """Handle city selection via the React Autosuggest modal.

        The Panago website uses a city picker modal that auto-detects location.
        Flow:
        1. Click the location trigger to open the modal
        2. Clear and type the city name in the autosuggest input
        3. Wait for and click the first suggestion
        4. Click "Save City" button

        Args:
            page: Playwright page instance.
            city: City name to enter (e.g., "Vancouver").
        """
        logger.info("selecting_location", city=city)

        # Step 1: Click location trigger to open the city picker modal
        try:
            trigger = page.locator(self.SELECTORS["location_trigger"])
            if await trigger.is_visible():
                await trigger.click()
                logger.debug("clicked_location_trigger")
                await asyncio.sleep(1)
        except Exception as e:
            logger.debug("location_trigger_click_skipped", error=str(e))

        # Step 2: Wait for modal and find city input
        try:
            await page.wait_for_selector(
                self.SELECTORS["city_input"],
                state="visible",
                timeout=5000,
            )
        except Exception:
            logger.warning("city_input_not_visible")

        # Step 3: Clear and type the city name
        city_input = page.locator(self.SELECTORS["city_input"])
        await city_input.click()
        await asyncio.sleep(0.5)

        # Triple-click to select all, then type new value
        await city_input.click(click_count=3)
        await asyncio.sleep(0.3)
        await page.keyboard.type(city, delay=50)  # Type slowly like a human
        logger.debug("typed_city", city=city)

        # Step 4: Wait for autocomplete suggestions
        await asyncio.sleep(1.5)  # Wait for suggestions to appear

        # Step 5: Click the first suggestion
        try:
            suggestion_selector = self.SELECTORS["autocomplete_suggestion"]
            await page.wait_for_selector(
                suggestion_selector,
                state="visible",
                timeout=5000,
            )
            first_suggestion = page.locator(suggestion_selector).first
            suggestion_text = await first_suggestion.text_content()
            logger.debug("clicking_suggestion", suggestion=suggestion_text)
            await first_suggestion.click()
            await asyncio.sleep(1)
        except Exception as e:
            logger.warning("no_suggestions_found", error=str(e))

        # Step 6: Click Save City button
        try:
            save_button = page.locator(self.SELECTORS["save_city_button"])
            if await save_button.is_visible():
                await save_button.click()
                logger.debug("clicked_save_city")
                await asyncio.sleep(2)
        except Exception as e:
            logger.warning("save_button_not_found", error=str(e))

        # Wait for page to update
        await page.wait_for_load_state("networkidle")
        logger.info("location_selected", city=city)

    async def _scrape_category(
        self, page: Page, category: str, location: LocationConfig
    ) -> list[PriceRecord]:
        """Scrape all products and prices from a category.

        Includes delays to minimize site impact.

        Args:
            page: Playwright page instance.
            category: Category name to scrape.
            location: Current location configuration.

        Returns:
            List of price records for the category.
        """
        # Navigate directly to category URL (more reliable than clicking)
        category_url = self.CATEGORY_URLS.get(category, f"/menu/{category}")
        try:
            await page.goto(
                f"{self.base_url}{category_url}",
                wait_until="domcontentloaded",
                timeout=60000,  # 60 second timeout for slow staging site
            )
        except Exception as e:
            logger.warning("page_load_slow", url=category_url, error=str(e))

        # Wait for page content to load
        await asyncio.sleep(3)  # Give React time to render

        products = page.locator(self.SELECTORS["product_card"])
        count = await products.count()

        prices: list[PriceRecord] = []
        for i in range(count):
            product = products.nth(i)
            try:
                # Use .first to handle multiple matching elements (strict mode)
                # Add timeout to prevent long hangs on pages with different structure
                name_locator = product.locator(self.SELECTORS["product_name"])
                name = None
                try:
                    if await name_locator.count() > 0:
                        name = await name_locator.first.text_content(timeout=5000)
                except Exception:
                    pass  # Skip if name not found

                # Check for products with multiple size/price variants (pizzas, etc.)
                price_list_items = product.locator(self.SELECTORS["price_list_item"])
                price_list_count = await price_list_items.count()

                if price_list_count > 1:
                    # Multiple sizes - extract each size/price pair
                    for j in range(price_list_count):
                        item = price_list_items.nth(j)
                        try:
                            # Get size label (e.g., "Extra-Large:", "Large:", etc.)
                            size_label = item.locator(self.SELECTORS["price_size_label"])
                            size = None
                            if await size_label.count() > 0:
                                size_text = await size_label.first.text_content(timeout=5000)
                                # Clean up: remove trailing colon and whitespace
                                size = size_text.strip().rstrip(":").strip() if size_text else None

                            # Get price value
                            price_elem = item.locator(self.SELECTORS["price_value"])
                            if await price_elem.count() > 0:
                                price_text = await price_elem.first.text_content(timeout=5000)
                                if price_text:
                                    prices.append(
                                        PriceRecord(
                                            province=location.province,
                                            store_name=location.store_name,
                                            category=category,
                                            product_name=name.strip() if name else "",
                                            actual_price=self._parse_price(price_text),
                                            raw_price_text=price_text,
                                            size=size,
                                        )
                                    )
                        except Exception as e:
                            logger.debug(
                                "size_extraction_failed",
                                product_index=i,
                                size_index=j,
                                error=str(e),
                            )
                else:
                    # Single price or different format
                    price_locator = product.locator(self.SELECTORS["product_price"])
                    price_count = await price_locator.count()
                    price_text = None

                    if price_count > 0:
                        # Standard format: price in dedicated element
                        price_text = await price_locator.first.text_content(timeout=5000)
                    else:
                        # Dips/extras format: "Product Name / $1.25" in label span
                        label_locator = product.locator(self.SELECTORS["product_price_label"])
                        if await label_locator.count() > 0:
                            label_text = await label_locator.first.text_content(timeout=5000)
                            # Extract price from "Product Name / $1.25" format
                            if label_text and "$" in label_text:
                                price_text = label_text

                    if not price_text:
                        logger.debug("no_price_found", product_index=i, category=category)
                        continue

                    prices.append(
                        PriceRecord(
                            province=location.province,
                            store_name=location.store_name,
                            category=category,
                            product_name=name.strip() if name else "",
                            actual_price=self._parse_price(price_text),
                            raw_price_text=price_text or "",
                            size=None,
                        )
                    )
            except Exception as e:
                logger.warning(
                    "product_extraction_failed",
                    category=category,
                    product_index=i,
                    error=str(e),
                )

        return prices

    def _parse_price(self, price_text: Optional[str]) -> Decimal:
        """Parse price string to Decimal.

        Handles formats:
        - "$26.50" (standard)
        - "Product Name / $1.25" (dips/label format)
        - "$6.85 8 pc" (with quantity suffix)

        Args:
            price_text: Raw price string.

        Returns:
            Parsed Decimal value, or Decimal('0') if unparseable.
        """
        if not price_text:
            return Decimal("0")

        cleaned = price_text.replace(",", "")

        # First try to match a price with $ prefix (most reliable)
        match = re.search(r"\$(\d+\.?\d*)", cleaned)
        if match:
            return Decimal(match.group(1))

        # Fallback: match the last number in the string (for edge cases)
        matches = re.findall(r"(\d+\.?\d*)", cleaned)
        if matches:
            return Decimal(matches[-1])

        logger.warning("price_parse_failed", price_text=price_text)
        return Decimal("0")

    async def _wait_with_jitter(
        self, min_ms: Optional[int] = None, max_ms: Optional[int] = None
    ) -> None:
        """Wait with random jitter to appear human-like and reduce site impact.

        Uses configured delays by default, which respect safe mode settings.

        Args:
            min_ms: Minimum wait time in milliseconds (default: use configured).
            max_ms: Maximum wait time in milliseconds (default: use configured).
        """
        min_delay = min_ms if min_ms is not None else self.min_delay_ms
        max_delay = max_ms if max_ms is not None else self.max_delay_ms
        delay = random.uniform(min_delay, max_delay) / 1000
        logger.debug("waiting", delay_seconds=f"{delay:.1f}")
        await asyncio.sleep(delay)
