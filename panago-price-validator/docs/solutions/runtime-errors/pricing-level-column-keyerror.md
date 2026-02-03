# KeyError: 'province' in DataFrame Merge Operations

---
title: KeyError 'province' when merging dataframes with pricing_level column
category: runtime-errors
module: comparison
tags:
  - data-merge
  - column-mismatch
  - pricing-levels
  - dataframe-operations
  - pandas
symptoms:
  - KeyError: 'province' raised during pd.merge() operation
  - Validation fails with "validation failed message 'province'" error
  - Error occurs after implementing pricing levels feature
severity: medium
date_resolved: 2026-02-03
---

## Problem

After migrating from province-based pricing to pricing levels (PL1, PL2, PL2-B, PL3, PL4), the validation would fail with:

```
KeyError: 'province'
```

The error occurred in `comparison.py` when attempting to merge DataFrames that no longer contained the `province` column as the primary location identifier.

## Root Cause

When the pricing levels feature was implemented:

1. The **master document parser** (`master_parser.py`) creates expected prices with a `pricing_level` column
2. The **browser automation** creates actual prices with a `pricing_level` column
3. But the **comparison functions** had hardcoded references to `province` in:
   - Merge keys: `merge_keys = ["product_name", "category", "province"]`
   - Output columns: `output_columns = ["province", "store_name", ...]`

This caused pandas merge operations to fail when `province` didn't exist in one or both DataFrames.

## Solution

Updated all comparison functions to dynamically detect which location identifier column exists and use it accordingly.

### Key Pattern: Dynamic Merge Key Selection

**Before (hardcoded):**
```python
merge_keys = ["product_name", "province", "store_name", "category"]
```

**After (dynamic):**
```python
merge_keys = ["product_name", "store_name", "category"]
if "pricing_level" in menu_df.columns and "pricing_level" in cart_df.columns:
    merge_keys.append("pricing_level")
if "province" in menu_df.columns and "province" in cart_df.columns:
    merge_keys.append("province")
```

### Key Pattern: Inclusive Output Columns

**Before:**
```python
output_columns = [
    "province",
    "store_name",
    ...
]
```

**After:**
```python
output_columns = [
    "pricing_level",  # Added - will be filtered if not present
    "province",
    "store_name",
    ...
]
available_columns = [c for c in output_columns if c in result_df.columns]
result_df = result_df[available_columns]
```

## Files Modified

| File | Function | Change |
|------|----------|--------|
| `src/comparison.py` | `compare_prices()` | Dynamic merge_keys, output_columns |
| `src/comparison.py` | `compare_menu_vs_cart()` | Dynamic merge_keys, output_columns |
| `src/comparison.py` | `compare_all_prices()` | Dynamic merge_keys, output_columns |
| `src/comparison.py` | `_create_empty_results()` | Added pricing_level to columns |
| `src/comparison.py` | `_create_empty_menu_vs_cart_results()` | Added pricing_level to columns |
| `src/comparison.py` | `_create_empty_all_prices_results()` | Added pricing_level to columns |

## Prevention Strategies

### 1. Code Review Checklist

When refactoring column names:
- [ ] Search entire codebase for hardcoded column name strings
- [ ] Check all merge operations use dynamic key detection
- [ ] Verify output columns are filtered with `available_columns` pattern
- [ ] Test with both old and new data formats

### 2. Testing Approach

```python
def test_compare_prices_with_pricing_level():
    """Ensure comparison works with pricing_level column."""
    expected_df = pd.DataFrame({
        "product_name": ["Pizza"],
        "pricing_level": ["PL1"],
        "expected_price": [15.99],
    })
    actual_prices = [PriceRecord(..., pricing_level=PricingLevel.PL1)]

    result = compare_prices(expected_df, actual_prices)
    assert "pricing_level" in result["details_df"].columns

def test_compare_prices_with_province_fallback():
    """Ensure comparison still works with legacy province column."""
    expected_df = pd.DataFrame({
        "product_name": ["Pizza"],
        "province": ["BC"],
        "expected_price": [15.99],
    })
    actual_prices = [PriceRecord(..., province="BC")]

    result = compare_prices(expected_df, actual_prices)
    assert "province" in result["details_df"].columns
```

### 3. Best Practice: Column Abstraction

Consider centralizing column names:

```python
class Columns:
    PRODUCT_NAME = "product_name"
    PRICING_LEVEL = "pricing_level"
    PROVINCE = "province"

    @classmethod
    def get_location_column(cls, df: pd.DataFrame) -> str:
        if cls.PRICING_LEVEL in df.columns:
            return cls.PRICING_LEVEL
        return cls.PROVINCE
```

## Related

- Master document parser: `src/master_parser.py`
- Pricing level model: `src/models.py` (`PricingLevel` enum)
- Config: `config/pricing_levels.yaml`
