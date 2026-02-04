---
status: partial
priority: p3
issue_id: "008"
tags:
  - code-review
  - architecture
  - refactoring
dependencies: []
---

# Refactor PanagoAutomation God Class

## Problem Statement

The `PanagoAutomation` class in `browser_automation.py` is **1,542 lines** with **28 methods** handling too many responsibilities:
- Browser lifecycle management
- Location selection
- Category navigation
- Product scraping (multiple methods for different product types)
- Cart interaction
- Debug snapshot handling
- Rate limiting

**Why it matters:** Large classes are difficult to test, maintain, and extend. Changes in one area risk breaking others.

## Findings

**Location:** `src/browser_automation.py`

**Class Responsibilities:**
1. **Browser Management** (5 methods): Context creation, resource blocking
2. **Location Selection** (4 methods): City picker interaction, validation
3. **Category Scraping** (6 methods): Navigation, product extraction
4. **Beverage Handling** (2 methods): Special beverage extraction
5. **Cart Interaction** (8 methods): Add to cart, price capture, cleanup
6. **Utilities** (3 methods): Parsing, progress reporting, debug snapshots

**Size Breakdown:**
| Responsibility | Lines | % of Class |
|----------------|-------|------------|
| Cart Interaction | ~400 | 26% |
| Category Scraping | ~350 | 23% |
| Location Selection | ~125 | 8% |
| Beverage Handling | ~120 | 8% |
| Browser Management | ~100 | 6% |
| Other | ~450 | 29% |

## Proposed Solutions

### Option 1: Extract Strategy Classes (Recommended)

**Description:** Extract each responsibility into focused classes.

```
src/
  automation/
    __init__.py
    browser_manager.py      # Browser lifecycle
    location_selector.py    # City selection
    category_scraper.py     # Base scraping logic
    beverage_scraper.py     # Beverage-specific
    cart_interactor.py      # Cart price capture
    debug_snapshots.py      # Debug utilities
  browser_automation.py     # Facade that coordinates
```

```python
# browser_automation.py becomes a thin facade
class PanagoAutomation:
    def __init__(self, config, ...):
        self.browser = BrowserManager(config)
        self.location = LocationSelector()
        self.scraper = CategoryScraper()
        self.cart = CartInteractor() if capture_cart else None

    async def run_price_collection(self):
        async with self.browser.context() as context:
            page = await context.new_page()
            await self.location.select(page, city)
            for category in self.CATEGORIES:
                prices = await self.scraper.scrape(page, category)
                yield from prices
```

| Aspect | Assessment |
|--------|------------|
| Pros | Clean separation, testable, extensible |
| Cons | Significant refactoring effort |
| Effort | Large (2-3 days) |
| Risk | Medium - many files touched |

### Option 2: Extract Cart Interaction Only

**Description:** Move just the cart code (largest chunk) to separate module.

```python
# cart_interactor.py
class CartInteractor:
    async def click_product(self, page, product): ...
    async def select_size(self, page, size): ...
    async def add_to_cart(self, page): ...
    async def get_cart_price(self, page, name): ...
    async def clear_cart(self, page): ...
    async def capture_price(self, page, product, location, category): ...
```

| Aspect | Assessment |
|--------|------------|
| Pros | Quick win, removes 400 lines |
| Cons | Doesn't address other issues |
| Effort | Medium (4-6 hours) |
| Risk | Low |

### Option 3: Delete Cart Interaction

**Description:** Remove cart capture entirely (it's disabled by default).

| Aspect | Assessment |
|--------|------------|
| Pros | Simplest, removes 400 lines immediately |
| Cons | Loses functionality that may be needed |
| Effort | Small (1-2 hours) |
| Risk | Medium - may need later |

## Recommended Action

<!-- To be filled during triage -->

## Technical Details

**Current File:**
- `src/browser_automation.py` - 1,542 lines

**Proposed Structure (Option 1):**
```
src/automation/
  __init__.py           # Exports PanagoAutomation
  browser_manager.py    # ~100 lines
  location_selector.py  # ~125 lines
  category_scraper.py   # ~350 lines
  beverage_scraper.py   # ~120 lines (extends CategoryScraper)
  cart_interactor.py    # ~400 lines
  debug.py              # ~50 lines
  selectors.py          # ~100 lines (shared selectors)
```

## Acceptance Criteria

- [ ] No single file over 500 lines
- [ ] Each class has single responsibility
- [ ] All existing tests pass
- [ ] Functionality unchanged
- [ ] Cart capture remains optional

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-02-03 | Created from code review | Simplicity reviewer identified god class |
| 2026-02-03 | Partial: Cart extraction completed via #014 | Reduced from 1,542 to 1,170 lines (24% reduction). Cart capture now in separate module. Full Option 1 refactor deferred to P3 - remaining class is maintainable at current size. |

## Resources

- Single Responsibility Principle: https://en.wikipedia.org/wiki/Single-responsibility_principle
- Refactoring to Patterns: https://martinfowler.com/books/r2p.html
