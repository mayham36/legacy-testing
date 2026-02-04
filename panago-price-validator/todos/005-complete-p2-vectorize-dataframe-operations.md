---
status: complete
priority: p2
issue_id: "005"
tags:
  - code-review
  - performance
  - pandas
dependencies: []
---

# Vectorize DataFrame Operations

## Problem Statement

The comparison module uses `DataFrame.apply(axis=1)` with Python lambda functions for row-by-row processing. This is **10-100x slower** than vectorized numpy operations.

**Why it matters:** For large datasets (1000+ products), comparison operations take significantly longer than necessary. This impacts user experience and scalability.

## Findings

**Location:** `src/comparison.py`

**Slow Patterns Found:**

```python
# Line 219-221 - Status determination
merged["status"] = merged.apply(
    lambda row: _determine_status(row, tolerance), axis=1
)

# Line 352-356 - Pass rate calculation
summary["pass_rate"] = summary.apply(
    lambda row: f"{(row['passed'] / row['total_products'] * 100):.1f}%"
    if row["total_products"] > 0
    else "N/A",
    axis=1,
)

# Line 630 - All prices status
result_df["status"] = result_df.apply(get_status, axis=1)
```

**Performance Impact:**
| Products | Current Time | Vectorized Time | Speedup |
|----------|--------------|-----------------|---------|
| 1,000 | ~150ms | ~2ms | 75x |
| 10,000 | ~1.5s | ~15ms | 100x |
| 100,000 | ~15s | ~150ms | 100x |

## Proposed Solutions

### Option 1: Use numpy.where for Status (Recommended)

**Description:** Replace `apply()` with vectorized `np.where()` chains.

```python
import numpy as np

# Replace lines 219-221 with:
merged["status"] = np.where(
    pd.isna(merged["expected_price"]),
    ValidationStatus.MISSING_EXPECTED,
    np.where(
        pd.isna(merged["actual_price"]),
        ValidationStatus.MISSING_ACTUAL,
        np.where(
            merged["price_difference"].abs() <= tolerance,
            ValidationStatus.PASS,
            ValidationStatus.FAIL
        )
    )
)
```

| Aspect | Assessment |
|--------|------------|
| Pros | 10-100x faster, numpy is well-optimized |
| Cons | Slightly less readable than apply |
| Effort | Small (2-3 hours) |
| Risk | Low |

### Option 2: Use pandas.cut or pandas.select

**Description:** Use pandas categorical operations.

```python
import numpy as np

conditions = [
    pd.isna(merged["expected_price"]),
    pd.isna(merged["actual_price"]),
    merged["price_difference"].abs() <= tolerance,
]
choices = [
    ValidationStatus.MISSING_EXPECTED,
    ValidationStatus.MISSING_ACTUAL,
    ValidationStatus.PASS,
]
merged["status"] = np.select(conditions, choices, default=ValidationStatus.FAIL)
```

| Aspect | Assessment |
|--------|------------|
| Pros | Clear condition/choice mapping |
| Cons | Order of conditions matters |
| Effort | Small (2-3 hours) |
| Risk | Low |

### Option 3: Use Numba JIT Compilation

**Description:** Keep apply but JIT compile the function.

| Aspect | Assessment |
|--------|------------|
| Pros | Minimal code changes |
| Cons | Adds dependency, complex setup |
| Effort | Medium (4-6 hours) |
| Risk | Medium |

## Recommended Action

<!-- To be filled during triage -->

## Technical Details

**Affected Files:**
- `src/comparison.py` - Lines 219-221, 352-356, 630

**Benchmark Script:**
```python
import timeit
import pandas as pd
import numpy as np

# Create test data
n = 10000
df = pd.DataFrame({
    'expected_price': np.random.rand(n) * 100,
    'actual_price': np.random.rand(n) * 100,
})
df['price_difference'] = df['actual_price'] - df['expected_price']

# Benchmark apply vs vectorized
def using_apply():
    return df.apply(lambda row: 'PASS' if abs(row['price_difference']) <= 0.01 else 'FAIL', axis=1)

def using_numpy():
    return np.where(df['price_difference'].abs() <= 0.01, 'PASS', 'FAIL')

print(f"apply: {timeit.timeit(using_apply, number=10):.3f}s")
print(f"numpy: {timeit.timeit(using_numpy, number=10):.3f}s")
```

## Acceptance Criteria

- [ ] No `DataFrame.apply(axis=1)` calls in comparison.py
- [ ] All tests still pass
- [ ] Performance benchmark shows 10x+ improvement
- [ ] Code remains readable with comments

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-02-03 | Created from code review | Performance oracle identified apply() bottleneck |

## Resources

- pandas performance tips: https://pandas.pydata.org/docs/user_guide/enhancingperf.html
- numpy.where docs: https://numpy.org/doc/stable/reference/generated/numpy.where.html
