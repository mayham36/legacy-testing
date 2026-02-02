---
title: "Docker Distribution for Non-Technical Users"
category: deployment-patterns
tags:
  - docker
  - docker-compose
  - distribution
  - non-technical-users
  - launcher-scripts
  - setup-guide
module: panago-price-validator
symptoms:
  - "Non-technical team members cannot set up Python environment"
  - "Playwright requires complex system dependencies"
  - "Cross-platform deployment needed (Windows/Mac/Linux)"
  - "Users need single-click startup experience"
  - "CLI flags too complex for QA team"
root_cause: "CLI automation tool required development environment knowledge to install and run"
solution_pattern: "Docker containerization with launcher scripts and web UI"
date: 2026-02-02
related_docs:
  - docs/solutions/feature-patterns/cli-to-web-ui-wrapper.md
  - SETUP-GUIDE.md
  - README.md
---

# Docker Distribution for Non-Technical Users

## Problem

A Docker-based price validation tool needed to be distributed to QA team members who lack development environment setup skills. The tool requires:
- Python 3.12+
- Playwright with Chromium browser
- Multiple system-level dependencies (libgtk, libnss, etc.)

**Barriers for non-technical users:**
- Cannot install Python or manage virtual environments
- Cannot run CLI commands with flags
- Need cross-platform support (Windows/Mac)
- Need single-click startup experience

## Solution

A four-layer approach to "zero-friction deployment":

### 1. Simple `docker compose up` Default

Structure `docker-compose.yml` so the default service is the web UI:

```yaml
services:
  web:
    build: .
    ports:
      - "8080:8080"
    volumes:
      - ./input:/app/input
      - ./output:/app/output
      - ./config:/app/config
    command: ["--web", "--port", "8080"]

  # CLI variants hidden behind profiles
  validator:
    profiles: ["cli"]
    # ...
```

### 2. Platform-Specific Launcher Scripts

**Windows (`start.bat`):**
```batch
@echo off
echo ============================================
echo   Panago Price Validator
echo ============================================
echo.
echo Starting... (this may take a moment on first run)
echo Once started, open your browser to:
echo   http://localhost:8080
echo ============================================
docker compose up
pause
```

**Mac/Linux (`start.sh`):**
```bash
#!/bin/bash
echo "Starting... open http://localhost:8080"
docker compose up
```

### 3. Step-by-Step Setup Guide

Create `SETUP-GUIDE.md` written for non-technical audience:

1. Install Docker Desktop (with links to official installers)
2. Extract zip file to folder
3. Double-click `start.bat`
4. Open `http://localhost:8080`
5. Troubleshooting section with exact error messages

### 4. Distribution via Zip File

Package everything needed:
```
panago-validator.zip/
├── start.bat           # Windows launcher
├── start.sh            # Mac/Linux launcher
├── docker-compose.yml
├── Dockerfile
├── SETUP-GUIDE.md
├── config/
├── input/              # With sample data
└── output/
```

Create with:
```sh
zip -r panago-validator-dist.zip panago-price-validator \
  -x "*venv/*" -x "*.git/*" -x "*__pycache__/*"
```

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Web UI as default | No CLI knowledge required |
| Volume mounts for data | Users access files normally, not inside container |
| Profiles for CLI modes | Power users can still use CLI |
| Port 8080 | Avoids conflicts with port 80 |
| Friendly console messages | Users know what to do next |

## User Journey

| Step | User Action | Result |
|------|-------------|--------|
| 1 | Install Docker Desktop | One-time, graphical installer |
| 2 | Extract zip | Standard operation |
| 3 | Double-click `start.bat` | Everything launches |
| 4 | Open browser | URL shown in console |

## Prevention: Best Practices Checklist

Before distributing Docker apps to non-technical users:

- [ ] Default command runs the user-facing interface
- [ ] Launcher scripts for all target platforms
- [ ] Setup guide with Docker Desktop install links
- [ ] Sample data included for immediate testing
- [ ] Troubleshooting section with common errors
- [ ] Volume mounts for user-accessible data
- [ ] Non-conflicting port (8080+)
- [ ] Progress messages during startup

## Testing Checklist

- [ ] Test on machine without project source
- [ ] Test with fresh Docker install (no cached images)
- [ ] Test path with spaces: `C:\Users\John Smith\tool\`
- [ ] Test all platforms (Windows, Mac, Linux)
- [ ] Time the setup: should be <5 minutes

## Files Created

| File | Purpose |
|------|---------|
| `start.bat` | Windows double-click launcher |
| `start.sh` | Mac/Linux launcher |
| `SETUP-GUIDE.md` | Non-technical setup instructions |
| `docker-compose.yml` | Service orchestration with sensible defaults |

## Related Documentation

- [CLI-to-Web-UI Wrapper Pattern](../feature-patterns/cli-to-web-ui-wrapper.md) - Technical architecture
- [SETUP-GUIDE.md](../../../SETUP-GUIDE.md) - User-facing instructions
- [README.md](../../../README.md) - Full project documentation
