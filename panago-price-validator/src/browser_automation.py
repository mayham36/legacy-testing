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
    CATEGORIES = ["pizzas", "salads", "sides", "dips", "dessert", "beverages"]

    # Menu URL paths for each category
    CATEGORY_URLS = {
        "pizzas": "/menu/pizzas",
        "salads": "/menu/salads",
        "sides": "/menu/sides",
        "dips": "/menu/dips",
        "dessert": "/menu/dessert",  # Note: singular on panago.com
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
        "product_name": ".product-title h4, h4.product-title, .product-header h4",
        "product_price": ".product-header .price, .prices li span, .price",
        # Navigation
        "category_link": "ul.menu li a[href*='{category}']",
        # Loading states
        "loading_spinner": ".loading, .spinner, [class*='loading']",
    }

    def __init__(self, config: AutomationConfig, locations_path: Optional[Path] = None) -> None:
        """Initialize the automation engine.

        Args:
            config: Automation configuration settings.
            locations_path: Path to locations YAML file (optional).
        """
        self.config = config
        self.base_url = "https://www.panago.com"
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
        )

        await page.goto(self.base_url, wait_until="domcontentloaded")

        # Select location
        await self._select_location(page, location.address)

        # Add jitter delay to appear human-like
        await self._wait_with_jitter()

        # Collect prices from all categories
        prices: list[PriceRecord] = []

        for category in self.CATEGORIES:
            try:
                category_prices = await self._scrape_category(
                    page, category, location
                )
                prices.extend(category_prices)

                # Add delay between categories
                await self._wait_with_jitter(min_ms=1000, max_ms=2000)

            except Exception as e:
                logger.warning(
                    "category_scrape_failed",
                    category=category,
                    store=location.store_name,
                    error=str(e),
                )

        logger.info(
            "collected_location",
            store=location.store_name,
            price_count=len(prices),
        )
        return prices

    async def _select_location(self, page: Page, address: str) -> None:
        """Handle city selection via the React Autosuggest modal.

        The Panago website uses a city picker modal that auto-detects location.
        We need to:
        1. Click the location trigger to open the modal
        2. Clear and type the city name in the autosuggest input
        3. Wait for and select the first suggestion
        4. Click "Save City" button

        Args:
            page: Playwright page instance.
            address: City/address string to enter (e.g., "Vancouver, BC").
        """
        # Click location trigger to open the city picker modal
        try:
            await page.click(self.SELECTORS["location_trigger"])
            await page.wait_for_selector(
                self.SELECTORS["location_panel"],
                state="visible",
                timeout=5000,
            )
        except Exception:
            # Modal might already be visible or trigger is different
            logger.debug("location_trigger_click_skipped")

        # Find and fill the city input
        city_input = page.locator(self.SELECTORS["city_input"])
        await city_input.click()
        await city_input.fill("")  # Clear existing value
        await city_input.fill(address)

        # Wait for autocomplete suggestions to appear
        await asyncio.sleep(1)  # Brief pause for suggestions to load

        # Try to click a suggestion if available
        try:
            await page.wait_for_selector(
                self.SELECTORS["autocomplete_suggestion"],
                state="visible",
                timeout=3000,
            )
            await page.click(f"{self.SELECTORS['autocomplete_suggestion']} >> nth=0")
        except Exception:
            # No suggestions appeared, city might be exact match
            logger.debug("no_autocomplete_suggestions", city=address)

        # Click Save City button
        await page.click(self.SELECTORS["save_city_button"])
        await page.wait_for_load_state("networkidle")

    async def _scrape_category(
        self, page: Page, category: str, location: LocationConfig
    ) -> list[PriceRecord]:
        """Scrape all products and prices from a category.

        Args:
            page: Playwright page instance.
            category: Category name to scrape.
            location: Current location configuration.

        Returns:
            List of price records for the category.
        """
        # Navigate directly to category URL (more reliable than clicking)
        category_url = self.CATEGORY_URLS.get(category, f"/menu/{category}")
        await page.goto(f"{self.base_url}{category_url}", wait_until="networkidle")

        products = page.locator(self.SELECTORS["product_card"])
        count = await products.count()

        prices: list[PriceRecord] = []
        for i in range(count):
            product = products.nth(i)
            try:
                name = await product.locator(
                    self.SELECTORS["product_name"]
                ).text_content()
                price_text = await product.locator(
                    self.SELECTORS["product_price"]
                ).text_content()

                prices.append(
                    PriceRecord(
                        province=location.province,
                        store_name=location.store_name,
                        category=category,
                        product_name=name.strip() if name else "",
                        actual_price=self._parse_price(price_text),
                        raw_price_text=price_text or "",
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

        Args:
            price_text: Raw price string.

        Returns:
            Parsed Decimal value, or Decimal('0') if unparseable.
        """
        if not price_text:
            return Decimal("0")

        cleaned = price_text.replace(",", "")
        match = re.search(r"\$?(\d+\.?\d*)", cleaned)
        if match:
            return Decimal(match.group(1))

        logger.warning("price_parse_failed", price_text=price_text)
        return Decimal("0")

    async def _wait_with_jitter(
        self, min_ms: int = 2000, max_ms: int = 5000
    ) -> None:
        """Wait with random jitter to appear human-like.

        Args:
            min_ms: Minimum wait time in milliseconds.
            max_ms: Maximum wait time in milliseconds.
        """
        delay = random.uniform(min_ms, max_ms) / 1000
        await asyncio.sleep(delay)
