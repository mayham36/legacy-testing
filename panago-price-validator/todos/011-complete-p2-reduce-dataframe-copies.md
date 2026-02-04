---
status: complete
priority: p2
issue_id: "011"
tags:
  - code-review
  - performance
  - memory
dependencies: []
---

# Reduce DataFrame Memory Copies

## Problem Statement

The comparison module makes **5+ unnecessary `.copy()` calls** during a single comparison operation, causing excessive memory allocation.

**Why it matters:** For large datasets, this doubles or triples memory usage unnecessarily, potentially causing out-of-memory errors.

## Findings

**Location:** `src/comparison.py`

**Defensive Copies Found:**
```python
# Line 119 - _apply_name_normalization
df = df.copy()

# Line 162 - compare_prices
expected_df = expected_df.copy()

# Line 240 - discrepancies extraction
discrepancies_df = merged[merged["status"] != ValidationStatus.PASS].copy()

# Line 256-257 - output preparation
details_df = merged[available_columns].copy()
discrepancies_df = discrepancies_df[available_columns].copy()
```

**Memory Impact:**
| Products | Columns | Per Copy | 5 Copies |
|----------|---------|----------|----------|
| 10,000 | 10 | ~2MB | ~10MB |
| 100,000 | 10 | ~20MB | ~100MB |
| 1,000,000 | 10 | ~200MB | ~1GB |

## Proposed Solutions

### Option 1: Enable Copy-on-Write Mode (Recommended)

**Description:** Use pandas 2.0+ copy-on-write mode which makes copies lazy.

```python
# At top of comparison.py
import pandas as pd
pd.options.mode.copy_on_write = True

# Then remove explicit .copy() calls - they're now no-ops
```

| Aspect | Assessment |
|--------|------------|
| Pros | One-line fix, backwards compatible |
| Cons | Requires pandas 2.0+ |
| Effort | Small (15 minutes) |
| Risk | Very Low |

### Option 2: Remove Unnecessary Copies

**Description:** Analyze each copy and remove if not needed.

```python
# Line 119 - NEEDED: We modify the DataFrame
df = df.copy()

# Line 162 - MAYBE: Only if we modify expected_df
# If we don't modify it, remove .copy()

# Line 240, 256-257 - NOT NEEDED: Slicing already creates new DataFrame
# These can be removed
```

| Aspect | Assessment |
|--------|------------|
| Pros | No pandas version requirement |
| Cons | Must analyze each case carefully |
| Effort | Small (1-2 hours) |
| Risk | Low |

### Option 3: Use Views Where Possible

**Description:** Use `.loc` views instead of copies for read-only operations.

| Aspect | Assessment |
|--------|------------|
| Pros | Most memory efficient |
| Cons | Must be careful about SettingWithCopyWarning |
| Effort | Medium (2-3 hours) |
| Risk | Medium |

## Recommended Action

<!-- To be filled during triage -->

## Technical Details

**Affected Files:**
- `src/comparison.py` - Lines 119, 162, 240, 256-257

**Copy Analysis:**

| Line | Reason | Needed? |
|------|--------|---------|
| 119 | Modifies df to add normalized column | Yes |
| 162 | Renames columns | Maybe - check if modified |
| 240 | Slicing already copies | No |
| 256 | Slicing already copies | No |
| 257 | Already copied | No |

## Acceptance Criteria

- [ ] Memory usage reduced by 50%+ for large datasets
- [ ] No SettingWithCopyWarning in logs
- [ ] All tests pass
- [ ] Benchmark confirms improvement

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-02-03 | Created from code review | Performance oracle identified memory issue |

## Resources

- pandas Copy-on-Write: https://pandas.pydata.org/docs/user_guide/copy_on_write.html
- Memory optimization: https://pandas.pydata.org/docs/user_guide/scale.html
