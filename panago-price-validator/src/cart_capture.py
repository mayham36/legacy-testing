"""Optional cart price capture functionality.

This module provides cart interaction methods for capturing prices from the shopping cart.
It is loaded conditionally only when capture_cart_prices=True is enabled.
"""
import asyncio
from decimal import Decimal
import re
from typing import Optional, Callable

import structlog
from playwright.async_api import Page

logger = structlog.get_logger()


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


class CartPriceCapture:
    """Optional cart price capture functionality.

    Provides methods to interact with the shopping cart to capture actual
    prices as they would appear during checkout.
    """

    def __init__(
        self,
        selectors: dict,
        parse_price_func: Callable[[Optional[str]], Decimal],
    ) -> None:
        """Initialize the cart price capture module.

        Args:
            selectors: Dict of CSS selectors for cart interaction.
            parse_price_func: Function to parse price strings to Decimal.
        """
        self.selectors = selectors
        self._parse_price = parse_price_func

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
            except Exception:
                element_text = "could not get text"
            logger.debug("processing_product", element_preview=element_text)

            # Scroll product into view first
            await product_locator.scroll_into_view_if_needed(timeout=2000)
            await asyncio.sleep(0.3)

            # Find "Add to Order" button within this product
            add_button = product_locator.locator(self.selectors["add_to_order_button"]).first

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
            modal_selector = self.selectors["product_modal"]
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
                    except Exception:
                        continue

            # Fallback: try generic size selector
            size_selector = self.selectors["size_option"]
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
            crust_selector = self.selectors["crust_option"]
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
                except Exception:
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
            cart_items = page.locator(self.selectors["cart_item"])
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
                cart_items = page.locator(self.selectors["cart_item"])
                count = await cart_items.count()
                logger.debug("cart_items_after_open", count=count)

            # Search for the product in cart items
            for i in range(count):
                item = cart_items.nth(i)
                name_elem = item.locator(self.selectors["cart_item_name"])
                price_elem = item.locator(self.selectors["cart_item_price"])

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
                price_elem = last_item.locator(self.selectors["cart_item_price"])
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
            clear_btn = page.locator(self.selectors["clear_cart"])
            if await clear_btn.count() > 0 and await clear_btn.first.is_visible():
                await clear_btn.first.click()
                await asyncio.sleep(0.5)
                logger.debug("cart_cleared_via_button")
                return

            # Otherwise remove items one by one
            max_attempts = 20  # Prevent infinite loop
            for _ in range(max_attempts):
                remove_buttons = page.locator(self.selectors["remove_item"])
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
            close_selector = self.selectors["close_modal"]
            close_btn = page.locator(close_selector).first

            if await close_btn.is_visible():
                await close_btn.click()
                await asyncio.sleep(0.3)
                logger.debug("modal_closed")

        except Exception as e:
            logger.debug("close_modal_skipped", error=str(e))

    async def capture_price(
        self,
        page: Page,
        product_locator,
        product_name: str,
        size: Optional[str],
        base_url: str,
        category_url: str,
    ) -> Optional[Decimal]:
        """Capture price from cart for a single product.

        Flow: click product -> select size -> add to cart -> read price -> clear cart -> go back

        Args:
            page: Playwright page instance.
            product_locator: Locator for the product card element.
            product_name: Name of the product.
            size: Size variant to select (if applicable).
            base_url: Base URL of the website.
            category_url: URL path for the category (e.g., "/menu/pizzas/meat").

        Returns:
            Cart price as Decimal, or None if capture failed.
        """
        # Remember the category URL so we can return to it
        full_category_url = f"{base_url}{category_url}"
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

            return cart_price

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
            except Exception:
                pass
            return None
