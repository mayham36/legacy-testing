---
status: complete
priority: p2
issue_id: "012"
tags:
  - code-review
  - performance
  - async
dependencies: []
---

# Use Async File I/O in FastAPI Handlers

## Problem Statement

The FastAPI application performs **blocking file I/O operations** inside async handlers. This blocks the event loop and reduces concurrency.

**Why it matters:** Blocking I/O in async code defeats the purpose of async - other requests must wait while files are being read/written.

## Findings

**Location:** `src/web/app.py`

**Blocking Operations Found:**
```python
# Line 53-54 - load_cities_from_config
with open(locations_path) as f:
    data = yaml.safe_load(f)

# Line 87-88 - load_pricing_levels
with open(pl_path) as f:
    data = yaml.safe_load(f)

# Line 99-100 - get_master_info
with open(MASTER_INFO_FILE) as f:
    return json.load(f)

# Line 107-108 - save_master_info
with open(MASTER_INFO_FILE, "w") as f:
    json.dump(info, f, indent=2)

# Line 127-129 - save_cities_to_config
with open(locations_path) as f:
    existing_data = yaml.safe_load(f)

# Line 143-144 - save_cities_to_config
with open(locations_path, "w") as f:
    yaml.dump(existing_data, f, ...)

# Lines 462-464 - upload_master
with open(file_path, "wb") as f:
    f.write(content)
```

## Proposed Solutions

### Option 1: Use aiofiles Library (Recommended)

**Description:** Replace synchronous file operations with async versions.

```python
import aiofiles

# Before
with open(path) as f:
    data = yaml.safe_load(f)

# After
async with aiofiles.open(path, 'r') as f:
    content = await f.read()
    data = yaml.safe_load(content)
```

| Aspect | Assessment |
|--------|------------|
| Pros | True async, doesn't block event loop |
| Cons | Adds dependency, requires refactoring |
| Effort | Medium (3-4 hours) |
| Risk | Low |

### Option 2: Use run_in_executor

**Description:** Run blocking I/O in thread pool.

```python
import asyncio
from functools import partial

async def load_config():
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,  # Default executor
        partial(yaml.safe_load, open(path).read())
    )
```

| Aspect | Assessment |
|--------|------------|
| Pros | No new dependencies |
| Cons | Still uses threads, more verbose |
| Effort | Medium (2-3 hours) |
| Risk | Low |

### Option 3: Cache Config in Memory

**Description:** Load config once at startup, serve from memory.

```python
# Global config cache
_config_cache = {}

@app.on_event("startup")
async def load_configs():
    _config_cache["cities"] = load_cities_from_config()
    _config_cache["pricing_levels"] = load_pricing_levels()

def get_cities():
    return _config_cache["cities"]
```

| Aspect | Assessment |
|--------|------------|
| Pros | Fastest, no I/O during requests |
| Cons | Must invalidate cache on updates |
| Effort | Medium (2-3 hours) |
| Risk | Medium - cache invalidation |

## Recommended Action

<!-- To be filled during triage -->

## Technical Details

**Affected Files:**
- `src/web/app.py` - Multiple functions

**Required Changes with aiofiles:**
```python
# Add to requirements
aiofiles>=23.0.0

# Add import
import aiofiles

# Convert each blocking open() to async
```

**Functions to Update:**
1. `load_cities_from_config()` → make async
2. `load_pricing_levels()` → make async
3. `get_master_info()` → make async
4. `save_master_info()` → make async
5. `save_cities_to_config()` → make async
6. `upload_master()` → already async, fix file write

## Acceptance Criteria

- [x] No blocking `open()` calls in async functions
- [x] All file I/O uses aiofiles or executor
- [ ] Application performance improved under load
- [ ] All tests pass

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-02-03 | Created from code review | Python reviewer identified blocking I/O |
| 2026-02-03 | Implemented Option 1 (aiofiles) | Converted all 6 functions to async with aiofiles. Added aiofiles>=23.0.0 to requirements.txt. Updated all callers to use await. |

## Resources

- aiofiles: https://github.com/Tinche/aiofiles
- FastAPI async: https://fastapi.tiangolo.com/async/
