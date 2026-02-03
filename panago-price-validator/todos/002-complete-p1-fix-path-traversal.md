---
status: pending
priority: p1
issue_id: "002"
tags:
  - code-review
  - security
  - path-traversal
dependencies: []
---

# Fix Path Traversal Vulnerability in File Upload

## Problem Statement

The file upload endpoint sanitizes filenames using a regex that **allows dots**, which could potentially enable path traversal attacks through sequences like `....//` or by exploiting path parsing differences.

**Why it matters:** Attackers could potentially write files outside the uploads directory or overwrite critical application files. This is a critical security vulnerability.

## Findings

**Location:** `src/web/app.py`, lines 455-464

**Vulnerable Code:**
```python
# Save the uploaded file
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
safe_filename = re.sub(r'[^\w\-_.]', '_', file.filename)  # ALLOWS DOTS!
filename = f"master_{timestamp}_{safe_filename}"
file_path = UPLOAD_DIR / filename

try:
    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)
```

**Attack Vector:**
- Filename like `....//....//etc/passwd` after sanitization becomes `........__etc_passwd`
- More concerning: filename like `../../../app/main.py` could escape directory
- The regex `[^\w\-_.]` allows `.` which is used in path traversal

**Additional Risk in Download Endpoint (lines 401-422):**
```python
file_path = Path(job["result_file"])
# No validation that path is within OUTPUT_DIR
return FileResponse(path=file_path, ...)
```

## Proposed Solutions

### Option 1: Use pathlib.Path.name + resolve() Validation (Recommended)

**Description:** Extract only the basename and validate the resolved path is within the target directory.

```python
from pathlib import Path

@app.post("/upload-master")
async def upload_master(file: UploadFile = File(...)):
    # Extract just the filename (removes any path components)
    raw_filename = Path(file.filename).name if file.filename else "unnamed"

    # Sanitize remaining filename
    safe_filename = re.sub(r'[^\w\-_.]', '_', raw_filename)

    # Ensure no empty filename
    if not safe_filename or safe_filename.startswith('.'):
        safe_filename = f"upload_{uuid.uuid4().hex[:8]}"

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"master_{timestamp}_{safe_filename}"
    file_path = (UPLOAD_DIR / filename).resolve()

    # CRITICAL: Validate path is within UPLOAD_DIR
    if not file_path.is_relative_to(UPLOAD_DIR.resolve()):
        raise HTTPException(status_code=400, detail="Invalid filename")

    # ... rest of upload logic
```

| Aspect | Assessment |
|--------|------------|
| Pros | Defense in depth, handles edge cases, clear validation |
| Cons | Slightly more code |
| Effort | Small (1-2 hours) |
| Risk | Low |

### Option 2: Whitelist File Extensions Only

**Description:** Only allow specific file extensions (.xls, .xlsx) and generate random filenames.

```python
ALLOWED_EXTENSIONS = {'.xls', '.xlsx'}

@app.post("/upload-master")
async def upload_master(file: UploadFile = File(...)):
    # Check extension
    ext = Path(file.filename).suffix.lower() if file.filename else ''
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Only {ALLOWED_EXTENSIONS} allowed")

    # Generate safe filename (ignore user-provided name entirely)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"master_{timestamp}_{uuid.uuid4().hex[:8]}{ext}"
    file_path = UPLOAD_DIR / filename
    # ...
```

| Aspect | Assessment |
|--------|------------|
| Pros | Simplest approach, ignores user filename entirely |
| Cons | Loses original filename context |
| Effort | Small (1 hour) |
| Risk | Low |

### Option 3: Use secure-filename Library

**Description:** Use the `werkzeug.utils.secure_filename` function.

```python
from werkzeug.utils import secure_filename

safe_filename = secure_filename(file.filename)
```

| Aspect | Assessment |
|--------|------------|
| Pros | Battle-tested, widely used |
| Cons | Adds dependency |
| Effort | Small (30 minutes) |
| Risk | Low |

## Recommended Action

<!-- To be filled during triage -->

## Technical Details

**Affected Files:**
- `src/web/app.py` - Upload and download handlers

**Specific Lines:**
- Lines 455-464: File upload sanitization
- Lines 401-422: Download path validation needed

**Fix for Download Endpoint:**
```python
@app.get("/download/{job_id}")
async def download_results(job_id: str):
    if job_id not in jobs:
        return {"error": "Job not found"}

    job = jobs[job_id]
    file_path = Path(job["result_file"]).resolve()

    # Validate path is within OUTPUT_DIR
    if not file_path.is_relative_to(OUTPUT_DIR.resolve()):
        return {"error": "Invalid file path"}

    if not file_path.exists():
        return {"error": "Result file not found"}

    return FileResponse(path=file_path, ...)
```

## Acceptance Criteria

- [ ] File upload extracts basename only (no path components)
- [ ] Resolved path validated to be within UPLOAD_DIR
- [ ] Download endpoint validates path within OUTPUT_DIR
- [ ] Unit tests for path traversal attempts
- [ ] Test cases: `../file.xls`, `....//file.xls`, `/etc/passwd`

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-02-03 | Created from code review | Security-sentinel identified path traversal risk |

## Resources

- OWASP Path Traversal: https://owasp.org/www-community/attacks/Path_Traversal
- Python pathlib.is_relative_to: https://docs.python.org/3/library/pathlib.html
