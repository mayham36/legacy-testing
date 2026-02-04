---
status: complete
priority: p2
issue_id: "007"
tags:
  - code-review
  - security
  - rate-limiting
dependencies:
  - "004"  # Depends on job tracking fix
---

# Add Rate Limiting and Job Cleanup

## Problem Statement

The application has **no rate limiting** on job creation and **no cleanup** of old jobs:
1. Unlimited jobs can be created, exhausting memory
2. Each job spawns browser automation (resource-intensive)
3. Jobs are stored in-memory forever with no expiration
4. No concurrent job limits per client

**Why it matters:** A single user (or attacker) could exhaust server resources by creating unlimited validation jobs.

## Findings

**Location:** `src/web/app.py`

**Issues:**
```python
# Line 44 - Jobs stored in memory forever
jobs: dict[str, dict] = {}

# Line 179-187 - No limit on job creation
@app.post("/run")
async def run_validation(...):
    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {...}  # No limit check
    background_tasks.add_task(...)  # No concurrency limit
```

**Resource Impact:**
- Each job consumes ~50-100MB (browser context)
- 100 concurrent jobs = 5-10GB memory
- No cleanup = unbounded growth

## Proposed Solutions

### Option 1: Simple In-Memory Limits (Recommended)

**Description:** Add job limits and automatic cleanup.

```python
from datetime import datetime, timedelta
import asyncio

MAX_JOBS = 50
MAX_CONCURRENT_JOBS = 5
JOB_EXPIRY_HOURS = 24

async def cleanup_old_jobs():
    """Remove jobs older than JOB_EXPIRY_HOURS."""
    async with jobs_lock:
        now = datetime.now()
        expired = [
            jid for jid, job in jobs.items()
            if (now - datetime.fromisoformat(job.get("created_at", now.isoformat()))).total_seconds() > JOB_EXPIRY_HOURS * 3600
        ]
        for jid in expired:
            del jobs[jid]
        return len(expired)

@app.post("/run")
async def run_validation(...):
    async with jobs_lock:
        # Check job limits
        active_jobs = sum(1 for j in jobs.values() if j["status"] in ("pending", "running"))
        if active_jobs >= MAX_CONCURRENT_JOBS:
            raise HTTPException(429, "Too many active jobs. Please wait.")
        if len(jobs) >= MAX_JOBS:
            # Cleanup old jobs first
            await cleanup_old_jobs()
            if len(jobs) >= MAX_JOBS:
                raise HTTPException(429, "Job limit reached. Try again later.")

        # Create job...
        jobs[job_id] = {
            "created_at": datetime.now().isoformat(),
            ...
        }
```

| Aspect | Assessment |
|--------|------------|
| Pros | Simple, no dependencies, immediate effect |
| Cons | Per-instance only, not distributed |
| Effort | Small (2-3 hours) |
| Risk | Low |

### Option 2: Use slowapi Rate Limiter

**Description:** Add proper rate limiting middleware.

```python
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

@app.post("/run")
@limiter.limit("5/minute")
async def run_validation(...):
    ...
```

| Aspect | Assessment |
|--------|------------|
| Pros | Industry standard, configurable |
| Cons | Adds dependency |
| Effort | Small (1-2 hours) |
| Risk | Low |

### Option 3: Redis-Based Rate Limiting

**Description:** Use Redis for distributed rate limiting.

| Aspect | Assessment |
|--------|------------|
| Pros | Works across instances, persistent |
| Cons | Requires Redis infrastructure |
| Effort | Medium (4-6 hours) |
| Risk | Medium |

## Recommended Action

<!-- To be filled during triage -->

## Technical Details

**Affected Files:**
- `src/web/app.py` - Add limits and cleanup

**Constants to Add:**
```python
MAX_JOBS = int(os.getenv("MAX_JOBS", "50"))
MAX_CONCURRENT_JOBS = int(os.getenv("MAX_CONCURRENT_JOBS", "5"))
JOB_EXPIRY_HOURS = int(os.getenv("JOB_EXPIRY_HOURS", "24"))
```

## Acceptance Criteria

- [ ] Maximum concurrent jobs enforced
- [ ] Old jobs cleaned up automatically
- [ ] HTTP 429 returned when limits exceeded
- [ ] Limits configurable via environment variables
- [ ] Memory usage bounded

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-02-03 | Created from code review | Security sentinel identified DoS risk |

## Resources

- slowapi: https://github.com/laurentS/slowapi
- FastAPI rate limiting: https://fastapi.tiangolo.com/tutorial/middleware/
