---
status: pending
priority: p1
issue_id: "001"
tags:
  - code-review
  - security
  - authentication
dependencies: []
---

# Add Authentication to Web Application

## Problem Statement

The FastAPI web application has **no authentication or authorization mechanisms**. All endpoints are publicly accessible including sensitive operations:

- Admin routes (`/admin`, `/admin/cities`, `/admin/provinces`)
- File upload (`/upload-master`)
- File download (`/download/{job_id}`, `/download-latest`)
- Configuration management (`/admin/cities/{province}/{city}`)
- Validation execution (`/run`)

**Why it matters:** Any user can upload arbitrary Excel files, modify configuration, download results, and trigger resource-intensive validation jobs. This is a critical security vulnerability that blocks production deployment.

## Findings

**Location:** `src/web/app.py`

**Evidence:**
```python
# Lines 445-496 - No auth check
@app.post("/upload-master")
async def upload_master(file: UploadFile = File(...)):
    """Upload and parse a master pricing document."""
    # No authentication check before file upload
    ...

# Lines 529-566 - No auth check
@app.post("/admin/cities")
async def add_city(request: Request):
    """Add a new city to a province."""
    # No authentication check before config modification
    ...
```

**Impact:**
- Arbitrary file upload to server
- Configuration tampering
- Data exfiltration via result downloads
- Resource exhaustion via unlimited job creation

## Proposed Solutions

### Option 1: Basic Auth Middleware (Recommended for Internal Tool)

**Description:** Add HTTP Basic Authentication using FastAPI's built-in security utilities.

```python
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import secrets

security = HTTPBasic()

def verify_credentials(credentials: HTTPBasicCredentials = Depends(security)):
    correct_username = secrets.compare_digest(credentials.username, os.getenv("AUTH_USER", "admin"))
    correct_password = secrets.compare_digest(credentials.password, os.getenv("AUTH_PASS", "changeme"))
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

# Apply to routes
@app.post("/admin/cities")
async def add_city(request: Request, user: str = Depends(verify_credentials)):
    ...
```

| Aspect | Assessment |
|--------|------------|
| Pros | Simple, no external dependencies, works with curl/scripts |
| Cons | Credentials sent with every request, less secure than tokens |
| Effort | Small (2-4 hours) |
| Risk | Low |

### Option 2: JWT Token Authentication

**Description:** Implement JWT-based authentication with login endpoint.

```python
from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

async def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    return username
```

| Aspect | Assessment |
|--------|------------|
| Pros | More secure, stateless, industry standard |
| Cons | More complex, requires token management |
| Effort | Medium (4-8 hours) |
| Risk | Low |

### Option 3: API Key Authentication

**Description:** Simple API key validation via header.

```python
from fastapi import Security
from fastapi.security import APIKeyHeader

api_key_header = APIKeyHeader(name="X-API-Key")

async def verify_api_key(api_key: str = Security(api_key_header)):
    if api_key != os.getenv("API_KEY"):
        raise HTTPException(status_code=403, detail="Invalid API key")
    return api_key
```

| Aspect | Assessment |
|--------|------------|
| Pros | Very simple, good for internal APIs |
| Cons | Key rotation requires client updates |
| Effort | Small (1-2 hours) |
| Risk | Low |

## Recommended Action

<!-- To be filled during triage -->

## Technical Details

**Affected Files:**
- `src/web/app.py` - Add auth middleware and protect routes

**Routes Requiring Protection:**
- `POST /run` - Validation execution
- `POST /upload-master` - File upload
- `GET /download/{job_id}` - Result download
- `GET /download-latest` - Latest result download
- `POST /admin/cities` - Add city
- `DELETE /admin/cities/{province}/{city}` - Delete city
- `POST /admin/provinces` - Add province
- `DELETE /admin/provinces/{province}` - Delete province

**Environment Variables to Add:**
- `AUTH_USER` or `API_KEY` depending on chosen approach
- `AUTH_PASS` or `JWT_SECRET` depending on chosen approach

## Acceptance Criteria

- [ ] All admin routes require authentication
- [ ] File upload requires authentication
- [ ] Validation execution requires authentication
- [ ] Unauthenticated requests return 401/403
- [ ] Credentials stored in environment variables, not code
- [ ] README updated with auth configuration instructions

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-02-03 | Created from code review | Security-sentinel agent identified missing auth |

## Resources

- PR: N/A (merged to master)
- FastAPI Security docs: https://fastapi.tiangolo.com/tutorial/security/
- Related: Path traversal issue (002)
