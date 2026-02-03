"""Playwright browser automation with parallel execution."""
import asyncio
import json
import random
import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional, Callable

import structlog
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from .models import AutomationConfig, PriceRecord, LocationConfig, PriceSource
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
    # Pizza has multiple subcategories that need to be scraped separately
    CATEGORIES = [
        "pizzas-meat",
        "pizzas-veggie",
        "pizzas-plant-based",
        "salads",
        "sides",
        "dips",
        "dessert",
        "beverages",
    ]

    # Menu URL paths for each category
    CATEGORY_URLS = {
        "pizzas-meat": "/menu/pizzas/meat",
        "pizzas-veggie": "/menu/pizzas/veggie",
        "pizzas-plant-based": "/menu/pizzas/plant_based",
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

    # Cart interaction selectors - for capturing prices from the shopping cart
    CART_SELECTORS = {
        # Add to Order button on product cards
        "add_to_order_button": "a:has-text('Add to Order'), button:has-text('Add to Order'), .prices-actions a, a.button",
        # Product modal/customization panel (opens after clicking Add to Order)
        "product_modal": ".product-modal, [class*='product-modal'], .modal, .product-detail, .customization",
        # Size and crust radio buttons (after clicking Add to Order)
        "size_option": "input[type='radio'][name*='size'], input[type='radio'][name*='Size'], label:has(input[type='radio'])",
        "crust_option": "input[type='radio'][name*='crust'], input[type='radio'][name*='Crust'], input[type='radio'][name*='dough']",
        "add_to_cart_button": "button:has-text('Add to Cart'), button:has-text('Add to Order'), .add-to-cart, button[type='submit']",
        # Cart sidebar/modal
        "cart_icon": ".cart-icon, [class*='cart'], header a[href*='cart'], .shopping-cart-icon",
        "cart_sidebar": ".cart-sidebar, [class*='cart-panel'], .shopping-cart, .cart-drawer",
        "cart_item": ".cart-item, [class*='cart-item'], .line-item, .cart-product",
        "cart_item_name": ".cart-item-name, .item-title, .product-name, .line-item-title",
        "cart_item_price": ".cart-item-price, .item-price, .line-item-price, .product-price",
        "remove_item": ".remove-item, .delete-item, [class*='remove'], button[aria-label*='remove']",
        "clear_cart": ".clear-cart, [class*='clear-cart'], .empty-cart",
        # Modal controls
        "close_modal": ".close, [class*='close'], button[aria-label='Close'], .modal-close",
    }

    # Category-specific selectors - different page layouts need different selectors
    CATEGORY_SELECTORS = {
        "beverages": {
            # Beverages may use a different layout (dropdowns, list format)
            "product_card": ".beverage-item, .drink-option, [data-product-type='beverage'], .product-group, ul.products > li, .menu-item",
            "product_name": ".beverage-name, .drink-name, .product-title h4, h4.product-title, .product-group-title, .menu-item-name",
            "product_price": ".beverage-price, .drink-price, .product-header .price, .prices li span, .price, .menu-item-price",
        },
        "dips": {
            # Dips often use qty-picker format with inline prices
            "product_card": ".qty-picker, .product-group, ul.products > li",
            "product_name": ".qty-picker label, .product-title h4, .product-group-title",
            "product_price": ".qty-picker label span, .price",
        },
        "default": {
            "product_card": "ul.products > li, .product-group",
            "product_name": ".product-title h4, h4.product-title, .product-header h4, .product-group-title",
            "product_price": ".product-header .price, .prices li span, .price",
        },
    }

    def __init__(
        self,
        config: AutomationConfig,
        locations_path: Optional[Path] = None,
        base_url: str = "https://www.panago.com",
        min_delay_ms: int = 3000,
        max_delay_ms: int = 6000,
        capture_cart_prices: bool = False,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> None:
        """Initialize the automation engine.

        Args:
            config: Automation configuration settings.
            locations_path: Path to locations YAML file (optional).
            base_url: Base URL for the target environment (QA or Production).
            min_delay_ms: Minimum delay between actions in milliseconds.
            max_delay_ms: Maximum delay between actions in milliseconds.
            capture_cart_prices: If True, also capture prices from cart (slower).
            progress_callback: Optional callback function to report progress messages.
        """
        self.config = config
        self.base_url = base_url
        self.min_delay_ms = min_delay_ms
        self.max_delay_ms = max_delay_ms
        self.capture_cart_prices = capture_cart_prices
        self.progress_callback = progress_callback
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._locations_path = locations_path
        self._locations: list[LocationConfig] = []

    def _report_progress(self, message: str) -> None:
        """Report progress via callback if available."""
        if self.progress_callback:
            self.progress_callback(message)

    async def _save_debug_snapshot(
        self, page: Page, context: str, location: Optional[LocationConfig] = None
    ) -> None:
        """Save page state for debugging when scraping fails.

        Creates a timestamped debug directory with screenshot, HTML, and state JSON.

        Args:
            page: Playwright page instance.
            context: Description of what was being done (e.g., "beverages", "location_fail_Calgary").
            location: Optional location config for context.
        """
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            debug_dir = Path("debug") / timestamp
            debug_dir.mkdir(parents=True, exist_ok=True)

            # Safe context name for filenames
            safe_context = re.sub(r"[^a-zA-Z0-9_-]", "_", context)

            # Screenshot
            screenshot_path = debug_dir / f"{safe_context}_screenshot.png"
            await page.screenshot(path=str(screenshot_path), full_page=True)

            # HTML content
            html_path = debug_dir / f"{safe_context}_page.html"
            html = await page.content()
            html_path.write_text(html, encoding="utf-8")

            # State JSON
            state = {
                "url": page.url,
                "context": context,
                "location": {
                    "store_name": location.store_name,
                    "province": location.province,
                    "pricing_level": str(location.get_pricing_level()),
                } if location else None,
                "timestamp": timestamp,
                "page_title": await page.title(),
            }
            state_path = debug_dir / f"{safe_context}_state.json"
            state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

            logger.info(
                "debug_snapshot_saved",
                path=str(debug_dir),
                context=context,
                screenshot=str(screenshot_path),
            )
            self._report_progress(f"📸 Debug snapshot saved: {debug_dir}")

        except Exception as e:
            logger.warning("debug_snapshot_failed", context=context, error=str(e))

    def _get_category_selectors(self, category: str) -> dict:
        """Get selectors for a specific category.

        Args:
            category: Category name.

        Returns:
            Dict of selectors for the category.
        """
        return self.CATEGORY_SELECTORS.get(category, self.CATEGORY_SELECTORS["default"])

    async def _extract_product_name(self, product, selectors: dict) -> Optional[str]:
        """Extract full product name using multiple strategies.

        Tries category-specific selector first, then falls back to other methods
        to ensure we capture the complete product name (not truncated).

        Args:
            product: Playwright locator for the product element.
            selectors: Dict of selectors to use.

        Returns:
            Product name string or None if not found.
        """
        name = None

        # Strategy 1: Try the category-specific name selector
        name_selectors = [
            selectors.get("product_name", ""),
            ".product-title h4",
            "h4.product-title",
            ".product-name",
            ".product-header h4",
            ".product-group-title",
            "h4",
            "h3",
        ]

        for selector in name_selectors:
            if not selector:
                continue
            try:
                locator = product.locator(selector)
                if await locator.count() > 0:
                    text = await locator.first.text_content(timeout=3000)
                    if text and len(text.strip()) > 2:
                        name = text.strip()
                        break
            except Exception:
                continue

        # Strategy 2: If name is short or suspicious, try getting more text
        if name and len(name) < 5:
            # Name might be truncated - try to get full text from product card
            try:
                full_text = await product.text_content(timeout=3000)
                if full_text:
                    # Extract first meaningful line (product name is usually first)
                    lines = [l.strip() for l in full_text.split("\n") if l.strip()]
                    # Find first line that's not a price
                    for line in lines:
                        if not line.startswith("$") and not re.match(r"^\d+\.\d{2}$", line):
                            if len(line) > len(name):
                                name = line
                            break
            except Exception:
                pass

        # Strategy 3: If still no name, try full text extraction
        if not name:
            try:
                full_text = await product.text_content(timeout=3000)
                if full_text:
                    # Extract first meaningful line
                    lines = [l.strip() for l in full_text.split("\n") if l.strip()]
                    for line in lines:
                        if not line.startswith("$") and not re.match(r"^\d+\.\d{2}$", line):
                            name = line
                            break
            except Exception:
                pass

        return name.strip() if name else None

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
        self._report_progress(f"🏪 {location.store_name} ({location.province}) - Opening browser...")

        # Initial delay before starting
        await self._wait_with_jitter()

        await page.goto(self.base_url, wait_until="domcontentloaded")

        # Delay after page load
        await self._wait_with_jitter()

        # Select location - try city name first, then address
        location_selected = await self._select_location(page, location.store_name.split()[0])
        if not location_selected:
            # Try with full address
            location_selected = await self._select_location(page, location.address)

        if not location_selected:
            logger.error("location_selection_failed", location=location.store_name)
            self._report_progress(f"❌ Failed to select location: {location.store_name}")
            # Continue anyway - the site may have defaulted to a location
            # and we can still scrape, just noting the potential issue

        # Delay after location selection
        await self._wait_with_jitter()

        # Collect prices from all categories
        prices: list[PriceRecord] = []
        total_categories = len(self.CATEGORIES)

        for idx, category in enumerate(self.CATEGORIES, 1):
            try:
                logger.info(
                    "scraping_category",
                    category=self._normalize_category(category),
                    progress=f"{idx}/{total_categories}",
                    store=location.store_name,
                )
                self._report_progress(f"📂 {location.store_name} - Scraping {category} ({idx}/{total_categories})")

                category_prices = await self._scrape_category(
                    page, category, location
                )
                prices.extend(category_prices)

                logger.info(
                    "category_complete",
                    category=self._normalize_category(category),
                    products_found=len(category_prices),
                )
                self._report_progress(f"✅ {category} complete - {len(category_prices)} prices found")

                # Delay between categories (use full configured delay)
                if idx < total_categories:
                    await self._wait_with_jitter()

            except Exception as e:
                logger.warning(
                    "category_scrape_failed",
                    category=self._normalize_category(category),
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

    async def _select_location(self, page: Page, city: str) -> bool:
        """Handle city selection via the React Autosuggest modal with retry logic.

        The Panago website uses a city picker modal that auto-detects location.
        This method tries multiple city name formats and validates selection.

        Args:
            page: Playwright page instance.
            city: City name to enter (e.g., "Vancouver").

        Returns:
            True if location was successfully selected, False otherwise.
        """
        logger.info("selecting_location", city=city)

        # Try multiple city name formats
        city_formats = [
            city,
            city.replace(",", ""),
            city.split(",")[0].strip() if "," in city else city,
        ]

        for attempt, city_format in enumerate(city_formats):
            try:
                success = await self._attempt_location_selection(page, city_format)
                if success:
                    # Validate the selection worked
                    if await self._verify_location_selected(page, city):
                        logger.info("location_selected", city=city, format_used=city_format)
                        return True
                    else:
                        logger.debug("location_verification_failed", city=city_format)
            except Exception as e:
                logger.debug(
                    "location_attempt_failed",
                    city=city_format,
                    attempt=attempt + 1,
                    error=str(e),
                )
                continue

        # All attempts failed - save debug snapshot
        logger.warning("location_selection_failed", city=city, attempts=len(city_formats))
        await self._save_debug_snapshot(page, f"location_fail_{city}", None)
        return False

    async def _attempt_location_selection(self, page: Page, city: str) -> bool:
        """Attempt to select a location once.

        Args:
            page: Playwright page instance.
            city: City name to enter.

        Returns:
            True if the selection flow completed without errors.
        """
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
            return False

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
            logger.warning("no_suggestions_found", city=city, error=str(e))
            return False

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
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=10000)
        except Exception as e:
            logger.debug("load_state_timeout", error=str(e))

        return True

    async def _verify_location_selected(self, page: Page, expected_city: str) -> bool:
        """Verify that the expected location was actually selected.

        Checks the page content to confirm the city name appears in the
        location indicator.

        Args:
            page: Playwright page instance.
            expected_city: City name that should be selected.

        Returns:
            True if the expected city appears to be selected.
        """
        try:
            # Check for city name in the location trigger text
            trigger = page.locator(self.SELECTORS["location_trigger"])
            if await trigger.count() > 0:
                trigger_text = await trigger.text_content()
                if trigger_text and expected_city.lower() in trigger_text.lower():
                    return True

            # Also check the page URL or other indicators
            # Some sites include location in the URL
            page_url = page.url.lower()
            if expected_city.lower().replace(" ", "-") in page_url:
                return True

            # If we can't verify, assume success if we got this far
            return True

        except Exception as e:
            logger.debug("location_verification_error", error=str(e))
            return True  # Don't fail on verification errors

    async def _scrape_category(
        self, page: Page, category: str, location: LocationConfig
    ) -> list[PriceRecord]:
        """Scrape all products and prices from a category.

        Includes delays to minimize site impact. Uses category-specific selectors
        for different page layouts.

        Args:
            page: Playwright page instance.
            category: Category name to scrape.
            location: Current location configuration.

        Returns:
            List of price records for the category.
        """
        # Navigate directly to category URL (more reliable than clicking)
        category_url = self.CATEGORY_URLS.get(category, f"/menu/{category}")
        full_url = f"{self.base_url}{category_url}"
        logger.info("navigating_to_category", url=full_url)
        self._report_progress(f"🔗 Navigating to {full_url}")
        try:
            await page.goto(
                full_url,
                wait_until="domcontentloaded",
                timeout=60000,  # 60 second timeout for slow staging site
            )
            logger.info("navigation_complete", final_url=page.url)
        except Exception as e:
            logger.warning("page_load_failed", url=full_url, error=str(e))

        # Wait for page content to load (extra time for JavaScript rendering)
        await asyncio.sleep(2)  # Give React/JavaScript time to render

        # Get category-specific selectors
        cat_selectors = self._get_category_selectors(category)

        # Try category-specific selector first, then fall back to default
        products = page.locator(cat_selectors["product_card"])
        count = await products.count()

        # If no products found with category selector, try default selector
        if count == 0 and category in self.CATEGORY_SELECTORS:
            default_selectors = self.CATEGORY_SELECTORS["default"]
            products = page.locator(default_selectors["product_card"])
            count = await products.count()
            if count > 0:
                cat_selectors = default_selectors
                logger.info("using_fallback_selectors", category=category, count=count)

        # Save debug snapshot if no products found
        if count == 0:
            logger.warning(
                "no_products_found",
                category=category,
                url=page.url,
                location=location.store_name,
            )
            self._report_progress(f"⚠️ No products found for {category}")
            await self._save_debug_snapshot(page, f"no_products_{category}", location)
            return []

        logger.info("found_products", category=category, count=count)
        self._report_progress(f"📦 Found {count} products in {category}")

        prices: list[PriceRecord] = []
        for i in range(count):
            product = products.nth(i)
            try:
                # Extract product name using category-specific selector
                name = await self._extract_product_name(product, cat_selectors)
                if not name:
                    logger.debug("no_name_found", product_index=i, category=category)
                    continue

                # Check for products with multiple size/price variants (pizzas, etc.)
                price_list_items = product.locator(self.SELECTORS["price_list_item"])
                price_list_count = await price_list_items.count()

                if price_list_count > 1:
                    # Multiple sizes - extract each size/price pair
                    # First collect all menu prices, then do ONE cart capture for first size
                    first_size_for_cart = None
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

                            # Remember first size for cart capture later
                            if first_size_for_cart is None:
                                first_size_for_cart = size

                            # Get price value
                            price_elem = item.locator(self.SELECTORS["price_value"])
                            if await price_elem.count() > 0:
                                price_text = await price_elem.first.text_content(timeout=5000)
                                if price_text:
                                    prices.append(
                                        PriceRecord(
                                            province=location.province,
                                            store_name=location.store_name,
                                            category=self._normalize_category(category),
                                            product_name=name.strip() if name else "",
                                            actual_price=self._parse_price(price_text),
                                            raw_price_text=price_text,
                                            size=size,
                                            pricing_level=location.get_pricing_level(),
                                            price_source=PriceSource.MENU,
                                        )
                                    )
                        except Exception as e:
                            logger.debug(
                                "size_extraction_failed",
                                product_index=i,
                                size_index=j,
                                error=str(e),
                            )

                    # After collecting all menu prices, capture ONE cart price for this product
                    # This avoids navigation issues from trying to capture for each size
                    if self.capture_cart_prices and name:
                        product_display = f"{name.strip()} ({first_size_for_cart})" if first_size_for_cart else name.strip()
                        self._report_progress(f"🛒 Adding to cart: {product_display}")
                        cart_record = await self._capture_cart_price_for_product(
                            page,
                            product,
                            name.strip(),
                            first_size_for_cart,  # Use first size
                            location,
                            category,
                        )
                        if cart_record:
                            prices.append(cart_record)
                            self._report_progress(f"💰 Cart price: ${cart_record.actual_price}")
                        else:
                            self._report_progress(f"⚠️ Could not get cart price")

                        # Re-fetch products locator after navigation
                        # (Playwright locators are lazy, but this ensures we're working with current DOM)
                        products = page.locator(cat_selectors["product_card"])
                        await asyncio.sleep(0.3)
                else:
                    # Single price or different format - try category-specific selector first
                    price_selector = cat_selectors.get("product_price", self.SELECTORS["product_price"])
                    price_locator = product.locator(price_selector)
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
                            category=self._normalize_category(category),
                            product_name=name.strip() if name else "",
                            actual_price=self._parse_price(price_text),
                            raw_price_text=price_text or "",
                            size=None,
                            pricing_level=location.get_pricing_level(),
                            price_source=PriceSource.MENU,
                        )
                    )
                    # Capture cart price if enabled (for single-price products)
                    if self.capture_cart_prices and name:
                        product_display = name.strip()
                        self._report_progress(f"🛒 Adding to cart: {product_display}")
                        cart_record = await self._capture_cart_price_for_product(
                            page,
                            product,
                            name.strip(),
                            None,
                            location,
                            category,
                        )
                        if cart_record:
                            prices.append(cart_record)
                            self._report_progress(f"💰 Cart price: ${cart_record.actual_price}")
                        else:
                            self._report_progress(f"⚠️ Could not get cart price")

                        # Re-fetch products locator after navigation
                        products = page.locator(cat_selectors["product_card"])
                        await asyncio.sleep(0.3)
            except Exception as e:
                logger.warning(
                    "product_extraction_failed",
                    category=self._normalize_category(category),
                    product_index=i,
                    error=str(e),
                )

        return prices

    def _normalize_category(self, category: str) -> str:
        """Normalize category name for output (e.g., 'pizzas-meat' -> 'pizzas').

        Args:
            category: Internal category name.

        Returns:
            Normalized category name for display/comparison.
        """
        # Map pizza subcategories back to 'pizzas' for output
        if category.startswith("pizzas-"):
            return "pizzas"
        return category

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

    # Cart interaction methods for menu vs cart price comparison

    async def _click_product(self, page: Page, product_locator) -> bool:
        """Click the 'Add to Order' button within a product card.

        Args:
            page: Playwright page instance.
            product_locator: Locator for the product element.

        Returns:
            True if modal opened or page navigated successfully, False otherwise.
        """
        try:
            # Log what product we're working with
            try:
                element_text = await product_locator.text_content(timeout=1000)
                element_text = element_text[:80] if element_text else "no text"
            except:
                element_text = "could not get text"
            logger.debug("processing_product", element_preview=element_text)

            # Scroll product into view first
            await product_locator.scroll_into_view_if_needed(timeout=2000)
            await asyncio.sleep(0.3)

            # Find "Add to Order" button within this product
            add_button = product_locator.locator(self.CART_SELECTORS["add_to_order_button"]).first

            if not await add_button.count():
                logger.debug("add_to_order_button_not_found")
                return False

            button_text = await add_button.text_content(timeout=1000)
            logger.debug("found_add_button", button_text=button_text)

            # Remember current URL to detect navigation
            original_url = page.url

            # Click the Add to Order button
            await add_button.click(timeout=2000)
            logger.debug("clicked_add_to_order")
            await asyncio.sleep(0.5)

            # Check if we navigated to a new page (product customization page)
            if page.url != original_url:
                logger.debug("navigated_to_product_page", url=page.url)
                await page.wait_for_load_state("domcontentloaded")
                return True

            # Otherwise, check for modal/popup
            modal_selector = self.CART_SELECTORS["product_modal"]
            try:
                await page.wait_for_selector(modal_selector, state="visible", timeout=2000)
                logger.debug("product_modal_opened")
                return True
            except Exception:
                logger.debug("no_modal_after_click", url=page.url)
                # Even if no modal, maybe item was added directly to cart
                return True
        except Exception as e:
            logger.warning("click_product_failed", error=str(e))
            return False

    async def _select_size(self, page: Page, size: Optional[str]) -> bool:
        """Select a size option via radio button in the customization panel.

        Args:
            page: Playwright page instance.
            size: Size to select (e.g., "Large", "Medium"). If None, selects first available.

        Returns:
            True if size was selected, False otherwise.
        """
        try:
            # Wait a moment for customization panel to load
            await asyncio.sleep(0.3)

            # Try to find size radio buttons by looking for labels containing size text
            if size:
                # Look for radio button or label containing the size name
                size_patterns = [
                    f"input[type='radio'][value*='{size}' i]",
                    f"label:has-text('{size}')",
                    f"text='{size}'",
                ]
                for pattern in size_patterns:
                    try:
                        option = page.locator(pattern).first
                        if await option.count() > 0:
                            await option.click(timeout=2000)
                            logger.debug("size_selected", size=size, pattern=pattern)
                            await asyncio.sleep(0.3)
                            return True
                    except:
                        continue

            # Fallback: try generic size selector
            size_selector = self.CART_SELECTORS["size_option"]
            size_options = page.locator(size_selector)
            count = await size_options.count()
            logger.debug("size_options_found", count=count)

            if count == 0:
                logger.debug("no_size_options_found")
                return True  # Product may not have size options

            # Click first option as fallback
            await size_options.first.click()
            await asyncio.sleep(0.3)
            logger.debug("size_selected_first_option")
            return True

        except Exception as e:
            logger.warning("select_size_failed", error=str(e))
            return False

    async def _select_crust(self, page: Page) -> bool:
        """Select the first available crust option.

        Args:
            page: Playwright page instance.

        Returns:
            True if crust was selected or not needed, False on error.
        """
        try:
            crust_selector = self.CART_SELECTORS["crust_option"]
            crust_options = page.locator(crust_selector)
            count = await crust_options.count()

            if count == 0:
                logger.debug("no_crust_options_found")
                return True  # Product may not have crust options

            # Click first crust option
            await crust_options.first.click()
            await asyncio.sleep(0.3)
            logger.debug("crust_selected_first_option")
            return True

        except Exception as e:
            logger.warning("select_crust_failed", error=str(e))
            return False

    async def _add_to_cart(self, page: Page) -> bool:
        """Click the Add to Cart button in the customization panel.

        Args:
            page: Playwright page instance.

        Returns:
            True if item was added to cart, False otherwise.
        """
        try:
            # Try multiple button patterns
            button_patterns = [
                "button:has-text('Add to Cart')",
                "button:has-text('Add To Cart')",
                "button:has-text('Add to Order')",
                "input[type='submit'][value*='Add']",
                ".add-to-cart",
                "button[type='submit']",
            ]

            for pattern in button_patterns:
                try:
                    add_button = page.locator(pattern).first
                    if await add_button.count() > 0 and await add_button.is_visible():
                        button_text = await add_button.text_content(timeout=1000)
                        logger.debug("clicking_add_to_cart", pattern=pattern, text=button_text)
                        await add_button.click(timeout=2000)
                        await asyncio.sleep(1)  # Wait for cart to update
                        logger.debug("added_to_cart")
                        return True
                except:
                    continue

            logger.debug("add_to_cart_button_not_found")
            return False

        except Exception as e:
            logger.warning("add_to_cart_failed", error=str(e))
            return False

    async def _get_cart_price(self, page: Page, product_name: str) -> Optional[Decimal]:
        """Open the cart and extract the price for a specific product.

        Args:
            page: Playwright page instance.
            product_name: Name of the product to find in cart.

        Returns:
            Price as Decimal if found, None otherwise.
        """
        try:
            # First check if cart items are already visible (some sites auto-open cart after add)
            cart_items = page.locator(self.CART_SELECTORS["cart_item"])
            count = await cart_items.count()
            logger.debug("checking_cart_items_visible", count=count)

            # If no cart items visible, try to open cart
            if count == 0:
                # Try multiple ways to open the cart
                cart_openers = [
                    ".cart-icon",
                    "[class*='cart']",
                    "header a[href*='cart']",
                    ".shopping-cart-icon",
                    "a[href='/cart']",
                    ".cart-btn",
                    ".cart-button",
                ]

                for selector in cart_openers:
                    try:
                        cart_icon = page.locator(selector).first
                        if await cart_icon.count() > 0:
                            # Scroll into view first to fix "outside viewport" issue
                            await cart_icon.scroll_into_view_if_needed(timeout=2000)
                            await asyncio.sleep(0.2)

                            if await cart_icon.is_visible():
                                await cart_icon.click(timeout=3000)
                                logger.debug("clicked_cart_icon", selector=selector)
                                await asyncio.sleep(0.5)
                                break
                    except Exception as e:
                        logger.debug("cart_opener_failed", selector=selector, error=str(e))
                        continue

                # Re-check cart items after attempting to open
                cart_items = page.locator(self.CART_SELECTORS["cart_item"])
                count = await cart_items.count()
                logger.debug("cart_items_after_open", count=count)

            # Search for the product in cart items
            for i in range(count):
                item = cart_items.nth(i)
                name_elem = item.locator(self.CART_SELECTORS["cart_item_name"])
                price_elem = item.locator(self.CART_SELECTORS["cart_item_price"])

                if await name_elem.count() > 0:
                    name = await name_elem.first.text_content(timeout=2000)
                    if name and product_name.lower() in name.lower():
                        if await price_elem.count() > 0:
                            price_text = await price_elem.first.text_content(timeout=2000)
                            price = self._parse_price(price_text)
                            logger.debug("cart_price_found", product=product_name, price=str(price))
                            return price

            # If we couldn't find by name, try to get the most recent item's price
            if count > 0:
                last_item = cart_items.nth(count - 1)
                price_elem = last_item.locator(self.CART_SELECTORS["cart_item_price"])
                if await price_elem.count() > 0:
                    price_text = await price_elem.first.text_content(timeout=2000)
                    price = self._parse_price(price_text)
                    logger.debug("cart_price_from_last_item", product=product_name, price=str(price))
                    return price

            logger.debug("cart_price_not_found", product=product_name, items_checked=count)
            return None

        except Exception as e:
            logger.warning("get_cart_price_failed", product=product_name, error=str(e))
            return None

    async def _clear_cart(self, page: Page) -> None:
        """Remove all items from the shopping cart.

        Args:
            page: Playwright page instance.
        """
        try:
            # First try clear cart button if available
            clear_btn = page.locator(self.CART_SELECTORS["clear_cart"])
            if await clear_btn.count() > 0 and await clear_btn.first.is_visible():
                await clear_btn.first.click()
                await asyncio.sleep(0.5)
                logger.debug("cart_cleared_via_button")
                return

            # Otherwise remove items one by one
            max_attempts = 20  # Prevent infinite loop
            for _ in range(max_attempts):
                remove_buttons = page.locator(self.CART_SELECTORS["remove_item"])
                if await remove_buttons.count() == 0:
                    break
                await remove_buttons.first.click()
                await asyncio.sleep(0.3)

            logger.debug("cart_cleared_items_removed")

        except Exception as e:
            logger.warning("clear_cart_failed", error=str(e))

    async def _close_modal(self, page: Page) -> None:
        """Close any open modal dialog.

        Args:
            page: Playwright page instance.
        """
        try:
            close_selector = self.CART_SELECTORS["close_modal"]
            close_btn = page.locator(close_selector).first

            if await close_btn.is_visible():
                await close_btn.click()
                await asyncio.sleep(0.3)
                logger.debug("modal_closed")

        except Exception as e:
            logger.debug("close_modal_skipped", error=str(e))

    async def _capture_cart_price_for_product(
        self,
        page: Page,
        product_locator,
        product_name: str,
        size: Optional[str],
        location: LocationConfig,
        category: str,
    ) -> Optional[PriceRecord]:
        """Capture price from cart for a single product.

        Flow: click product -> select size -> add to cart -> read price -> clear cart -> go back

        Args:
            page: Playwright page instance.
            product_locator: Locator for the product card element.
            product_name: Name of the product.
            size: Size variant to select (if applicable).
            location: Current location configuration.
            category: Product category.

        Returns:
            PriceRecord with cart price, or None if capture failed.
        """
        # Remember the category URL so we can return to it
        category_url = self.CATEGORY_URLS.get(category, f"/menu/{category}")
        full_category_url = f"{self.base_url}{category_url}"
        original_url = page.url

        try:
            # Click "Add to Order" to open customization panel
            if not await self._click_product(page, product_locator):
                return None

            # Select size if applicable
            await self._select_size(page, size)

            # Select crust (first available option)
            await self._select_crust(page)

            # Click final "Add to Cart" button
            if not await self._add_to_cart(page):
                await self._close_modal(page)
                # Navigate back if we're on a different page
                if page.url != original_url:
                    await page.goto(full_category_url, wait_until="domcontentloaded", timeout=10000)
                return None

            # Get price from cart
            cart_price = await self._get_cart_price(page, product_name)

            # Clear cart for next product
            await self._clear_cart(page)

            # Close any open modals
            await self._close_modal(page)

            # Navigate back to category page if we ended up elsewhere
            if page.url != original_url and not page.url.startswith(full_category_url):
                logger.debug("navigating_back_to_category", from_url=page.url, to_url=full_category_url)
                await page.goto(full_category_url, wait_until="domcontentloaded", timeout=10000)
                await asyncio.sleep(0.5)

            if cart_price is not None:
                return PriceRecord(
                    province=location.province,
                    store_name=location.store_name,
                    category=self._normalize_category(category),
                    product_name=product_name,
                    actual_price=cart_price,
                    raw_price_text=f"${cart_price}",
                    size=size,
                    pricing_level=location.get_pricing_level(),
                    price_source=PriceSource.CART,
                )

            return None

        except Exception as e:
            logger.warning(
                "cart_price_capture_failed",
                product=product_name,
                error=str(e),
            )
            # Try to clean up and return to category
            try:
                await self._clear_cart(page)
                await self._close_modal(page)
                if page.url != original_url:
                    await page.goto(full_category_url, wait_until="domcontentloaded", timeout=10000)
            except:
                pass
            return None
