---
status: complete
priority: p2
issue_id: "013"
tags:
  - code-review
  - operations
  - disk-usage
dependencies: []
---

# Add Debug Snapshot Cleanup

## Problem Statement

The debug snapshot system saves screenshots, HTML, and JSON files on every scraping failure, but **never cleans them up**. Over time, this will fill disk space.

**Why it matters:** Long-running or frequently-failing scraping sessions can generate gigabytes of debug files.

## Findings

**Location:** `src/browser_automation.py`, lines 181-234

**Current Behavior:**
```python
async def _save_debug_snapshot(self, page, context, location):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    debug_dir = Path("debug") / timestamp
    debug_dir.mkdir(parents=True, exist_ok=True)

    # Screenshot (~500KB-2MB each)
    await page.screenshot(path=str(screenshot_path), full_page=True)

    # HTML (~100KB-1MB each)
    html_path.write_text(html, encoding="utf-8")

    # State JSON (~1KB each)
    state_path.write_text(json.dumps(state, indent=2))

    # NO CLEANUP MECHANISM
```

**Disk Usage:**
- Per snapshot: ~1-3MB
- 100 failures: ~100-300MB
- 1000 failures: ~1-3GB

## Proposed Solutions

### Option 1: Add Retention Policy (Recommended)

**Description:** Automatically delete debug files older than N hours.

```python
import shutil
from datetime import datetime, timedelta

MAX_DEBUG_AGE_HOURS = 24
MAX_DEBUG_SIZE_MB = 500

async def _cleanup_old_debug_snapshots(self):
    """Remove debug snapshots older than MAX_DEBUG_AGE_HOURS."""
    debug_root = Path("debug")
    if not debug_root.exists():
        return

    cutoff = datetime.now() - timedelta(hours=MAX_DEBUG_AGE_HOURS)

    for snapshot_dir in debug_root.iterdir():
        if not snapshot_dir.is_dir():
            continue
        try:
            # Parse timestamp from directory name (YYYYMMDD_HHMMSS)
            dir_time = datetime.strptime(snapshot_dir.name, "%Y%m%d_%H%M%S")
            if dir_time < cutoff:
                shutil.rmtree(snapshot_dir)
                logger.debug("cleaned_debug_snapshot", path=str(snapshot_dir))
        except (ValueError, OSError):
            continue

async def _save_debug_snapshot(self, page, context, location):
    # Clean up old snapshots first
    await self._cleanup_old_debug_snapshots()

    # ... existing save logic
```

| Aspect | Assessment |
|--------|------------|
| Pros | Automatic, configurable retention |
| Cons | Adds I/O overhead per snapshot |
| Effort | Small (1-2 hours) |
| Risk | Low |

### Option 2: Make Debug Mode Optional

**Description:** Only save snapshots when explicitly enabled.

```python
def __init__(self, ..., debug_mode: bool = False):
    self.debug_mode = debug_mode

async def _save_debug_snapshot(self, ...):
    if not self.debug_mode:
        return  # Skip entirely
    # ... save logic
```

| Aspect | Assessment |
|--------|------------|
| Pros | No disk usage by default |
| Cons | May lose useful debug info |
| Effort | Small (30 minutes) |
| Risk | Low |

### Option 3: Use Rotating Log-Style Storage

**Description:** Keep only last N snapshots.

```python
MAX_SNAPSHOTS = 50

async def _save_debug_snapshot(self, ...):
    debug_root = Path("debug")

    # Get all existing snapshots, sorted by time
    snapshots = sorted(debug_root.iterdir(), key=lambda p: p.stat().st_mtime)

    # Remove oldest if over limit
    while len(snapshots) >= MAX_SNAPSHOTS:
        oldest = snapshots.pop(0)
        shutil.rmtree(oldest)

    # ... save new snapshot
```

| Aspect | Assessment |
|--------|------------|
| Pros | Bounded disk usage |
| Cons | May lose relevant old snapshots |
| Effort | Small (1 hour) |
| Risk | Low |

## Recommended Action

<!-- To be filled during triage -->

## Technical Details

**Affected Files:**
- `src/browser_automation.py` - `_save_debug_snapshot` method

**Configuration Options:**
```python
# Environment variables
DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() == "true"
DEBUG_RETENTION_HOURS = int(os.getenv("DEBUG_RETENTION_HOURS", "24"))
DEBUG_MAX_SIZE_MB = int(os.getenv("DEBUG_MAX_SIZE_MB", "500"))
```

## Acceptance Criteria

- [ ] Debug snapshots automatically cleaned up
- [ ] Disk usage bounded to reasonable limit
- [ ] Configurable via environment variables
- [ ] No impact on scraping performance

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-02-03 | Created from code review | Operations concern identified |

## Resources

- Python shutil: https://docs.python.org/3/library/shutil.html
- Log rotation patterns: https://en.wikipedia.org/wiki/Log_rotation
