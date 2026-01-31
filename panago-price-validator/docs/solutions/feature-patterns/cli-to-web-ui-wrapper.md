---
title: "Web UI Wrapper for CLI Automation Tool"
category: feature-patterns
tags: [web-ui, fastapi, material-design, sse, docker, jinja2, htmx]
module: src/web
symptom: "CLI-only tool required technical knowledge; QA team needed simple interface for city selection and price validation"
root_cause: "No graphical interface existed for non-technical users to operate the price validation tool"
date: 2026-01-30
---

# Web UI Wrapper for CLI Automation Tool

## Problem

The Panago Price Validator was a CLI-only tool requiring technical knowledge to operate. The QA team needed a simple web interface to:

- Select cities/stores from a configuration file
- Run price validation automation
- Download results as Excel files
- See real-time progress during validation

## Solution

Implemented a FastAPI web application with Material Design 3 styling that wraps the existing CLI automation, providing:

- City selection tiles grouped by Canadian province
- Select All / Deselect All functionality
- Real-time progress updates via Server-Sent Events (SSE)
- Excel file download when validation completes
- Docker integration on port 8080

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Docker Container                      │
│  ┌─────────────────────────────────────────────────────┐│
│  │  FastAPI Web Server (port 8080)                     ││
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐ ││
│  │  │ GET /       │  │ POST /run   │  │ GET /stream │ ││
│  │  │ City tiles  │  │ Start job   │  │ SSE updates │ ││
│  │  └─────────────┘  └─────────────┘  └─────────────┘ ││
│  └─────────────────────────────────────────────────────┘│
│                          │                               │
│                          ▼                               │
│  ┌─────────────────────────────────────────────────────┐│
│  │  Existing Automation (PanagoAutomation)             ││
│  │  - Browser automation with Playwright               ││
│  │  - Price comparison logic                           ││
│  │  - Excel report generation                          ││
│  └─────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────┘
```

## Implementation

### Step 1: FastAPI Application

**File:** `src/web/app.py`

```python
from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

app = FastAPI(title="Panago Price Validator")
jobs: dict[str, dict] = {}  # In-memory job tracking

@app.get("/")
async def index(request: Request):
    """Render city selection UI."""
    provinces = load_cities_from_config()
    return templates.TemplateResponse("index.html", {"request": request, "provinces": provinces})

@app.post("/run")
async def run_validation(request: Request, background_tasks: BackgroundTasks):
    """Start validation job in background."""
    form_data = await request.form()
    selected_cities = form_data.getlist("cities")

    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {"status": "pending", "progress": 0, "message": "Starting..."}

    background_tasks.add_task(run_validation_task, job_id, selected_cities)
    return {"job_id": job_id, "status": "started"}

@app.get("/stream/{job_id}")
async def stream_status(job_id: str):
    """SSE endpoint for real-time progress."""
    async def event_generator():
        while True:
            job = jobs.get(job_id, {"error": "Job not found"})
            yield f"data: {json.dumps(job)}\n\n"
            if job.get("status") in ("completed", "error"):
                break
            await asyncio.sleep(1)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/download/{job_id}")
async def download_results(job_id: str):
    """Download Excel results file."""
    return FileResponse(path=jobs[job_id]["result_file"], filename="results.xlsx")
```

### Step 2: Material Design 3 Template

**File:** `src/web/templates/index.html`

```html
<!-- City tiles with checkbox selection -->
<div class="cities-grid">
    {% for city in cities %}
    <label class="city-tile">
        <input type="checkbox" name="cities" value="{{ province }}:{{ city.city }}">
        <div class="tile-content">
            <span class="material-icons">location_city</span>
            <span class="city-name">{{ city.city }}</span>
        </div>
        <span class="checkmark"><span class="material-icons">check</span></span>
    </label>
    {% endfor %}
</div>

<!-- SSE-based progress updates -->
<script>
function startPolling(jobId) {
    const eventSource = new EventSource('/stream/' + jobId);
    eventSource.onmessage = function(event) {
        const data = JSON.parse(event.data);
        updateProgress(data);
        if (data.status === 'completed') {
            eventSource.close();
            showResults(data);
        }
    };
}
</script>
```

### Step 3: CSS with MD3 Tokens

**File:** `src/web/static/styles.css`

```css
:root {
    --md-sys-color-primary: #006A60;
    --md-sys-color-primary-container: #74F8E5;
    --md-sys-color-surface: #FAFDFA;
    --md-sys-shape-corner-medium: 12px;
}

.city-tile input:checked + .tile-content {
    background-color: var(--md-sys-color-primary-container);
    border-color: var(--md-sys-color-primary);
}
```

### Step 4: CLI/Web Mode Switching

**File:** `src/main.py`

```python
def run_web_server(host: str = "0.0.0.0", port: int = 8080):
    import uvicorn
    from .web.app import app
    uvicorn.run(app, host=host, port=port)

def main() -> int:
    args = parse_args()

    if args.web:
        run_web_server(host=args.host, port=args.port)
        return 0

    # CLI mode continues as before...
```

### Step 5: Docker Configuration

**Dockerfile:**
```dockerfile
EXPOSE 8080
ENTRYPOINT ["python", "-m", "src.main"]
CMD ["--web"]
```

**docker-compose.yml:**
```yaml
services:
  web:
    build: .
    ports:
      - "8080:8080"
    command: ["--web", "--port", "8080"]
```

## Usage

```bash
# Docker (recommended)
docker-compose up
# Access http://localhost:8080

# Local development
python -m src.main --web --port 8080

# CLI mode still works
python -m src.main -i input/expected_prices.xlsx
```

## Best Practices

### When to Use This Pattern

| Scenario | Fit |
|----------|-----|
| Internal tools with simple UI needs | Excellent |
| CLI tools needing web interface | Excellent |
| Single-page applications | Good |
| Complex SPAs with state management | Use React/Vue instead |

### Key Decisions

1. **FastAPI + Jinja2** - No JavaScript build step required
2. **SSE over WebSockets** - Simpler for one-way progress updates
3. **BackgroundTasks** - Long operations don't block requests
4. **In-memory job tracking** - Simple for single-instance deployments
5. **Single Docker image** - Same container runs web or CLI mode

### Common Pitfalls

| Pitfall | Solution |
|---------|----------|
| SSE fails silently | Implement polling fallback |
| Job dictionary grows forever | Add cleanup for old jobs |
| Missing `python-multipart` | Form parsing fails - add to requirements |
| Background task exceptions lost | Wrap in try/except, update job status |

## Dependencies

```
fastapi>=0.109.0
uvicorn[standard]>=0.27.0
jinja2>=3.1.0
python-multipart>=0.0.6
```

## Files

| File | Purpose |
|------|---------|
| `src/web/app.py` | FastAPI routes, SSE, job management |
| `src/web/templates/index.html` | Jinja2 template with vanilla JS |
| `src/web/static/styles.css` | Material Design 3 CSS |
| `src/main.py` | CLI/Web mode switching |
| `Dockerfile` | Single image for both modes |
| `docker-compose.yml` | Service definitions |

## Related

- [FastAPI Background Tasks](https://fastapi.tiangolo.com/tutorial/background-tasks/)
- [Server-Sent Events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events)
- [Material Design 3 Color System](https://m3.material.io/styles/color/overview)
