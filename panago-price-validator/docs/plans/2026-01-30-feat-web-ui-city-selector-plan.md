# Feature: Web UI City Selector for Price Validation

**Created:** 2026-01-30
**Status:** Complete
**Type:** New Feature

## Problem Statement

The Panago Price Validator currently runs via CLI or Docker commands, requiring technical knowledge to operate. The QA team needs a simple web-based interface to:

1. Select one or more cities/stores from a configuration file
2. Run the price validation automation
3. Download the results as an Excel file

The UI should use Material Design 3 visuals and be packaged in a Docker container for easy distribution.

## Acceptance Criteria

- [x] Web UI displays list of cities/stores from YAML config file
- [x] Cities displayed as selectable Material Design 3 tiles
- [x] Support single-select and multi-select modes (select multiple cities)
- [x] "Select All" / "Deselect All" functionality
- [x] "Run Validation" button triggers the automation for selected cities
- [x] Progress indicator shows validation status while running
- [x] Results downloadable as Excel file when complete
- [x] Error states displayed clearly (no cities selected, automation failure)
- [x] Entire application packaged in single Docker container
- [x] Works on port 8080 by default

## Essential Context

### Existing Patterns

The project already has:
- **Async automation**: `src/browser_automation.py` uses `async/await` with Playwright
- **YAML config**: `config/locations.yaml` contains province → cities → stores structure
- **Docker setup**: `Dockerfile` with Playwright/Chromium, `docker-compose.yml`
- **Data models**: `src/models.py` with frozen dataclasses

### Recommended Stack

- **Backend**: FastAPI (async, lightweight, good Docker support)
- **Frontend**: Jinja2 templates + HTMX (simple, no build step, SSR)
- **Styling**: Material Design 3 CSS (via CDN or bundled)
- **Progress updates**: Server-Sent Events (SSE) for real-time status

### Key User Flows

1. **Single City**: Select one city tile → Run → Download results
2. **Multi City**: Select multiple tiles → Run → Single combined Excel output
3. **Select All**: Click "Select All" → Run full validation → Download

### File Structure

```
src/
├── web/
│   ├── app.py           # FastAPI application
│   ├── templates/
│   │   └── index.html   # Main UI template
│   └── static/
│       └── styles.css   # Material Design 3 styles
```

### Docker Changes

Update `Dockerfile` to:
1. Install FastAPI and uvicorn
2. Expose port 8080
3. Set entrypoint to run web server

Update `docker-compose.yml` to add web service with port mapping.

## Implementation Checklist

- [x] Create FastAPI app with city list endpoint
- [x] Create Jinja2 template with Material Design 3 tiles
- [x] Add city selection JavaScript (toggle tiles, select all)
- [x] Create `/run` endpoint that triggers automation
- [x] Add SSE endpoint for progress updates
- [x] Create `/download` endpoint for Excel results
- [x] Update Dockerfile for web mode
- [x] Update docker-compose.yml with web service
- [x] Test end-to-end in Docker
