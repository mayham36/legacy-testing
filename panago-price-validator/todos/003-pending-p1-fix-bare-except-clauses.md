---
status: pending
priority: p1
issue_id: "003"
tags:
  - code-review
  - code-quality
  - error-handling
dependencies: []
---

# Fix Bare except: Clauses

## Problem Statement

The codebase contains multiple bare `except:` clauses that catch **all exceptions including `KeyboardInterrupt` and `SystemExit`**. This is dangerous because:

1. It prevents graceful shutdown (Ctrl+C won't work)
2. It hides bugs by silently swallowing errors
3. It violates Python best practices (PEP 8)

**Why it matters:** Users cannot interrupt long-running scraping jobs, and errors are silently ignored making debugging extremely difficult.

## Findings

**Location:** `src/browser_automation.py`

**Instances Found:**

```python
# Line 1152-1153
except:
    element_text = "could not get text"

# Line 1228-1229
except:
    continue

# Line 1309-1310
except:
    continue

# Line 1539-1540
except:
    # Ignore close errors
    pass
```

**Also in `src/pages/menu_page.py`:**
```python
# Line 84-86
except Exception:
    # Modal might already be visible
    pass
```

**Impact:**
- `KeyboardInterrupt` (Ctrl+C) is caught and ignored
- `SystemExit` is caught, preventing clean process termination
- Memory errors, recursion errors are silently swallowed
- Debugging is nearly impossible when errors are hidden

## Proposed Solutions

### Option 1: Replace with `except Exception:` (Recommended)

**Description:** Change bare `except:` to `except Exception:` which catches all exceptions except `KeyboardInterrupt`, `SystemExit`, and `GeneratorExit`.

```python
# Before
except:
    element_text = "could not get text"

# After
except Exception:
    element_text = "could not get text"
```

| Aspect | Assessment |
|--------|------------|
| Pros | Minimal change, allows Ctrl+C, follows Python best practices |
| Cons | Still catches broad range of exceptions |
| Effort | Small (30 minutes) |
| Risk | Very Low |

### Option 2: Catch Specific Exceptions

**Description:** Identify and catch only the specific exceptions that can occur.

```python
# Before
try:
    element_text = await locator.text_content(timeout=3000)
except:
    element_text = "could not get text"

# After
from playwright.async_api import TimeoutError as PlaywrightTimeout

try:
    element_text = await locator.text_content(timeout=3000)
except (PlaywrightTimeout, AttributeError) as e:
    logger.debug("text_extraction_failed", error=str(e))
    element_text = "could not get text"
```

| Aspect | Assessment |
|--------|------------|
| Pros | Most precise, best for debugging |
| Cons | Requires identifying all possible exceptions |
| Effort | Medium (2-4 hours) |
| Risk | Low |

### Option 3: Add Logging to Exception Handlers

**Description:** Keep broad exception handling but add logging for visibility.

```python
# Before
except:
    continue

# After
except Exception as e:
    logger.warning("unexpected_error", error=str(e), exc_info=True)
    continue
```

| Aspect | Assessment |
|--------|------------|
| Pros | Provides visibility into hidden errors |
| Cons | Still catches too broadly |
| Effort | Small (1 hour) |
| Risk | Low |

## Recommended Action

<!-- To be filled during triage -->

## Technical Details

**Affected Files:**
- `src/browser_automation.py` - 4 instances
- `src/pages/menu_page.py` - 1 instance (already uses `except Exception`)

**Specific Changes:**

| File | Line | Current | Change To |
|------|------|---------|-----------|
| browser_automation.py | 1152 | `except:` | `except Exception:` |
| browser_automation.py | 1228 | `except:` | `except Exception:` |
| browser_automation.py | 1309 | `except:` | `except Exception:` |
| browser_automation.py | 1539 | `except:` | `except Exception:` |

**Quick Fix Command:**
```bash
# Find all bare except clauses
grep -n "except:" src/browser_automation.py | grep -v "except Exception" | grep -v "except.*:"
```

## Acceptance Criteria

- [ ] No bare `except:` clauses in codebase
- [ ] All exception handlers use `except Exception:` at minimum
- [ ] Ctrl+C (KeyboardInterrupt) stops the program cleanly
- [ ] Consider adding logging to exception handlers for debugging

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-02-03 | Created from code review | Python reviewer identified PEP 8 violation |

## Resources

- PEP 8 on bare except: https://peps.python.org/pep-0008/#programming-recommendations
- Python Exception Hierarchy: https://docs.python.org/3/library/exceptions.html#exception-hierarchy
