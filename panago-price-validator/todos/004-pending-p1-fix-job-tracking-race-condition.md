---
status: pending
priority: p1
issue_id: "004"
tags:
  - code-review
  - concurrency
  - thread-safety
dependencies: []
---

# Fix Race Condition in Job Tracking

## Problem Statement

The web application uses a **global mutable dictionary** for job tracking that is accessed from both the main thread (FastAPI endpoints) and background tasks **without any synchronization**. This can lead to race conditions and data corruption.

**Why it matters:** In a production environment with concurrent users, job state could become corrupted, jobs could be lost, or the application could crash with dictionary mutation errors.

## Findings

**Location:** `src/web/app.py`, line 44

**Vulnerable Code:**
```python
# Global mutable state with no synchronization
jobs: dict[str, dict] = {}
```

**Concurrent Access Points:**

1. **Main thread (FastAPI endpoints):**
```python
# Line 179-187 - Writing to jobs
job_id = str(uuid.uuid4())[:8]
jobs[job_id] = {
    "status": "pending",
    "message": "Starting validation...",
    ...
}

# Line 366-370 - Reading from jobs
@app.get("/status/{job_id}")
async def get_status(job_id: str):
    if job_id not in jobs:
        return {"error": "Job not found", "status": "error"}
    return jobs[job_id]
```

2. **Background tasks:**
```python
# Lines 220-362 - Modifying job state
async def run_validation_task(job_id: str, ...):
    job = jobs[job_id]  # Read
    job["status"] = "running"  # Modify
    job["message"] = "Collecting prices..."  # Modify
    job["progress"] = 20  # Modify
    ...
```

**Race Condition Scenarios:**
1. User A checks status while User B's job is being updated
2. Multiple background tasks updating different jobs simultaneously
3. Dictionary resize during iteration causes `RuntimeError`
4. Job deleted while background task is still updating it

## Proposed Solutions

### Option 1: Use asyncio.Lock (Recommended for Current Scale)

**Description:** Add an asyncio lock to synchronize access to the jobs dictionary.

```python
import asyncio

jobs: dict[str, dict] = {}
jobs_lock = asyncio.Lock()

@app.post("/run")
async def run_validation(request: Request, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())[:8]

    async with jobs_lock:
        jobs[job_id] = {
            "status": "pending",
            "message": "Starting validation...",
            ...
        }

    background_tasks.add_task(run_validation_task, job_id, ...)
    return {"job_id": job_id}

@app.get("/status/{job_id}")
async def get_status(job_id: str):
    async with jobs_lock:
        if job_id not in jobs:
            return {"error": "Job not found"}
        return jobs[job_id].copy()  # Return copy to prevent mutation
```

| Aspect | Assessment |
|--------|------------|
| Pros | Simple, no external dependencies, asyncio-native |
| Cons | Lock contention under high load |
| Effort | Small (1-2 hours) |
| Risk | Low |

### Option 2: Use Thread-Safe Dictionary Wrapper

**Description:** Create a thread-safe wrapper class for job storage.

```python
from threading import RLock
from typing import Optional

class JobStore:
    def __init__(self):
        self._jobs: dict[str, dict] = {}
        self._lock = RLock()

    def create(self, job_id: str, initial_state: dict) -> None:
        with self._lock:
            self._jobs[job_id] = initial_state

    def get(self, job_id: str) -> Optional[dict]:
        with self._lock:
            job = self._jobs.get(job_id)
            return job.copy() if job else None

    def update(self, job_id: str, **updates) -> None:
        with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id].update(updates)

    def exists(self, job_id: str) -> bool:
        with self._lock:
            return job_id in self._jobs

jobs = JobStore()
```

| Aspect | Assessment |
|--------|------------|
| Pros | Encapsulated, reusable, explicit API |
| Cons | More code, needs careful API design |
| Effort | Medium (2-4 hours) |
| Risk | Low |

### Option 3: Use Redis for Job State

**Description:** Move job state to Redis for distributed, thread-safe storage.

```python
import redis
import json

redis_client = redis.Redis(host='localhost', port=6379, db=0)

def create_job(job_id: str, state: dict) -> None:
    redis_client.setex(f"job:{job_id}", 3600, json.dumps(state))

def get_job(job_id: str) -> Optional[dict]:
    data = redis_client.get(f"job:{job_id}")
    return json.loads(data) if data else None

def update_job(job_id: str, **updates) -> None:
    key = f"job:{job_id}"
    data = redis_client.get(key)
    if data:
        state = json.loads(data)
        state.update(updates)
        redis_client.setex(key, 3600, json.dumps(state))
```

| Aspect | Assessment |
|--------|------------|
| Pros | Scalable, persistent, handles restarts, automatic expiry |
| Cons | External dependency, more complexity |
| Effort | Medium (4-6 hours) |
| Risk | Medium (adds infrastructure) |

### Option 4: Use SQLite for Job Persistence

**Description:** Store jobs in SQLite database for thread-safe access and persistence.

| Aspect | Assessment |
|--------|------------|
| Pros | Thread-safe, persistent, no external services |
| Cons | Slightly slower than in-memory |
| Effort | Medium (3-4 hours) |
| Risk | Low |

## Recommended Action

<!-- To be filled during triage -->

## Technical Details

**Affected Files:**
- `src/web/app.py` - All job-related operations

**Current Issues:**
1. No synchronization on reads/writes
2. No job cleanup (memory leak over time)
3. Jobs lost on restart
4. No maximum job limit

**Additional Improvements to Consider:**
```python
# Add job cleanup
MAX_JOBS = 100
JOB_EXPIRY_HOURS = 24

async def cleanup_old_jobs():
    async with jobs_lock:
        now = datetime.now()
        expired = [
            jid for jid, job in jobs.items()
            if (now - job.get("created_at", now)).total_seconds() > JOB_EXPIRY_HOURS * 3600
        ]
        for jid in expired:
            del jobs[jid]
```

## Acceptance Criteria

- [ ] Job dictionary access is synchronized
- [ ] No race conditions under concurrent access
- [ ] Status endpoint returns consistent data
- [ ] Background task updates don't corrupt state
- [ ] Job cleanup implemented (optional but recommended)
- [ ] Load tested with concurrent requests

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-02-03 | Created from code review | Python reviewer identified thread-safety issue |

## Resources

- asyncio.Lock documentation: https://docs.python.org/3/library/asyncio-sync.html#asyncio.Lock
- FastAPI Background Tasks: https://fastapi.tiangolo.com/tutorial/background-tasks/
- Thread-safe Python patterns: https://superfastpython.com/thread-safe-dictionary-in-python/
