"""FastAPI web application for Panago Price Validator."""
import asyncio
import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml
from fastapi import FastAPI, Request, BackgroundTasks, UploadFile, File
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..models import AutomationConfig, LocationConfig, PricingLevel, PROVINCE_TO_PL
from ..browser_automation import PanagoAutomation
from ..excel_handler import load_expected_prices, save_results
from ..comparison import compare_prices, compare_menu_vs_cart, compare_all_prices
from ..config_loader import load_settings
from ..master_parser import MasterDocumentParser, load_master_document

app = FastAPI(title="Panago Price Validator", version="1.0.0")

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


def load_cities_from_config() -> dict[str, list[dict]]:
    """Load cities grouped by province from locations.yaml."""
    locations_path = CONFIG_DIR / "locations.yaml"
    if not locations_path.exists():
        return {}

    with open(locations_path) as f:
        data = yaml.safe_load(f)

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


def load_pricing_levels() -> dict[str, dict]:
    """Load pricing levels from config file."""
    pl_path = CONFIG_DIR / "pricing_levels.yaml"
    if not pl_path.exists():
        return {}

    with open(pl_path) as f:
        data = yaml.safe_load(f)

    return data.get("pricing_levels", {})


def get_master_info() -> Optional[dict]:
    """Get info about the currently loaded master document."""
    if not MASTER_INFO_FILE.exists():
        return None

    try:
        with open(MASTER_INFO_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def save_master_info(info: dict) -> None:
    """Save master document info."""
    with open(MASTER_INFO_FILE, "w") as f:
        json.dump(info, f, indent=2)


def get_current_master_path() -> Optional[Path]:
    """Get the path to the currently loaded master document."""
    info = get_master_info()
    if info and "path" in info:
        path = Path(info["path"])
        if path.exists():
            return path
    return None


def save_cities_to_config(provinces: dict[str, list[dict]]) -> None:
    """Save cities to locations.yaml, preserving other config like categories."""
    locations_path = CONFIG_DIR / "locations.yaml"

    # Load existing config to preserve other sections (like categories)
    existing_data = {}
    if locations_path.exists():
        with open(locations_path) as f:
            existing_data = yaml.safe_load(f) or {}

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

    with open(locations_path, "w") as f:
        yaml.dump(existing_data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Render the main UI with city selection tiles."""
    pricing_levels = load_pricing_levels()
    master_info = get_master_info()
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "pricing_levels": pricing_levels,
            "master_info": master_info,
        }
    )


@app.post("/run")
async def run_validation(request: Request, background_tasks: BackgroundTasks):
    """Start a validation run for selected cities."""
    form_data = await request.form()
    selected_cities = form_data.getlist("cities")
    capture_cart = form_data.get("capture_cart") == "on"

    if not selected_cities:
        return {"error": "No cities selected", "status": "error"}

    # Create job ID
    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {
        "status": "pending",
        "progress": 0,
        "message": "Starting...",
        "cities": selected_cities,
        "capture_cart": capture_cart,
        "result_file": None,
        "error": None,
    }

    # Start background task
    background_tasks.add_task(run_validation_task, job_id, selected_cities, capture_cart)

    return {"job_id": job_id, "status": "started"}


async def run_validation_task(job_id: str, selected_cities: list[str], capture_cart: bool = False):
    """Background task to run the validation."""
    job = jobs[job_id]

    try:
        job["status"] = "running"
        job["message"] = "Loading configuration..."
        job["progress"] = 5

        # Parse selected cities (format: "PL:city" for pricing levels)
        locations: list[LocationConfig] = []
        pricing_levels_config = load_pricing_levels()

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
        job["message"] = f"Validating {len(locations)} location(s){cart_mode_text}..."
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

        # Progress callback to update job status in real-time
        def update_progress(message: str):
            job["message"] = message

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
        job["message"] = f"Collecting prices from {len(locations)} location(s){cart_note}..."
        job["progress"] = 20

        # Run async collection
        actual_prices = await automation._run_async()

        job["message"] = f"Collected {len(actual_prices)} prices. Comparing..."
        job["progress"] = 80

        # Load expected prices from master document or fallback to old format
        master_path = get_current_master_path()
        expected_prices_list = None
        expected_df = None

        if master_path:
            job["message"] = "Loading expected prices from master document..."
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
            job["message"] = "Comparing menu vs cart prices..."
            job["progress"] = 85
            menu_vs_cart_results = compare_menu_vs_cart(actual_prices, tolerance=0.01)

            # Create comprehensive comparison with all three prices
            if expected_df is not None and not expected_df.empty:
                job["message"] = "Creating comprehensive price comparison..."
                job["progress"] = 88
                all_prices_results = compare_all_prices(expected_df, actual_prices, tolerance=0.01)

        job["message"] = "Saving results..."
        job["progress"] = 90

        # Save results
        output_path = save_results(
            results,
            config.output_dir,
            menu_vs_cart_results=menu_vs_cart_results,
            all_prices_results=all_prices_results,
        )

        # Build summary message
        summary_parts = [results['summary']]
        if all_prices_results:
            summary_parts.append(all_prices_results['summary'])
        elif menu_vs_cart_results:
            summary_parts.append(menu_vs_cart_results['summary'])

        job["status"] = "completed"
        job["message"] = f"Complete! {' | '.join(summary_parts)}"
        job["progress"] = 100
        job["result_file"] = str(output_path)

    except Exception as e:
        import traceback
        traceback.print_exc()
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


# Master document management routes


@app.post("/upload-master")
async def upload_master(file: UploadFile = File(...)):
    """Upload and parse a master pricing document."""
    # Validate file type
    if not file.filename or not file.filename.endswith(('.xls', '.xlsx')):
        return JSONResponse(
            {"error": "File must be an Excel document (.xls or .xlsx)"},
            status_code=400
        )

    # Save the uploaded file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_filename = re.sub(r'[^\w\-_.]', '_', file.filename)
    filename = f"master_{timestamp}_{safe_filename}"
    file_path = UPLOAD_DIR / filename

    try:
        content = await file.read()
        with open(file_path, "wb") as f:
            f.write(content)

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
        save_master_info(master_info)

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
async def master_info():
    """Get info about the currently loaded master document."""
    info = get_master_info()
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
    provinces = load_cities_from_config()
    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "provinces": provinces,
        }
    )


@app.post("/admin/cities")
async def add_city(request: Request):
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

    provinces = load_cities_from_config()

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
    save_cities_to_config(provinces)

    return {"success": True, "message": f"Added {city} to {province}"}


@app.delete("/admin/cities/{province}/{city}")
async def delete_city(province: str, city: str):
    """Remove a city from a province."""
    province = province.upper()
    provinces = load_cities_from_config()

    if province not in provinces:
        return JSONResponse({"error": f"Province '{province}' not found"}, status_code=404)

    # Find and remove the city
    original_count = len(provinces[province])
    provinces[province] = [c for c in provinces[province] if c["city"] != city]

    if len(provinces[province]) == original_count:
        return JSONResponse({"error": f"City '{city}' not found in {province}"}, status_code=404)

    save_cities_to_config(provinces)
    return {"success": True, "message": f"Removed {city} from {province}"}


@app.post("/admin/provinces")
async def add_province(request: Request):
    """Add a new province."""
    form_data = await request.form()
    province = form_data.get("province", "").strip().upper()

    # Validate province code (2 letters)
    if not province or not re.match(r"^[A-Z]{2}$", province):
        return JSONResponse(
            {"error": "Province must be a 2-letter code (e.g., BC, ON)"},
            status_code=400
        )

    provinces = load_cities_from_config()

    if province in provinces:
        return JSONResponse(
            {"error": f"Province '{province}' already exists"},
            status_code=400
        )

    provinces[province] = []
    save_cities_to_config(provinces)

    return {"success": True, "message": f"Added province {province}"}


@app.delete("/admin/provinces/{province}")
async def delete_province(province: str):
    """Delete an empty province."""
    province = province.upper()
    provinces = load_cities_from_config()

    if province not in provinces:
        return JSONResponse({"error": f"Province '{province}' not found"}, status_code=404)

    if provinces[province]:
        return JSONResponse(
            {"error": f"Cannot delete province '{province}' - it still has cities. Remove all cities first."},
            status_code=400
        )

    del provinces[province]
    save_cities_to_config(provinces)

    return {"success": True, "message": f"Removed province {province}"}
