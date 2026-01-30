---
title: Automated Pricing Validation for Panago.com
type: feat
date: 2026-01-30
deepened: 2026-01-30
---

# Automated Pricing Validation for Panago.com

## Enhancement Summary

**Deepened on:** 2026-01-30
**Research agents used:** kieran-python-reviewer, performance-oracle, security-sentinel, code-simplicity-reviewer, architecture-strategist, pattern-recognition-specialist, best-practices-researcher, framework-docs-researcher

### Key Improvements
1. **Performance optimization** - Parallel browser contexts for 80% time reduction (target: 20-30 min)
2. **Security hardening** - Excel formula sanitization, path traversal protection, YAML safe_load
3. **Architecture refinement** - Page Object Model, explicit data contracts with dataclasses
4. **Simplified option** - Single-script alternative for faster initial deployment

### Critical Issues Discovered
- Sequential processing will take 2-4 hours, not 30 minutes - parallelization required
- YAML `load()` is a critical security vulnerability - must use `safe_load()`
- Excel formula injection possible - input sanitization needed
- Division by zero bug in comparison when no products found

---

## Overview

Build a lightweight, automated testing tool that validates product pricing across all Canadian provinces on the Panago.com website. The tool will systematically navigate to each store location, iterate through all products, capture prices, and compare them against expected values from Marketing's Excel spreadsheet.

**Current State:** Manual testing requires a human to order every product for every province to validate pricing changes - a time-consuming process with 500+ combinations.

**Target State:** Automated tool that completes full pricing validation in minutes, producing a comparison report highlighting any discrepancies.

## Problem Statement

When Marketing implements pricing changes across Panago's product catalog:
1. A human tester must manually select each province/city combination
2. Navigate through every product category
3. Record prices for each item
4. Compare against the expected prices from Marketing's Excel spreadsheet
5. Report any discrepancies

This process is:
- **Time-intensive:** 500+ product/location combinations
- **Error-prone:** Manual data entry and comparison
- **Blocking:** Delays pricing rollouts and validation cycles
- **Repetitive:** Same process every pricing change

## Proposed Solution

A Python-based automation tool using **Playwright** for browser automation that:

1. Reads expected prices from Marketing's Excel spreadsheet
2. Automates browser navigation on panago.com (React app embedded in WordPress)
3. Systematically selects store locations via address autocomplete
4. Iterates through all product categories and items
5. Captures displayed prices
6. Exports results to Excel with comparison against expected values
7. Generates a pass/fail report highlighting discrepancies

### Why Playwright?

Based on 2026 best practices research:

| Tool | Pros | Cons | Verdict |
|------|------|------|---------|
| **Playwright** | Modern, fast, auto-waits, cross-browser, excellent for SPAs/React | Newer ecosystem | **Best choice** |
| Selenium | Mature, large community | Slower, requires explicit waits, more flaky | Legacy option |
| Puppeteer | Fast, Chrome-focused | Chrome-only, JavaScript only | Limited |

**Playwright advantages for this project:**
- **Auto-wait mechanism:** Eliminates flaky tests with React's dynamic rendering
- **Native Python support:** Clean integration with pandas/openpyxl for Excel handling
- **Headless mode:** Efficient server/CI execution without visible browser
- **Built-in selectors:** Handles React components and shadow DOM seamlessly
- **Free and open-source:** Apache 2.0 license, no cost

### Research Insights: Playwright Best Practices

**Selector Priority (from official Playwright docs):**
1. Role-based: `page.get_by_role("button", name="Add to Cart")`
2. Test ID: `page.get_by_test_id("price-display")`
3. Text: `page.get_by_text("$19.99")`

**Auto-waiting:** Playwright automatically waits for actionability checks before actions - no explicit waits needed in most cases.

**Browser Context Isolation:** Each `browser.new_context()` creates an isolated session (like incognito) - essential for clean state between location validations.

Sources:
- [Playwright vs Selenium 2026 Comparison](https://brightdata.com/blog/web-data/playwright-vs-selenium)
- [Browser Automation Tools Comparison](https://www.firecrawl.dev/blog/browser-automation-tools-comparison-2025)
- [BrowserStack Playwright Guide](https://www.browserstack.com/guide/playwright-web-scraping)
- [Playwright Official Python Docs](https://playwright.dev/python/docs/)

## Technical Approach

### Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Pricing Validation Tool                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────┐                           ┌────────────────────────────┐  │
│  │   Config     │◄─────────────────────────▶│    Error Collector         │  │
│  │   Loader     │                           │  • Accumulate errors       │  │
│  └──────────────┘                           │  • Threshold monitoring    │  │
│         │                                   └────────────────────────────┘  │
│         ▼                                              ▲                    │
│  ┌──────────────┐    ┌──────────────┐    ┌────────────┴───────────────┐   │
│  │   Input      │    │   Scraping   │    │      Validation            │   │
│  │   Reader     │    │   Engine     │    │      Engine                │   │
│  │              │    │              │    │                            │   │
│  │ • Excel      │───▶│ • Browser    │───▶│  • Price comparison        │   │
│  │ • Sanitize   │    │   pool       │    │  • Tolerance checking      │   │
│  │ • Validate   │    │ • Context    │    │  • Difference calc         │   │
│  │              │    │   isolation  │    │                            │   │
│  │              │    │ • Retry      │    │                            │   │
│  └──────────────┘    │   logic      │    └────────────────────────────┘   │
│         │            └──────────────┘               │                      │
│         ▼                   │                       ▼                      │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │                        Data Contracts (Dataclasses)                  │  │
│  │    LocationInput ──────▶ ScrapedPrice ──────▶ ValidationResult      │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
│                                    │                                       │
│                                    ▼                                       │
│                          ┌──────────────────┐                             │
│                          │   Output Layer   │                             │
│                          │  • Excel report  │                             │
│                          │  • Screenshots   │                             │
│                          └──────────────────┘                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Technology Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| Browser Automation | Playwright (Python) | Navigate site, interact with React components |
| Excel Reading | openpyxl / pandas | Load expected prices from Marketing spreadsheet |
| Excel Writing | pandas + xlsxwriter | Export results (xlsxwriter is faster for large files) |
| Data Processing | pandas | DataFrames for price comparison logic |
| Configuration | YAML (with safe_load) | Store locations, test parameters |
| Logging | Python structlog | Structured logging for debugging |
| Retry Logic | tenacity | Exponential backoff for transient failures |

### Research Insights: Pandas Excel Performance

From Context7 pandas documentation:
- **calamine engine** is 5x faster than openpyxl for reading
- **xlsxwriter** is faster than openpyxl for writing large files
- Use `usecols` parameter to only read needed columns
- Specify `dtype` to avoid inference overhead

### File Structure Options

#### Option A: Full Package Structure (Recommended for team maintenance)

```
panago-price-validator/
├── config/
│   ├── locations.yaml        # Province/city test addresses
│   └── settings.yaml         # Timeouts, selectors, options
├── input/
│   └── expected_prices.xlsx  # Marketing's pricing spreadsheet
├── output/
│   └── results_YYYYMMDD_HHMMSS.xlsx
├── src/
│   ├── __init__.py
│   ├── main.py               # Entry point
│   ├── models.py             # Dataclasses for type safety
│   ├── excel_handler.py      # Read/write Excel files (with security)
│   ├── browser_automation.py # Playwright automation
│   ├── pages/                # Page Object Model
│   │   ├── __init__.py
│   │   ├── base_page.py
│   │   └── menu_page.py
│   └── comparison.py         # Compare expected vs actual
├── tests/
│   └── test_scraper.py       # Unit tests
├── requirements.txt
└── README.md
```

#### Option B: Single-Script (For quick deployment)

```
panago-price-validator/
├── validate_prices.py      # Single script - ALL logic here
├── expected_prices.xlsx    # Input (same directory)
├── requirements.txt        # Keep minimal
└── README.md              # Brief usage docs
```

### Research Insights: Simplification Analysis

From code-simplicity-reviewer:
- Single script approach reduces 14 files to 4
- ~80% less code for same functionality
- Best for: single maintainer, quick validation needs
- Trade-off: harder to test, extend, or hand off

**Recommendation:** Start with Option B (single script), refactor to Option A when the script exceeds ~300 lines or multiple people need to maintain it.

### Implementation Phases

#### Phase 1: Foundation Setup

**Tasks:**
- [x] Initialize Python project with virtual environment
- [x] Install dependencies: `playwright`, `pandas`, `openpyxl`, `pyyaml`, `tenacity`
- [ ] Run `playwright install chromium` to download browser binary
- [x] Create project directory structure
- [x] Set up structured logging configuration

**Key Files:**

`requirements.txt`
```
playwright>=1.40.0
pandas>=2.0.0
openpyxl>=3.1.0
xlsxwriter>=3.1.0
pyyaml>=6.0
tenacity>=8.0
structlog>=23.0
```

`src/models.py` (NEW - Type Safety)
```python
"""Data contracts for type safety and documentation."""
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Optional
from pathlib import Path


class ValidationStatus(StrEnum):
    """Status values for price validation."""
    PASS = "PASS"
    FAIL = "FAIL"
    MISSING_EXPECTED = "MISSING_EXPECTED"
    MISSING_ACTUAL = "MISSING_ACTUAL"


@dataclass(frozen=True)
class LocationConfig:
    """Configuration for a store location."""
    store_name: str
    address: str
    province: str


@dataclass(frozen=True)
class AutomationConfig:
    """Configuration for the automation run."""
    input_file: Path
    output_dir: Path
    timeout_ms: int = 30000
    headless: bool = True
    max_concurrent: int = 5
    retry_attempts: int = 3
    base_delay_ms: int = 1000


@dataclass(frozen=True)
class PriceRecord:
    """A single scraped price record."""
    province: str
    store_name: str
    category: str
    product_name: str
    actual_price: Decimal
    raw_price_text: str
    scraped_at: datetime = field(default_factory=datetime.now)


@dataclass
class ValidationResult:
    """Result of comparing expected vs actual price."""
    province: str
    store_name: str
    category: str
    product_name: str
    expected_price: Optional[Decimal]
    actual_price: Optional[Decimal]
    status: ValidationStatus
    price_difference: Optional[Decimal] = None

    def __post_init__(self):
        if self.expected_price and self.actual_price:
            self.price_difference = self.actual_price - self.expected_price
```

`src/main.py` (Enhanced with error handling)
```python
"""Panago Pricing Validation Tool - Main Entry Point."""
import argparse
import logging
import sys
from pathlib import Path

import structlog

from models import AutomationConfig
from excel_handler import load_expected_prices, save_results
from browser_automation import PanagoAutomation
from comparison import compare_prices

structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
)
logger = structlog.get_logger()


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Panago Pricing Validation Tool'
    )
    parser.add_argument(
        '--input', '-i',
        required=True,
        help='Path to expected prices Excel file'
    )
    parser.add_argument(
        '--output', '-o',
        default='./output',
        help='Output directory for results'
    )
    parser.add_argument(
        '--headless',
        action='store_true',
        default=True,
        help='Run browser in headless mode'
    )
    parser.add_argument(
        '--visible',
        action='store_true',
        help='Run browser with visible window (for debugging)'
    )
    parser.add_argument(
        '--province',
        help='Test single province only (e.g., BC, AB, ON)'
    )
    parser.add_argument(
        '--max-concurrent',
        type=int,
        default=5,
        help='Maximum concurrent browser contexts'
    )
    return parser.parse_args()


def main() -> int:
    """Run the pricing validation workflow."""
    args = parse_args()

    config = AutomationConfig(
        input_file=Path(args.input),
        output_dir=Path(args.output),
        headless=not args.visible,
        max_concurrent=args.max_concurrent,
    )

    try:
        logger.info("starting_validation", input_file=str(config.input_file))

        expected_prices = load_expected_prices(config.input_file)
        logger.info("loaded_expected_prices", count=len(expected_prices))

        automation = PanagoAutomation(config)
        actual_prices = automation.run_price_collection()
        logger.info("collected_actual_prices", count=len(actual_prices))

        results = compare_prices(expected_prices, actual_prices)
        output_path = save_results(results, config.output_dir)

        logger.info(
            "validation_complete",
            summary=results['summary'],
            output_file=str(output_path)
        )

        # Return non-zero exit code if failures found
        return 0 if results['discrepancies_df'].empty else 1

    except FileNotFoundError as e:
        logger.error("file_not_found", error=str(e))
        return 2
    except ValueError as e:
        logger.error("validation_error", error=str(e))
        return 3
    except Exception as e:
        logger.exception("unexpected_error", error=str(e))
        return 4


if __name__ == "__main__":
    sys.exit(main())
```

#### Phase 2: Configuration & Input Handling (Security Hardened)

**Tasks:**
- [x] Design location configuration format (addresses by province)
- [x] Build Excel reader with formula injection protection
- [x] Create mapping between spreadsheet format and internal data model
- [x] Validate input data structure and completeness
- [x] Implement path traversal protection

**Key Files:**

`config/locations.yaml`
```yaml
# Test addresses for each province - one per province minimum
provinces:
  BC:
    - address: "1234 Main Street, Vancouver, BC V5K 0A1"
      store_name: "Vancouver Downtown"
  AB:
    - address: "5678 Centre Street, Calgary, AB T2E 2R8"
      store_name: "Calgary Centre"
  ON:
    - address: "910 Queen Street, Toronto, ON M4M 1J5"
      store_name: "Toronto East"
  # ... additional provinces

# Product categories to validate
categories:
  - pizzas
  - salads
  - sides
  - dips
  - desserts
  - beverages
```

`src/excel_handler.py` (Security Hardened)
```python
"""Excel file handling with security hardening."""
import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd


# Security: Valid province codes whitelist
VALID_PROVINCES = {'BC', 'AB', 'SK', 'MB', 'ON', 'QC', 'NB', 'NS', 'PE', 'NL', 'YT', 'NT', 'NU'}


def sanitize_cell_value(value: Any) -> Any:
    """Sanitize cell values to prevent formula injection."""
    if isinstance(value, str):
        # Detect formula injection patterns
        dangerous_prefixes = ('=', '+', '-', '@', '\t', '\r', '\n')
        if value.startswith(dangerous_prefixes):
            # Prefix with single quote to neutralize formula
            return f"'{value}"

        # Check for DDE/external command patterns
        dde_patterns = [
            r'=\s*CMD\s*\|',
            r'=\s*EXEC\s*\(',
            r'=\s*HYPERLINK\s*\(',
            r'=\s*WEBSERVICE\s*\(',
        ]
        for pattern in dde_patterns:
            if re.search(pattern, value, re.IGNORECASE):
                raise ValueError(f"Potentially malicious formula detected: {value[:50]}...")
    return value


def load_expected_prices(filepath: Path) -> pd.DataFrame:
    """Load Marketing's expected prices spreadsheet with security hardening."""
    # Validate file exists
    if not filepath.exists():
        raise FileNotFoundError(f"Excel file not found: {filepath}")

    # Check file size to prevent DoS via large files
    max_size_mb = 50
    file_size_mb = filepath.stat().st_size / (1024 * 1024)
    if file_size_mb > max_size_mb:
        raise ValueError(f"File exceeds maximum size of {max_size_mb}MB: {file_size_mb:.2f}MB")

    # Load with specific columns and dtypes for performance
    df = pd.read_excel(
        filepath,
        engine='openpyxl',
        usecols=['product_name', 'category', 'province', 'expected_price'],
        dtype={
            'product_name': 'str',
            'category': 'str',
            'province': 'str',
            'expected_price': 'float64'
        }
    )

    # Normalize column names
    df.columns = df.columns.str.lower().str.strip()

    # Validate required columns exist
    required = ['product_name', 'category', 'province', 'expected_price']
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    # Sanitize all string values
    for col in df.select_dtypes(include=['object']).columns:
        df[col] = df[col].apply(sanitize_cell_value)

    # Validate province codes
    df['province'] = df['province'].str.upper().str.strip()
    invalid_provinces = set(df['province'].unique()) - VALID_PROVINCES
    if invalid_provinces:
        raise ValueError(f"Invalid province codes: {invalid_provinces}")

    # Validate prices are positive
    if (df['expected_price'] < 0).any():
        raise ValueError("expected_price cannot contain negative values")

    return df


def save_results(results: dict, output_dir: Path) -> Path:
    """Save comparison results to Excel with security controls."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / f"results_{timestamp}.xlsx"

    # Use xlsxwriter for faster writing of large files
    with pd.ExcelWriter(output_path, engine='xlsxwriter') as writer:
        # Summary sheet
        results['summary_df'].to_excel(writer, sheet_name='Summary', index=False)
        # Detailed results
        results['details_df'].to_excel(writer, sheet_name='Details', index=False)
        # Discrepancies only
        results['discrepancies_df'].to_excel(writer, sheet_name='Discrepancies', index=False)

    return output_path
```

`src/config_loader.py` (Security Hardened)
```python
"""Configuration loading with YAML security."""
from pathlib import Path
from typing import Any

import yaml


def load_config_secure(config_path: Path) -> dict[str, Any]:
    """Load YAML configuration with security hardening.

    CRITICAL: Uses safe_load() to prevent code execution attacks.
    """
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with open(config_path, 'r', encoding='utf-8') as f:
        # CRITICAL: Use safe_load() - never yaml.load()
        config = yaml.safe_load(f)

    if not isinstance(config, dict):
        raise ValueError("Configuration must be a dictionary")

    return config
```

#### Phase 3: Browser Automation Core (Performance Optimized)

**Tasks:**
- [x] Implement Playwright browser context setup with parallel execution
- [x] Build address autocomplete interaction using Page Object Model
- [x] Handle React component rendering waits
- [x] Navigate through product categories
- [x] Extract product names and prices from DOM
- [x] Add resource blocking for faster page loads
- [x] Implement retry logic with exponential backoff

### Research Insights: Performance Optimization

From performance-oracle analysis:

| Approach | Estimated Time (500 locations) | Memory |
|----------|-------------------------------|--------|
| Sequential (current) | 2-4 hours | Low |
| Parallel (5 contexts) | 40-50 min | Medium |
| Parallel (8 contexts) | 20-30 min | Higher |

**Critical optimizations:**
1. **Parallel browser contexts** - 80% time reduction
2. **Resource blocking** (images, fonts, analytics) - 40-60% faster page loads
3. **Index expected prices DataFrame** - O(1) lookups instead of O(n)

**Key Files:**

`src/pages/base_page.py` (Page Object Model)
```python
"""Base page object for Playwright automation."""
from abc import ABC, abstractmethod
from playwright.sync_api import Page, Locator


class BasePage(ABC):
    """Base class for all page objects."""

    def __init__(self, page: Page):
        self._page = page

    def wait_for_load(self, timeout: int = 30000) -> None:
        """Wait for page to be ready."""
        self._page.wait_for_load_state("networkidle", timeout=timeout)

    @property
    @abstractmethod
    def url_pattern(self) -> str:
        """Regex pattern to validate current URL."""
        pass
```

`src/pages/menu_page.py` (Page Object Model)
```python
"""Page object for Panago menu page."""
from decimal import Decimal
import re
from typing import Optional

from playwright.sync_api import Page

from .base_page import BasePage


class PanagoMenuPage(BasePage):
    """Page object for Panago store menu page."""

    # Centralized selectors - update these based on actual DOM inspection
    SELECTORS = {
        'location_selector': '[data-testid="location-selector"]',
        'address_input': 'input[placeholder*="address"]',
        'autocomplete_suggestion': '.autocomplete-suggestion',
        'product_card': '[data-testid="product-card"]',
        'product_name': '[data-testid="product-name"]',
        'product_price': '[data-testid="product-price"]',
        'category_tab': '[data-category="{category}"]',
        'loading_spinner': '.loading-spinner',
    }

    @property
    def url_pattern(self) -> str:
        return r"https://www\.panago\.com.*"

    def select_location(self, address: str, timeout: int = 30000) -> None:
        """Select store via address autocomplete."""
        # Open location selector
        self._page.click(self.SELECTORS['location_selector'])

        # Type address
        address_input = self._page.locator(self.SELECTORS['address_input'])
        address_input.fill(address)

        # Wait for and select first suggestion
        self._page.wait_for_selector(
            self.SELECTORS['autocomplete_suggestion'],
            timeout=timeout
        )
        self._page.click(f"{self.SELECTORS['autocomplete_suggestion']} >> nth=0")

        # Wait for menu to load
        self.wait_for_load()

    def navigate_to_category(self, category: str) -> None:
        """Navigate to a product category."""
        selector = self.SELECTORS['category_tab'].format(category=category)
        self._page.click(selector)

        # Wait for products to load
        loading = self._page.locator(self.SELECTORS['loading_spinner'])
        loading.wait_for(state="hidden", timeout=10000)

    def get_all_products(self) -> list[dict]:
        """Extract all products and prices from current category."""
        products = []
        cards = self._page.locator(self.SELECTORS['product_card']).all()

        for card in cards:
            name = card.locator(self.SELECTORS['product_name']).text_content()
            price_text = card.locator(self.SELECTORS['product_price']).text_content()

            products.append({
                'name': name.strip() if name else '',
                'price': self._parse_price(price_text),
                'raw_price_text': price_text,
            })

        return products

    def _parse_price(self, price_text: Optional[str]) -> Optional[Decimal]:
        """Parse price string to Decimal."""
        if not price_text:
            return None

        # Handle formats: $19.99, $1,299.99
        cleaned = price_text.replace(',', '')
        match = re.search(r'\$?(\d+\.?\d*)', cleaned)
        if match:
            return Decimal(match.group(1))
        return None
```

`src/browser_automation.py` (Performance Optimized)
```python
"""Playwright browser automation with parallel execution."""
import asyncio
import re
from datetime import datetime
from typing import Optional

import structlog
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from tenacity import retry, stop_after_attempt, wait_exponential

from models import AutomationConfig, PriceRecord, LocationConfig

logger = structlog.get_logger()


class PanagoAutomation:
    """High-performance pricing validation with parallel processing."""

    # Resource types to block for faster page loads
    BLOCKED_RESOURCES = [
        '**/*.png', '**/*.jpg', '**/*.jpeg', '**/*.gif', '**/*.webp',
        '**/*.woff', '**/*.woff2', '**/*.ttf',
        '**/analytics*', '**/tracking*', '**/google-analytics*',
    ]

    def __init__(self, config: AutomationConfig):
        self.config = config
        self.base_url = "https://www.panago.com"
        self._semaphore: Optional[asyncio.Semaphore] = None

    def run_price_collection(self) -> list[PriceRecord]:
        """Synchronous entry point - runs async collection."""
        return asyncio.run(self._run_async())

    async def _run_async(self) -> list[PriceRecord]:
        """Async implementation with parallel browser contexts."""
        self._semaphore = asyncio.Semaphore(self.config.max_concurrent)
        all_prices = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=self.config.headless,
                args=[
                    '--disable-gpu',
                    '--disable-dev-shm-usage',
                    '--no-sandbox',
                ]
            )

            # Load locations from config
            locations = self._load_locations()

            # Process all locations in parallel (bounded by semaphore)
            tasks = [
                self._validate_location(browser, loc)
                for loc in locations
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Collect successful results
            for result in results:
                if isinstance(result, list):
                    all_prices.extend(result)
                elif isinstance(result, Exception):
                    logger.error("location_failed", error=str(result))

            await browser.close()

        return all_prices

    async def _validate_location(
        self, browser: Browser, location: LocationConfig
    ) -> list[PriceRecord]:
        """Validate prices for a single location with concurrency control."""
        async with self._semaphore:
            context = await self._create_optimized_context(browser)

            try:
                page = await context.new_page()
                return await self._collect_prices(page, location)
            finally:
                await context.close()

    async def _create_optimized_context(self, browser: Browser) -> BrowserContext:
        """Create browser context with resource blocking."""
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 720},
            locale='en-CA',
            service_workers='block',  # Required for route interception
        )

        # Block unnecessary resources for faster loading
        for pattern in self.BLOCKED_RESOURCES:
            await context.route(pattern, lambda route: route.abort())

        return context

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True
    )
    async def _collect_prices(
        self, page: Page, location: LocationConfig
    ) -> list[PriceRecord]:
        """Collect all product prices for a single location with retry."""
        logger.info("collecting_prices", store=location.store_name, province=location.province)

        await page.goto(self.base_url, wait_until='domcontentloaded')

        # Select location
        await self._select_location(page, location.address)

        # Collect prices from all categories
        prices = []
        categories = ['pizzas', 'salads', 'sides', 'dips', 'desserts', 'beverages']

        for category in categories:
            category_prices = await self._scrape_category(
                page, category, location
            )
            prices.extend(category_prices)

        logger.info(
            "collected_location",
            store=location.store_name,
            price_count=len(prices)
        )
        return prices

    async def _select_location(self, page: Page, address: str) -> None:
        """Handle address autocomplete location selection."""
        await page.click('[data-testid="location-selector"]')

        address_input = page.locator('input[placeholder*="address"]')
        await address_input.fill(address)

        await page.wait_for_selector(
            '.autocomplete-suggestion',
            timeout=self.config.timeout_ms
        )
        await page.click('.autocomplete-suggestion >> nth=0')

        await page.wait_for_load_state('networkidle')

    async def _scrape_category(
        self, page: Page, category: str, location: LocationConfig
    ) -> list[PriceRecord]:
        """Scrape all products and prices from a category."""
        await page.click(f'[data-category="{category}"]')
        await page.wait_for_load_state('networkidle')

        products = page.locator('[data-testid="product-card"]')
        count = await products.count()

        prices = []
        for i in range(count):
            product = products.nth(i)
            try:
                name = await product.locator('[data-testid="product-name"]').text_content()
                price_text = await product.locator('[data-testid="product-price"]').text_content()

                prices.append(PriceRecord(
                    province=location.province,
                    store_name=location.store_name,
                    category=category,
                    product_name=name.strip() if name else '',
                    actual_price=self._parse_price(price_text),
                    raw_price_text=price_text or '',
                ))
            except Exception as e:
                logger.warning("product_extraction_failed", error=str(e))

        return prices

    def _parse_price(self, price_text: Optional[str]) -> Decimal:
        """Parse price string to Decimal."""
        if not price_text:
            return Decimal('0')

        cleaned = price_text.replace(',', '')
        match = re.search(r'\$?(\d+\.?\d*)', cleaned)
        if match:
            return Decimal(match.group(1))
        raise ValueError(f"Could not parse price: {price_text}")

    def _load_locations(self) -> list[LocationConfig]:
        """Load location configurations."""
        # In real implementation, load from YAML config
        # For now, return placeholder
        return []
```

#### Phase 4: Price Comparison & Reporting (Bug Fixed)

**Tasks:**
- [x] Build comparison logic (expected vs actual prices)
- [x] Define tolerance threshold for price matching (e.g., ±$0.01)
- [x] Generate summary statistics (pass/fail counts, discrepancy rates)
- [x] Fix division by zero bug when no products found
- [x] Create formatted Excel output

**Key Files:**

`src/comparison.py` (Bug Fixed)
```python
"""Price comparison logic with bug fixes."""
from decimal import Decimal
from typing import Optional

import pandas as pd

from models import ValidationStatus


def compare_prices(
    expected_df: pd.DataFrame,
    actual_prices: list[dict],
    tolerance: float = 0.01
) -> dict:
    """Compare expected vs actual prices and generate report.

    Args:
        expected_df: DataFrame with expected prices from Marketing.
        actual_prices: List of price dictionaries from web scraping.
        tolerance: Maximum acceptable price difference in dollars (default: $0.01).

    Returns:
        Dictionary containing summary and detail DataFrames.
    """
    # Convert actual prices to DataFrame
    actual_df = pd.DataFrame(actual_prices)

    # Handle empty DataFrames
    if actual_df.empty:
        return _create_empty_results()

    # Merge on product_name, category, province
    merged = pd.merge(
        expected_df,
        actual_df,
        on=['product_name', 'category', 'province'],
        how='outer',
        suffixes=('_expected', '_actual')
    )

    # Calculate difference
    merged['price_difference'] = (
        merged['actual_price'] - merged['expected_price']
    ).round(2)

    # Determine pass/fail using vectorized operation
    merged['status'] = merged.apply(
        lambda row: _determine_status(row, tolerance), axis=1
    )

    # Generate summary with division-by-zero protection
    total_products = len(merged)
    summary = {
        'total_products': total_products,
        'passed': len(merged[merged['status'] == ValidationStatus.PASS]),
        'failed': len(merged[merged['status'] == ValidationStatus.FAIL]),
        'missing_expected': len(merged[merged['status'] == ValidationStatus.MISSING_EXPECTED]),
        'missing_actual': len(merged[merged['status'] == ValidationStatus.MISSING_ACTUAL]),
    }

    # FIX: Division by zero protection
    if total_products > 0:
        summary['pass_rate'] = f"{(summary['passed'] / total_products * 100):.1f}%"
    else:
        summary['pass_rate'] = "N/A"

    summary_df = pd.DataFrame([summary])
    discrepancies_df = merged[merged['status'] != ValidationStatus.PASS].copy()

    return {
        'summary': f"Pass: {summary['passed']}, Fail: {summary['failed']}, Rate: {summary['pass_rate']}",
        'summary_df': summary_df,
        'details_df': merged,
        'discrepancies_df': discrepancies_df
    }


def _determine_status(row: pd.Series, tolerance: float) -> ValidationStatus:
    """Determine pass/fail status for a single row."""
    expected = row.get('expected_price')
    actual = row.get('actual_price')

    if pd.isna(expected):
        return ValidationStatus.MISSING_EXPECTED
    if pd.isna(actual):
        return ValidationStatus.MISSING_ACTUAL

    price_diff = row.get('price_difference')
    if price_diff is not None and abs(price_diff) <= tolerance:
        return ValidationStatus.PASS
    return ValidationStatus.FAIL


def _create_empty_results() -> dict:
    """Create empty results structure when no data collected."""
    return {
        'summary': "No data collected",
        'summary_df': pd.DataFrame([{
            'total_products': 0,
            'passed': 0,
            'failed': 0,
            'missing_expected': 0,
            'missing_actual': 0,
            'pass_rate': 'N/A'
        }]),
        'details_df': pd.DataFrame(),
        'discrepancies_df': pd.DataFrame()
    }
```

#### Phase 5: Polish & Optimization

**Tasks:**
- [x] Add progress reporting during execution
- [x] Create comprehensive error logging with screenshots on failure
- [x] Write user documentation (README)
- [x] Add command-line arguments for flexibility
- [x] Implement rate limiting to avoid detection

### Research Insights: Anti-Bot Detection Avoidance

From best-practices-researcher:

**Legitimate testing strategies:**
1. Add random delays (2-5s with jitter) between requests
2. Rotate realistic viewport sizes
3. Use realistic user agent strings
4. Run in headed mode if site has strong protection
5. Identify your tool in headers for transparency

```python
# Rate limiting helper
import random
import asyncio

async def wait_with_jitter(min_ms: int = 2000, max_ms: int = 5000):
    """Wait with random jitter to appear human-like."""
    delay = random.uniform(min_ms, max_ms) / 1000
    await asyncio.sleep(delay)
```

## Acceptance Criteria

### Functional Requirements
- [ ] Tool reads expected prices from Marketing Excel spreadsheet
- [ ] Tool navigates to panago.com and handles React app loading
- [ ] Tool selects store locations via address autocomplete for all provinces
- [ ] Tool iterates through all product categories (pizzas, salads, sides, dips, desserts, beverages)
- [ ] Tool captures product names and prices accurately
- [ ] Tool exports results to Excel spreadsheet with:
  - Summary sheet (pass/fail counts, pass rate)
  - Details sheet (all products with expected vs actual)
  - Discrepancies sheet (failures only)
- [ ] Tool handles network errors gracefully with retry logic
- [ ] Tool can run headless (no visible browser) for automation

### Non-Functional Requirements
- [ ] Completes full validation (500+ combinations) in under 30 minutes
- [ ] Works on Windows, macOS, and Linux
- [ ] Requires only Python 3.9+ and pip (no paid tools)
- [ ] Clear error messages when failures occur
- [ ] Progress indication during execution

### Quality Gates
- [ ] All selectors documented and configurable
- [ ] README with setup instructions and usage examples
- [ ] Sample configuration files provided
- [ ] Manual verification of 10 random price captures for accuracy
- [ ] Security: YAML loaded with safe_load only
- [ ] Security: Excel inputs sanitized for formula injection

## Success Metrics

| Metric | Target |
|--------|--------|
| Manual testing time saved | 90%+ reduction |
| Price capture accuracy | 99%+ correct |
| Full suite execution time | < 30 minutes |
| False positive rate | < 1% |

## Dependencies & Prerequisites

### Required
- Python 3.9 or higher
- Internet access to panago.com
- Marketing's expected prices Excel file with columns: product_name, category, province, expected_price

### Technical Dependencies
- playwright >= 1.40.0 (browser automation)
- pandas >= 2.0.0 (data manipulation)
- openpyxl >= 3.1.0 (Excel read)
- xlsxwriter >= 3.1.0 (Excel write - faster for large files)
- pyyaml >= 6.0 (configuration files)
- tenacity >= 8.0 (retry logic)
- structlog >= 23.0 (structured logging)

### Knowledge Requirements
- Understanding of DOM selectors (will need to inspect panago.com to find actual selectors)
- Basic familiarity with running Python scripts

## Risk Analysis & Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Website DOM structure changes | High | Medium | Make selectors configurable; document selector locations |
| Anti-bot detection | Medium | Low | Use realistic delays; run in headed mode if needed |
| Address autocomplete API changes | High | Low | Abstract location selection into separate module |
| Network timeouts | Low | Medium | Implement retry logic with exponential backoff |
| Excel format changes | Medium | Medium | Validate input columns; provide clear error messages |
| **YAML code injection** | **Critical** | Low | **Use yaml.safe_load() only** |
| **Excel formula injection** | Medium | Low | Sanitize cell values on read |
| **Path traversal** | High | Low | Validate all file paths |

## Security Checklist

From security-sentinel review:

- [ ] YAML loaded with `yaml.safe_load()` only (never `yaml.load()`)
- [ ] Excel inputs sanitized for formula injection (=, +, -, @ prefixes)
- [ ] File paths validated against allowed directories
- [ ] Output files created with restrictive permissions
- [ ] No hardcoded credentials (use environment variables if needed)
- [ ] Sensitive data masked in logs

## Future Considerations

1. **CI/CD Integration:** Run as scheduled job after pricing updates
2. **Slack/Email Notifications:** Alert on test completion or failures
3. **Historical Tracking:** Store results over time to track pricing trends
4. **Visual Regression:** Screenshot products to catch display issues
5. **Multiple Size Validation:** Extend to validate small/medium/large pricing tiers

## References & Research

### Tool Selection
- [Playwright vs Selenium 2026 Comparison (BrightData)](https://brightdata.com/blog/web-data/playwright-vs-selenium)
- [Browser Automation Tools Comparison (Firecrawl)](https://www.firecrawl.dev/blog/browser-automation-tools-comparison-2025)
- [Playwright Web Scraping Guide (BrowserStack)](https://www.browserstack.com/guide/playwright-web-scraping)
- [Best Open-Source Web Scraping Libraries 2026](https://www.firecrawl.dev/blog/best-open-source-web-scraping-libraries)

### Implementation Guides
- [Web Scraping with Playwright and Python (Medium)](https://medium.com/@hasdata/how-to-scrape-websites-with-playwright-and-python-49a015fd00aa)
- [Geolocation Testing in Playwright](https://timdeschryver.dev/blog/using-geolocation-in-playwright-tests)
- [openpyxl Tutorial (DataCamp)](https://www.datacamp.com/tutorial/openpyxl)
- [Playwright Official Python Documentation](https://playwright.dev/python/docs/)
- [Pandas Excel I/O Documentation](https://pandas.pydata.org/docs/user_guide/io.html)

### Best Practices
- [Website QA Testing Guide 2026 (BugHerd)](https://bugherd.com/blog/website-qa-testing-complete-guide-to-quality-assurance)
- [E-commerce Testing Guide (Shopify)](https://www.shopify.com/il/blog/ecommerce-testing)
- [Software Testing Best Practices 2026 (N-iX)](https://www.n-ix.com/software-testing-best-practices/)
- [ZenRows - Anti-Bot Detection Avoidance](https://www.zenrows.com/blog/bypass-bot-detection)

## Important Implementation Notes

### Selector Discovery Required

The DOM selectors in this plan (e.g., `[data-testid="location-selector"]`, `.product-item`) are **placeholders**. Before implementation, you must:

1. Open panago.com in Chrome DevTools
2. Inspect the location selector modal/popup
3. Inspect product listing elements
4. Document actual selectors in `config/settings.yaml`

**Selector Priority (from Playwright docs):**
1. `page.get_by_role()` - Most resilient
2. `page.get_by_test_id()` - Good if data-testid exists
3. `page.get_by_text()` - For stable text content
4. CSS selectors - Last resort

### React App Considerations

Since panago.com uses a React app embedded in WordPress:
- Wait for `networkidle` state after navigation
- Use Playwright's auto-wait for elements
- Consider React-specific selectors if data-testid attributes exist
- Handle potential loading spinners/skeletons
- Block service workers for reliable route interception

### Excel Input Format

Marketing's spreadsheet must include these columns (case-insensitive):
- `product_name` - Exact name as displayed on website
- `category` - pizzas, salads, sides, dips, desserts, beverages
- `province` - Two-letter code (BC, AB, ON, etc.)
- `expected_price` - Numeric value (e.g., 14.99)

### Performance Targets

| Configuration | Est. Time | Memory | Use Case |
|--------------|-----------|--------|----------|
| Sequential | 2-4 hours | Low | Debugging |
| 5 concurrent | 40-50 min | ~500MB | Standard |
| 8 concurrent | 20-30 min | ~800MB | Fast validation |
