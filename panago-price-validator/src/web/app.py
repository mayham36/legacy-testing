"""FastAPI web application for Panago Price Validator."""
import asyncio
import uuid
from pathlib import Path
from typing import Optional

import yaml
from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..models import AutomationConfig, LocationConfig
from ..browser_automation import PanagoAutomation
from ..excel_handler import load_expected_prices, save_results
from ..comparison import compare_prices
from ..config_loader import load_settings

app = FastAPI(title="Panago Price Validator", version="1.0.0")

# Setup paths
BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
CONFIG_DIR = Path(__file__).parent.parent.parent / "config"
INPUT_DIR = Path(__file__).parent.parent.parent / "input"
OUTPUT_DIR = Path(__file__).parent.parent.parent / "output"

# Ensure output directory exists
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Setup templates and static files
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Job tracking
jobs: dict[str, dict] = {}


def load_cities_from_config() -> dict[str, list[dict]]:
    """Load cities grouped by province from locations.yaml."""
    locations_path = CONFIG_DIR / "locations.yaml"
    if not locations_path.exists():
        return {}

    with open(locations_path) as f:
        data = yaml.safe_load(f)

    return data.get("provinces", {})


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Render the main UI with city selection tiles."""
    provinces = load_cities_from_config()
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "provinces": provinces,
        }
    )


@app.post("/run")
async def run_validation(request: Request, background_tasks: BackgroundTasks):
    """Start a validation run for selected cities."""
    form_data = await request.form()
    selected_cities = form_data.getlist("cities")

    if not selected_cities:
        return {"error": "No cities selected", "status": "error"}

    # Create job ID
    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {
        "status": "pending",
        "progress": 0,
        "message": "Starting...",
        "cities": selected_cities,
        "result_file": None,
        "error": None,
    }

    # Start background task
    background_tasks.add_task(run_validation_task, job_id, selected_cities)

    return {"job_id": job_id, "status": "started"}


async def run_validation_task(job_id: str, selected_cities: list[str]):
    """Background task to run the validation."""
    job = jobs[job_id]

    try:
        job["status"] = "running"
        job["message"] = "Loading configuration..."
        job["progress"] = 5

        # Parse selected cities (format: "province:city")
        locations: list[LocationConfig] = []
        provinces_data = load_cities_from_config()

        for city_key in selected_cities:
            province, city_name = city_key.split(":", 1)
            # Find the city data
            province_cities = provinces_data.get(province, [])
            for city_data in province_cities:
                if city_data["city"] == city_name:
                    locations.append(LocationConfig(
                        store_name=city_data.get("store_name", city_name),
                        address=city_name,  # Use city name for lookup
                        province=province,
                    ))
                    break

        job["message"] = f"Validating {len(locations)} location(s)..."
        job["progress"] = 10

        # Load settings
        settings_path = CONFIG_DIR / "settings.yaml"
        settings = {}
        if settings_path.exists():
            settings = load_settings(settings_path)

        # Use QA environment settings
        env_settings = settings.get("environments", {}).get("qa", {})
        base_url = env_settings.get("base_url", "https://www.panago.com")

        # Safe mode settings
        safe_settings = settings.get("safe_mode_settings", {})
        max_concurrent = safe_settings.get("max_concurrent", 1)
        min_delay = safe_settings.get("min_delay_ms", 5000)
        max_delay = safe_settings.get("max_delay_ms", 10000)

        # Create automation config
        config = AutomationConfig(
            input_file=INPUT_DIR / "expected_prices.xlsx",
            output_dir=OUTPUT_DIR,
            headless=True,
            max_concurrent=max_concurrent,
            timeout_ms=30000,
        )

        job["message"] = "Starting browser automation..."
        job["progress"] = 15

        # Create automation instance
        automation = PanagoAutomation(
            config,
            CONFIG_DIR / "locations.yaml",
            base_url=base_url,
            min_delay_ms=min_delay,
            max_delay_ms=max_delay,
        )

        # Override locations with selected ones
        automation.set_locations(locations)

        # Run collection (this is the long part)
        job["message"] = f"Collecting prices from {len(locations)} location(s)..."
        job["progress"] = 20

        # Run async collection
        actual_prices = await automation._run_async()

        job["message"] = f"Collected {len(actual_prices)} prices. Comparing..."
        job["progress"] = 80

        # Load expected prices
        expected_prices = load_expected_prices(config.input_file)

        # Compare prices
        results = compare_prices(expected_prices, actual_prices, tolerance=0.01)

        job["message"] = "Saving results..."
        job["progress"] = 90

        # Save results
        output_path = save_results(results, config.output_dir)

        job["status"] = "completed"
        job["message"] = f"Complete! {results['summary']}"
        job["progress"] = 100
        job["result_file"] = str(output_path)

    except Exception as e:
        job["status"] = "error"
        job["message"] = f"Error: {str(e)}"
        job["error"] = str(e)


@app.get("/status/{job_id}")
async def get_status(job_id: str):
    """Get the status of a validation job."""
    if job_id not in jobs:
        return {"error": "Job not found", "status": "error"}
    return jobs[job_id]


@app.get("/stream/{job_id}")
async def stream_status(job_id: str):
    """SSE endpoint for real-time progress updates."""
    async def event_generator():
        while True:
            if job_id not in jobs:
                yield f"data: {{'error': 'Job not found'}}\n\n"
                break

            job = jobs[job_id]
            import json
            yield f"data: {json.dumps(job)}\n\n"

            if job["status"] in ("completed", "error"):
                break

            await asyncio.sleep(1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


@app.get("/download/{job_id}")
async def download_results(job_id: str):
    """Download the results Excel file."""
    if job_id not in jobs:
        return {"error": "Job not found"}

    job = jobs[job_id]
    if job["status"] != "completed":
        return {"error": "Job not complete"}

    if not job["result_file"]:
        return {"error": "No result file"}

    file_path = Path(job["result_file"])
    if not file_path.exists():
        return {"error": "Result file not found"}

    return FileResponse(
        path=file_path,
        filename=file_path.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


@app.get("/download-latest")
async def download_latest():
    """Download the most recent results file."""
    # Find the most recent Excel file in output directory
    excel_files = list(OUTPUT_DIR.glob("validation_results_*.xlsx"))
    if not excel_files:
        return {"error": "No results files found"}

    latest_file = max(excel_files, key=lambda p: p.stat().st_mtime)

    return FileResponse(
        path=latest_file,
        filename=latest_file.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
