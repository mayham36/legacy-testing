---
status: complete
priority: p2
issue_id: "006"
tags:
  - code-review
  - security
  - cors
dependencies: []
---

# Add CORS Configuration

## Problem Statement

The FastAPI application has **no CORS (Cross-Origin Resource Sharing) configuration**. This means:
- No origin restrictions are in place
- CSRF attacks are possible since endpoints accept form data without tokens
- If deployed, the API may be accessible from any origin

**Why it matters:** Without CORS configuration, malicious websites could make requests to the API on behalf of authenticated users.

## Findings

**Location:** `src/web/app.py`

**Missing Configuration:**
- No `CORSMiddleware` imported or configured
- No origin whitelist defined
- Form endpoints vulnerable to cross-origin requests

## Proposed Solutions

### Option 1: Restrictive CORS (Recommended for Production)

**Description:** Only allow requests from known origins.

```python
from fastapi.middleware.cors import CORSMiddleware

# Add after app = FastAPI(...)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        # Add production domain when deployed
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)
```

| Aspect | Assessment |
|--------|------------|
| Pros | Secure, blocks unauthorized origins |
| Cons | Must update list when deploying |
| Effort | Small (30 minutes) |
| Risk | Low |

### Option 2: Environment-Based CORS

**Description:** Configure allowed origins via environment variable.

```python
import os
from fastapi.middleware.cors import CORSMiddleware

allowed_origins = os.getenv("CORS_ORIGINS", "http://localhost:8000").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)
```

| Aspect | Assessment |
|--------|------------|
| Pros | Flexible, no code changes for deployment |
| Cons | Must set env var correctly |
| Effort | Small (30 minutes) |
| Risk | Low |

### Option 3: Allow All Origins (Development Only)

**Description:** Allow all origins - NOT for production.

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,  # Must be False with "*"
    allow_methods=["*"],
    allow_headers=["*"],
)
```

| Aspect | Assessment |
|--------|------------|
| Pros | Simplest, good for local dev |
| Cons | NOT SECURE for production |
| Effort | Small (15 minutes) |
| Risk | High if used in production |

## Recommended Action

<!-- To be filled during triage -->

## Technical Details

**Affected Files:**
- `src/web/app.py` - Add middleware after app creation

**Add Import:**
```python
from fastapi.middleware.cors import CORSMiddleware
```

## Acceptance Criteria

- [ ] CORSMiddleware configured in app.py
- [ ] Allowed origins configurable via environment
- [ ] Localhost origins allowed for development
- [ ] Documentation updated with CORS_ORIGINS env var

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-02-03 | Created from code review | Security sentinel identified missing CORS |

## Resources

- FastAPI CORS docs: https://fastapi.tiangolo.com/tutorial/cors/
- CORS explained: https://developer.mozilla.org/en-US/docs/Web/HTTP/CORS
