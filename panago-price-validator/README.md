# Panago Price Validator

Automated pricing validation tool for Panago.com. Compares product prices across all Canadian provinces against Marketing's expected pricing spreadsheet.

## Installation

```sh
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium
```

## Quick Start

```sh
# Run against QA environment (default, recommended)
python -m src.main -i input/expected_prices.xlsx --env qa

# Run against Production (uses extra-safe slow mode)
python -m src.main -i input/expected_prices.xlsx --env production

# Run with visible browser for debugging
python -m src.main -i input/expected_prices.xlsx --env qa --visible

# Test single province
python -m src.main -i input/expected_prices.xlsx --env qa --province BC
```

## Environment Configuration

The tool supports multiple environments with different base URLs and rate limiting:

| Environment | Base URL | Max Concurrent | Delay Range |
|-------------|----------|----------------|-------------|
| **qa** (default) | https://qa.panago.com | 3 | 2-4 seconds |
| **production** | https://www.panago.com | 1 | 5-10 seconds |

### Safe Mode (Enabled by Default)

Safe mode enforces conservative settings to minimize site impact:
- **1 browser** at a time
- **5-10 second delays** between actions
- **8 second delays** between category navigation

To disable safe mode (use with caution):
```sh
python -m src.main -i input/expected_prices.xlsx --env qa --no-safe-mode
```

### Custom Environment URLs

Edit `config/settings.yaml` to change the QA URL:
```yaml
environments:
  qa:
    base_url: "https://your-qa-site.panago.com"
```

## Input Format

Create an Excel file with these columns:

| product_name | category | province | expected_price |
|--------------|----------|----------|----------------|
| Pepperoni Classic | pizzas | BC | 14.99 |
| Garden Salad | salads | AB | 8.99 |

**Required columns:**
- `product_name` - Exact name as shown on website
- `category` - One of: pizzas, salads, sides, dips, desserts, beverages
- `province` - Two-letter code: BC, AB, SK, MB, ON, QC, NB, NS, PE, NL
- `expected_price` - Numeric value (e.g., 14.99)

## Output

Results are saved to `output/results_YYYYMMDD_HHMMSS.xlsx` with three sheets:

1. **Summary** - Pass/fail counts and pass rate
2. **Details** - All products with expected vs actual prices
3. **Discrepancies** - Only items that failed validation

## Configuration

### Locations

Edit `config/locations.yaml` to specify test addresses for each province:

```yaml
provinces:
  BC:
    - address: "1234 Main Street, Vancouver, BC V5K 0A1"
      store_name: "Vancouver Downtown"
```

### Settings

Edit `config/settings.yaml` to adjust timeouts, parallelism, and selectors.

## Command Line Options

| Option | Description | Default |
|--------|-------------|---------|
| `-i, --input` | Path to expected prices Excel file | Required |
| `-o, --output` | Output directory | ./output |
| `-e, --env` | Environment: `qa` or `production` | qa |
| `--safe-mode` | Enable conservative rate limiting | Enabled |
| `--no-safe-mode` | Disable safe mode (faster, use with caution) | - |
| `-c, --config` | Path to locations.yaml | config/locations.yaml |
| `-s, --settings` | Path to settings.yaml | config/settings.yaml |
| `--visible` | Show browser window | Hidden |
| `--province` | Test single province only | All |
| `--max-concurrent` | Parallel browser contexts | 1 (safe mode) |
| `--timeout` | Page timeout (ms) | 30000 |
| `--tolerance` | Price tolerance ($) | 0.01 |
| `-v, --verbose` | Debug logging | Off |

## Performance

| Configuration | Estimated Time | Memory |
|--------------|----------------|--------|
| Sequential (1 context) | 2-4 hours | Low |
| Default (5 contexts) | 40-50 min | ~500MB |
| Fast (8 contexts) | 20-30 min | ~800MB |

Increase `--max-concurrent` for faster validation if your system has sufficient memory.

## Selector Status

**All selectors verified (January 2026):**

| Element | Selector |
|---------|----------|
| Location trigger | `.react-state-link-choose-location` |
| City input | `.react-autosuggest__input` |
| Autocomplete suggestions | `.react-autosuggest__suggestion` |
| Save city button | `.location-choice-panel .primary.button` |
| Product cards | `ul.products > li`, `.product-group` |
| Product names | `.product-title h4`, `.product-header h4` |
| Product prices | `.product-header .price`, `.prices li span` |
| Category navigation | `ul.menu li a[href*="{category}"]` |

**Note:** The location picker uses **React Autosuggest** component with city names (e.g., "Vancouver, BC"), not full addresses.

The tool uses direct URL navigation for categories (e.g., `/menu/pizzas`) which is more reliable than clicking menu items.

## Troubleshooting

**"No locations configured"**
- Create `config/locations.yaml` with valid addresses

**"Missing required columns"**
- Ensure your Excel file has: product_name, category, province, expected_price

**Timeout errors**
- Increase `--timeout` value
- Run with `--visible` to see what's happening
- Check if site structure has changed

**Rate limiting**
- Reduce `--max-concurrent` to 3-5
- Delays between requests are automatic

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | All prices match |
| 1 | Discrepancies found |
| 2 | File not found |
| 3 | Validation error |
| 4 | Unexpected error |

## License

Internal use only.
