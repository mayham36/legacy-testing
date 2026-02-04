---
status: complete
priority: p2
issue_id: "009"
tags:
  - code-review
  - code-quality
  - dry
dependencies: []
---

# Remove Duplicate Selectors

## Problem Statement

The same CSS selectors are defined in **two different locations**:
1. `src/browser_automation.py` (lines 75-143)
2. `src/pages/menu_page.py` (lines 23-44)

**Why it matters:** Duplicate code leads to inconsistencies when one is updated but not the other. It also causes confusion about which is the "source of truth."

## Findings

**Location 1:** `src/browser_automation.py`
```python
SELECTORS = {
    "location_trigger": ".react-state-link-choose-location",
    "city_input": ".react-autosuggest__input",
    "autocomplete_suggestion": ".react-autosuggest__suggestion",
    ...
}
```

**Location 2:** `src/pages/menu_page.py`
```python
SELECTORS = {
    "location_trigger": ".react-state-link-choose-location",
    "city_input": ".react-autosuggest__input",
    ...
}
```

**Note:** The page object files (`pages/base_page.py`, `pages/menu_page.py`) are **not used anywhere** - they're dead code. See todo #010.

## Proposed Solutions

### Option 1: Delete Page Objects (Recommended)

**Description:** Since `pages/` is dead code, delete it entirely and keep selectors in `browser_automation.py`.

```bash
rm -rf src/pages/
```

| Aspect | Assessment |
|--------|------------|
| Pros | Eliminates duplication by removing dead code |
| Cons | None - code is unused |
| Effort | Small (15 minutes) |
| Risk | Very Low |

### Option 2: Create Shared Selectors Module

**Description:** Extract selectors to dedicated module, import everywhere.

```python
# src/selectors.py
LOCATION_SELECTORS = {
    "trigger": ".react-state-link-choose-location",
    "city_input": ".react-autosuggest__input",
    ...
}

PRODUCT_SELECTORS = {
    "card": "ul.products > li, .product-group",
    "name": ".product-title h4",
    ...
}

CART_SELECTORS = {...}
```

| Aspect | Assessment |
|--------|------------|
| Pros | Single source of truth, organized by purpose |
| Cons | More files, import overhead |
| Effort | Small (1-2 hours) |
| Risk | Low |

### Option 3: Move Selectors to Config File

**Description:** Store selectors in YAML config for easy updates.

```yaml
# config/selectors.yaml
location:
  trigger: ".react-state-link-choose-location"
  city_input: ".react-autosuggest__input"

products:
  card: "ul.products > li, .product-group"
  name: ".product-title h4"
```

| Aspect | Assessment |
|--------|------------|
| Pros | Non-developers can update selectors |
| Cons | Loses IDE autocompletion, type safety |
| Effort | Medium (2-3 hours) |
| Risk | Low |

## Recommended Action

<!-- To be filled during triage -->

## Technical Details

**Files to Modify:**
- Delete: `src/pages/base_page.py` (103 lines)
- Delete: `src/pages/menu_page.py` (204 lines)
- Keep: `src/browser_automation.py` selectors

**Total Lines Removed:** 307

## Acceptance Criteria

- [ ] Only one location defines each selector
- [ ] No duplicate selector definitions
- [ ] All tests pass
- [ ] No import errors

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-02-03 | Created from code review | Pattern recognition found duplicate definitions |

## Resources

- DRY Principle: https://en.wikipedia.org/wiki/Don%27t_repeat_yourself
