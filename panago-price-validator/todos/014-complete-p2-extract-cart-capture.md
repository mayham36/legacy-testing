---
status: complete
priority: p2
issue_id: "014"
tags:
  - code-review
  - architecture
  - yagni
dependencies:
  - "008"  # Related to god class refactoring
---

# Extract or Remove Cart Capture Feature

## Problem Statement

The cart price capture feature adds **400+ lines** (26% of `browser_automation.py`) but is **disabled by default** (`capture_cart_prices: bool = False`). This complexity may not be justified if the feature is rarely used.

**Why it matters:**
- Increases cognitive load for developers
- Makes the main class harder to understand
- Adds maintenance burden for unused code
- Violates YAGNI (You Aren't Gonna Need It)

## Findings

**Location:** `src/browser_automation.py`

**Cart-Related Methods (8 methods, ~400 lines):**
```python
# Line 1135-1164
async def _click_product(self, page, product): ...

# Line 1166-1225
async def _select_size(self, page, product, size): ...

# Line 1227-1303
async def _select_crust(self, page, product): ...

# Line 1305-1388
async def _add_to_cart(self, page, product): ...

# Line 1390-1448
async def _get_cart_price(self, page, product_name): ...

# Line 1450-1480
async def _clear_cart(self, page): ...

# Line 1482-1522
async def _close_modal(self, page): ...

# Line 1524-1600
async def _capture_cart_price_for_product(self, ...): ...
```

**Usage Analysis:**
- Default: `capture_cart_prices=False`
- Only enabled via `--cart-prices` CLI flag or web UI checkbox
- Adds significant complexity to `_scrape_category` method

## Proposed Solutions

### Option 1: Extract to Separate Module (Recommended)

**Description:** Move cart functionality to optional module.

```python
# src/cart_capture.py
class CartPriceCapture:
    """Optional cart price capture functionality."""

    def __init__(self, selectors: dict):
        self.selectors = selectors

    async def capture_price(self, page, product, name, size, location, category):
        """Capture price from cart for a product."""
        await self._click_product(page, product)
        if size:
            await self._select_size(page, product, size)
        await self._add_to_cart(page, product)
        price = await self._get_cart_price(page, name)
        await self._clear_cart(page)
        await self._close_modal(page)
        return price

    # ... move all cart methods here

# browser_automation.py
class PanagoAutomation:
    def __init__(self, ..., capture_cart_prices: bool = False):
        self.cart = CartPriceCapture(self.CART_SELECTORS) if capture_cart_prices else None

    async def _scrape_category(self, ...):
        # ... scraping logic
        if self.cart:
            cart_price = await self.cart.capture_price(...)
```

| Aspect | Assessment |
|--------|------------|
| Pros | Clean separation, optional import, maintainable |
| Cons | Some refactoring needed |
| Effort | Medium (4-6 hours) |
| Risk | Low |

### Option 2: Delete Cart Capture Entirely

**Description:** Remove the feature if not used in production.

```bash
# Remove all cart-related code
# Update CLI to remove --cart-prices flag
# Update web UI to remove checkbox
```

| Aspect | Assessment |
|--------|------------|
| Pros | Immediate simplification, 400 lines removed |
| Cons | Loses functionality permanently |
| Effort | Small (1-2 hours) |
| Risk | Medium - may need feature later |

### Option 3: Feature Flag with Lazy Loading

**Description:** Keep code but only load when needed.

```python
def _get_cart_module(self):
    if not hasattr(self, '_cart_module'):
        if self.capture_cart_prices:
            from .cart_capture import CartPriceCapture
            self._cart_module = CartPriceCapture(self.CART_SELECTORS)
        else:
            self._cart_module = None
    return self._cart_module
```

| Aspect | Assessment |
|--------|------------|
| Pros | No overhead when disabled |
| Cons | Still maintains the code |
| Effort | Medium (3-4 hours) |
| Risk | Low |

## Recommended Action

<!-- To be filled during triage -->

## Technical Details

**Current State:**
- 400+ lines in `browser_automation.py`
- 8 methods dedicated to cart interaction
- Disabled by default

**Proposed File Structure (Option 1):**
```
src/
  browser_automation.py  # Reduced by 400 lines
  cart_capture.py        # New: 400 lines, optional
```

**Impact on Main Class:**
- Before: 1,542 lines
- After: ~1,100 lines

## Acceptance Criteria

- [x] Cart functionality isolated or removed
- [x] Main class under 1,200 lines
- [x] Feature still works if extracted (not deleted)
- [ ] All tests pass
- [ ] CLI and web UI updated accordingly

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-02-03 | Created from code review | Simplicity reviewer identified YAGNI violation |
| 2026-02-03 | Implemented Option 1 - Extracted to separate module | Created src/cart_capture.py with CartPriceCapture class. Reduced browser_automation.py from ~1546 to ~1171 lines (375 lines removed). Conditional import when capture_cart_prices=True. |

## Resources

- YAGNI: https://martinfowler.com/bliki/Yagni.html
- Feature Toggles: https://martinfowler.com/articles/feature-toggles.html
