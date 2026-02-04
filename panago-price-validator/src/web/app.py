"""FastAPI web application for Panago Price Validator."""
import asyncio
import json
import os
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import aiofiles
import yaml
from fastapi import Depends, FastAPI, HTTPException, Request, BackgroundTasks, Security, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.security import APIKeyHeader
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..models import AutomationConfig, LocationConfig, PricingLevel, PROVINCE_TO_PL
from ..browser_automation import PanagoAutomation
from ..excel_handler import load_expected_prices, save_results
from ..comparison import compare_prices, compare_menu_vs_cart, compare_all_prices
from ..config_loader import load_settings
from ..master_parser import MasterDocumentParser, load_master_document

app = FastAPI(title="Panago Price Validator", version="1.0.0")

# CORS configuration
allowed_origins = os.getenv("CORS_ORIGINS", "http://localhost:8000").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)

# API Key authentication
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: str = Security(api_key_header)):
    """Verify API key for protected endpoints."""
    expected_key = os.getenv("PANAGO_API_KEY")
    if not expected_key:
        # No key configured = auth disabled (for local dev)
        return None
    if api_key != expected_key:
        raise HTTPException(status_code=403, detail="Invalid or missing API key")
    return api_key


# Setup paths
BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
CONFIG_DIR = Path(__file__).parent.parent.parent / "config"
INPUT_DIR = Path(__file__).parent.parent.parent / "input"
OUTPUT_DIR = Path(__file__).parent.parent.parent / "output"
UPLOAD_DIR = Path(__file__).parent.parent.parent / "uploads"
MASTER_INFO_FILE = UPLOAD_DIR / "master_info.json"

# Ensure directories exist
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Setup templates and static files
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Job tracking
jobs: dict[str, dict] = {}
jobs_lock = asyncio.Lock()

# Rate limiting constants
MAX_JOBS = int(os.getenv("MAX_JOBS", "50"))
MAX_CONCURRENT_JOBS = int(os.getenv("MAX_CONCURRENT_JOBS", "5"))
JOB_EXPIRY_HOURS = int(os.getenv("JOB_EXPIRY_HOURS", "24"))


async def cleanup_old_jobs() -> int:
    """Remove jobs older than JOB_EXPIRY_HOURS. Must be called with jobs_lock held."""
    now = datetime.now()
    expired = [
        jid for jid, job in jobs.items()
        if (now - datetime.fromisoformat(job.get("created_at", now.isoformat()))).total_seconds() > JOB_EXPIRY_HOURS * 3600
    ]
    for jid in expired:
        del jobs[jid]
    return len(expired)


async def load_cities_from_config() -> dict[str, list[dict]]:
    """Load cities grouped by province from locations.yaml."""
    locations_path = CONFIG_DIR / "locations.yaml"
    if not locations_path.exists():
        return {}

    async with aiofiles.open(locations_path, 'r') as f:
        content = await f.read()
        data = yaml.safe_load(content)

    provinces = data.get("provinces", {})

    # Fix boolean keys that YAML interprets from ON/NO/etc.
    fixed_provinces = {}
    for code, cities in provinces.items():
        if isinstance(code, bool):
            code = "ON" if code else "NO"
        fixed_provinces[str(code)] = cities

    return fixed_provinces


class QuotedString(str):
    """String subclass that forces YAML to quote the value."""
    pass


def quoted_str_representer(dumper, data):
    """Custom representer to force quoting of strings."""
    return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='"')


yaml.add_representer(QuotedString, quoted_str_representer)


async def load_pricing_levels() -> dict[str, dict]:
    """Load pricing levels from config file."""
    pl_path = CONFIG_DIR / "pricing_levels.yaml"
    if not pl_path.exists():
        return {}

    async with aiofiles.open(pl_path, 'r') as f:
        content = await f.read()
        data = yaml.safe_load(content)

    return data.get("pricing_levels", {})


async def get_master_info() -> Optional[dict]:
    """Get info about the currently loaded master document."""
    if not MASTER_INFO_FILE.exists():
        return None

    try:
        async with aiofiles.open(MASTER_INFO_FILE, 'r') as f:
            content = await f.read()
            return json.loads(content)
    except (json.JSONDecodeError, IOError):
        return None


async def save_master_info(info: dict) -> None:
    """Save master document info."""
    async with aiofiles.open(MASTER_INFO_FILE, "w") as f:
        await f.write(json.dumps(info, indent=2))


async def get_current_master_path() -> Optional[Path]:
    """Get the path to the currently loaded master document."""
    info = await get_master_info()
    if info and "path" in info:
        path = Path(info["path"])
        if path.exists():
            return path
    return None


async def save_cities_to_config(provinces: dict[str, list[dict]]) -> None:
    """Save cities to locations.yaml, preserving other config like categories."""
    locations_path = CONFIG_DIR / "locations.yaml"

    # Load existing config to preserve other sections (like categories)
    existing_data = {}
    if locations_path.exists():
        async with aiofiles.open(locations_path, 'r') as f:
            content = await f.read()
            existing_data = yaml.safe_load(content) or {}

    # Quote province codes that YAML might interpret as booleans (ON, NO, etc.)
    # See: https://yaml.org/type/bool.html
    quoted_provinces = {}
    for code, cities in provinces.items():
        # Convert boolean keys back to strings (in case they were loaded as bool)
        if isinstance(code, bool):
            code = "ON" if code else "NO"
        quoted_provinces[QuotedString(code)] = cities

    # Update provinces section
    existing_data["provinces"] = quoted_provinces

    async with aiofiles.open(locations_path, "w") as f:
        await f.write(yaml.dump(existing_data, default_flow_style=False, allow_unicode=True, sort_keys=False))


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Render the main UI with city selection tiles."""
    pricing_levels = await load_pricing_levels()
    master_info = await get_master_info()
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "pricing_levels": pricing_levels,
            "master_info": master_info,
        }
    )


@app.post("/run")
async def run_validation(request: Request, background_tasks: BackgroundTasks, user: str = Depends(verify_api_key)):
    """Start a validation run for selected cities."""
    form_data = await request.form()
    selected_cities = form_data.getlist("cities")
    capture_cart = form_data.get("capture_cart") == "on"

    if not selected_cities:
        return {"error": "No cities selected", "status": "error"}

    # Create job ID
    job_id = str(uuid.uuid4())[:8]
    async with jobs_lock:
        # Check concurrent job limit
        active_jobs = sum(1 for j in jobs.values() if j["status"] in ("pending", "running"))
        if active_jobs >= MAX_CONCURRENT_JOBS:
            raise HTTPException(429, "Too many active jobs. Please wait.")

        # Check total job limit
        if len(jobs) >= MAX_JOBS:
            await cleanup_old_jobs()
            if len(jobs) >= MAX_JOBS:
                raise HTTPException(429, "Job limit reached. Try again later.")

        jobs[job_id] = {
            "status": "pending",
            "progress": 0,
            "message": "Starting...",
            "cities": selected_cities,
            "capture_cart": capture_cart,
            "result_file": None,
            "error": None,
            "created_at": datetime.now().isoformat(),
            "started_at": None,
            "ended_at": None,
            "elapsed_seconds": 0,
        }

    # Start background task
    background_tasks.add_task(run_validation_task, job_id, selected_cities, capture_cart)

    return {"job_id": job_id, "status": "started"}


async def update_job(job_id: str, **updates):
    """Helper to update job state under the lock."""
    async with jobs_lock:
        if job_id in jobs:
            jobs[job_id].update(updates)


async def run_validation_task(job_id: str, selected_cities: list[str], capture_cart: bool = False):
    """Background task to run the validation."""
    started_at = datetime.now()
    await update_job(job_id, status="running", message="Loading configuration...", progress=5, started_at=started_at.isoformat())

    try:
        # Parse selected cities (format: "PL:city" for pricing levels)
        locations: list[LocationConfig] = []
        pricing_levels_config = await load_pricing_levels()

        for city_key in selected_cities:
            pl_code, city_name = city_key.split(":", 1)

            # Find the city in pricing levels config
            pl_config = pricing_levels_config.get(pl_code, {})
            pl_cities = pl_config.get("cities", [])
            provinces = pl_config.get("provinces", [])
            province = provinces[0] if provinces else "BC"

            for city_data in pl_cities:
                if city_data["city"] == city_name:
                    # Convert PL code to PricingLevel enum
                    try:
                        pricing_level = PricingLevel(pl_code)
                    except ValueError:
                        pricing_level = PricingLevel.PL1

                    locations.append(LocationConfig(
                        store_name=city_data.get("store_name", city_name),
                        address=city_name,
                        province=province,
                        pricing_level=pricing_level,
                    ))
                    break

        cart_mode_text = " (with cart comparison)" if capture_cart else ""
        await update_job(job_id, message=f"Validating {len(locations)} location(s){cart_mode_text}...", progress=10)

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

        await update_job(job_id, message="Starting browser automation...", progress=15)

        # Progress callback to update job status in real-time
        async def update_progress_async(message: str):
            await update_job(job_id, message=message)

        def update_progress(message: str):
            # Schedule the async update (fire-and-forget for progress updates)
            asyncio.create_task(update_progress_async(message))

        # Create automation instance
        automation = PanagoAutomation(
            config,
            CONFIG_DIR / "locations.yaml",
            base_url=base_url,
            min_delay_ms=min_delay,
            max_delay_ms=max_delay,
            capture_cart_prices=capture_cart,
            progress_callback=update_progress,
        )

        # Override locations with selected ones
        automation.set_locations(locations)

        # Run collection (this is the long part)
        cart_note = " (including cart prices - this may take a while)" if capture_cart else ""
        await update_job(job_id, message=f"Collecting prices from {len(locations)} location(s){cart_note}...", progress=20)

        # Run async collection
        actual_prices = await automation._run_async()

        await update_job(job_id, message=f"Collected {len(actual_prices)} prices. Comparing...", progress=80)

        # Load expected prices from master document or fallback to old format
        master_path = await get_current_master_path()
        expected_prices_list = None
        expected_df = None

        if master_path:
            await update_job(job_id, message="Loading expected prices from master document...")
            expected_prices_list = load_master_document(master_path)
            # Convert to DataFrame for comparison
            import pandas as pd
            expected_df = pd.DataFrame([p.to_dict() for p in expected_prices_list])
        else:
            # Fallback to old expected_prices.xlsx format
            if config.input_file.exists():
                expected_df = load_expected_prices(config.input_file)

        # Filter to only MENU prices for expected vs actual comparison
        from ..models import PriceSource
        menu_prices = [p for p in actual_prices if p.price_source == PriceSource.MENU]

        # Compare prices (expected vs actual menu prices)
        if expected_df is not None and not expected_df.empty:
            results = compare_prices(expected_df, menu_prices, tolerance=0.01)
        else:
            results = {
                "summary": "No expected prices loaded",
                "summary_df": pd.DataFrame(),
                "details_df": pd.DataFrame(),
                "discrepancies_df": pd.DataFrame(),
            }

        # Compare menu vs cart prices if cart capture was enabled
        menu_vs_cart_results = None
        all_prices_results = None
        if capture_cart:
            await update_job(job_id, message="Comparing menu vs cart prices...", progress=85)
            menu_vs_cart_results = compare_menu_vs_cart(actual_prices, tolerance=0.01)

            # Create comprehensive comparison with all three prices
            if expected_df is not None and not expected_df.empty:
                await update_job(job_id, message="Creating comprehensive price comparison...", progress=88)
                all_prices_results = compare_all_prices(expected_df, actual_prices, tolerance=0.01)

        await update_job(job_id, message="Saving results...", progress=90)

        # Calculate timing
        ended_at = datetime.now()
        elapsed_seconds = (ended_at - started_at).total_seconds()
        timing_info = {
            "started_at": started_at.isoformat(),
            "ended_at": ended_at.isoformat(),
            "elapsed_seconds": elapsed_seconds,
            "locations_count": len(locations),
        }

        # Save results with timing info
        output_path = save_results(
            results,
            config.output_dir,
            menu_vs_cart_results=menu_vs_cart_results,
            all_prices_results=all_prices_results,
            timing_info=timing_info,
        )

        # Build summary message with timing
        elapsed_str = f"{int(elapsed_seconds // 60)}m {int(elapsed_seconds % 60)}s"
        summary_parts = [results['summary']]
        if all_prices_results:
            summary_parts.append(all_prices_results['summary'])
        elif menu_vs_cart_results:
            summary_parts.append(menu_vs_cart_results['summary'])

        await update_job(
            job_id,
            status="completed",
            message=f"Complete! {' | '.join(summary_parts)}",
            progress=100,
            result_file=str(output_path),
            ended_at=ended_at.isoformat(),
            elapsed_seconds=elapsed_seconds,
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        await update_job(job_id, status="error", message=f"Error: {str(e)}", error=str(e))


@app.get("/status/{job_id}")
async def get_status(job_id: str):
    """Get the status of a validation job."""
    async with jobs_lock:
        if job_id not in jobs:
            return {"error": "Job not found", "status": "error"}
        return jobs[job_id].copy()


@app.get("/stream/{job_id}")
async def stream_status(job_id: str):
    """SSE endpoint for real-time progress updates."""
    async def event_generator():
        while True:
            async with jobs_lock:
                if job_id not in jobs:
                    yield f"data: {{'error': 'Job not found'}}\n\n"
                    break
                job = jobs[job_id].copy()

            # Calculate elapsed time dynamically for running jobs
            if job["status"] == "running" and job.get("started_at"):
                started = datetime.fromisoformat(job["started_at"])
                job["elapsed_seconds"] = (datetime.now() - started).total_seconds()

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
    async with jobs_lock:
        if job_id not in jobs:
            return {"error": "Job not found"}
        job = jobs[job_id].copy()

    if job["status"] != "completed":
        return {"error": "Job not complete"}

    if not job["result_file"]:
        return {"error": "No result file"}

    file_path = Path(job["result_file"]).resolve()

    # Validate path is within OUTPUT_DIR to prevent path traversal
    if not file_path.is_relative_to(OUTPUT_DIR.resolve()):
        return {"error": "Invalid file path"}

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


# Master document management routes


@app.post("/upload-master")
async def upload_master(file: UploadFile = File(...), user: str = Depends(verify_api_key)):
    """Upload and parse a master pricing document."""
    # Validate file type
    if not file.filename or not file.filename.endswith(('.xls', '.xlsx')):
        return JSONResponse(
            {"error": "File must be an Excel document (.xls or .xlsx)"},
            status_code=400
        )

    # Save the uploaded file with path traversal protection
    # Extract just the filename (removes any path components)
    raw_filename = Path(file.filename).name if file.filename else "unnamed"
    safe_filename = re.sub(r'[^\w\-_.]', '_', raw_filename)

    # Ensure no empty/hidden filename
    if not safe_filename or safe_filename.startswith('.'):
        safe_filename = f"upload_{uuid.uuid4().hex[:8]}"

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"master_{timestamp}_{safe_filename}"
    file_path = (UPLOAD_DIR / filename).resolve()

    # CRITICAL: Validate path is within UPLOAD_DIR
    if not file_path.is_relative_to(UPLOAD_DIR.resolve()):
        raise HTTPException(status_code=400, detail="Invalid filename")

    try:
        content = await file.read()
        async with aiofiles.open(file_path, "wb") as f:
            await f.write(content)

        # Parse the document to validate it
        parser = MasterDocumentParser(file_path)
        prices = parser.parse()
        summary = parser.get_summary()

        # Save master info
        master_info = {
            "path": str(file_path),
            "filename": file.filename,
            "uploaded_at": timestamp,
            "total_prices": summary["total"],
            "by_category": summary["by_category"],
            "by_pl": summary["by_pl"],
        }
        await save_master_info(master_info)

        return {
            "success": True,
            "message": f"Uploaded and parsed {file.filename}",
            "filename": filename,
            "summary": summary,
        }

    except Exception as e:
        # Clean up file on error
        if file_path.exists():
            file_path.unlink()
        return JSONResponse(
            {"error": f"Failed to parse document: {str(e)}"},
            status_code=400
        )


@app.get("/master-info")
async def master_info_endpoint():
    """Get info about the currently loaded master document."""
    info = await get_master_info()
    if not info:
        return {"loaded": False}

    # Check if file still exists
    if not Path(info.get("path", "")).exists():
        return {"loaded": False, "error": "Master file no longer exists"}

    return {"loaded": True, **info}


# Admin routes for city configuration


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    """Render the admin page for managing cities."""
    provinces = await load_cities_from_config()
    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "provinces": provinces,
        }
    )


@app.post("/admin/cities")
async def add_city(request: Request, user: str = Depends(verify_api_key)):
    """Add a new city to a province."""
    form_data = await request.form()
    province = form_data.get("province", "").strip().upper()
    city = form_data.get("city", "").strip()
    store_name = form_data.get("store_name", "").strip() or city

    # Validate province code (2 letters)
    if not province or not re.match(r"^[A-Z]{2}$", province):
        return JSONResponse(
            {"error": "Province must be a 2-letter code (e.g., BC, ON)"},
            status_code=400
        )

    if not city:
        return JSONResponse({"error": "City name is required"}, status_code=400)

    provinces = await load_cities_from_config()

    # Initialize province if it doesn't exist
    if province not in provinces:
        provinces[province] = []

    # Check for duplicate city
    for existing_city in provinces[province]:
        if existing_city["city"].lower() == city.lower():
            return JSONResponse(
                {"error": f"City '{city}' already exists in {province}"},
                status_code=400
            )

    # Add the city
    provinces[province].append({"city": city, "store_name": store_name})
    await save_cities_to_config(provinces)

    return {"success": True, "message": f"Added {city} to {province}"}


@app.delete("/admin/cities/{province}/{city}")
async def delete_city(province: str, city: str, user: str = Depends(verify_api_key)):
    """Remove a city from a province."""
    province = province.upper()
    provinces = await load_cities_from_config()

    if province not in provinces:
        return JSONResponse({"error": f"Province '{province}' not found"}, status_code=404)

    # Find and remove the city
    original_count = len(provinces[province])
    provinces[province] = [c for c in provinces[province] if c["city"] != city]

    if len(provinces[province]) == original_count:
        return JSONResponse({"error": f"City '{city}' not found in {province}"}, status_code=404)

    await save_cities_to_config(provinces)
    return {"success": True, "message": f"Removed {city} from {province}"}


@app.post("/admin/provinces")
async def add_province(request: Request, user: str = Depends(verify_api_key)):
    """Add a new province."""
    form_data = await request.form()
    province = form_data.get("province", "").strip().upper()

    # Validate province code (2 letters)
    if not province or not re.match(r"^[A-Z]{2}$", province):
        return JSONResponse(
            {"error": "Province must be a 2-letter code (e.g., BC, ON)"},
            status_code=400
        )

    provinces = await load_cities_from_config()

    if province in provinces:
        return JSONResponse(
            {"error": f"Province '{province}' already exists"},
            status_code=400
        )

    provinces[province] = []
    await save_cities_to_config(provinces)

    return {"success": True, "message": f"Added province {province}"}


@app.delete("/admin/provinces/{province}")
async def delete_province(province: str, user: str = Depends(verify_api_key)):
    """Delete an empty province."""
    province = province.upper()
    provinces = await load_cities_from_config()

    if province not in provinces:
        return JSONResponse({"error": f"Province '{province}' not found"}, status_code=404)

    if provinces[province]:
        return JSONResponse(
            {"error": f"Cannot delete province '{province}' - it still has cities. Remove all cities first."},
            status_code=400
        )

    del provinces[province]
    await save_cities_to_config(provinces)

    return {"success": True, "message": f"Removed province {province}"}
