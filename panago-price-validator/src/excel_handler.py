"""Excel file handling with security hardening."""
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


# Security: Valid province codes whitelist
VALID_PROVINCES = {
    "BC", "AB", "SK", "MB", "ON", "QC", "NB", "NS", "PE", "NL", "YT", "NT", "NU"
}

# Maximum file size in MB to prevent DoS
MAX_FILE_SIZE_MB = 50


def sanitize_cell_value(value: Any) -> Any:
    """Sanitize cell values to prevent formula injection.

    Excel formulas can execute commands when prefixed with certain characters.
    This function neutralizes potentially dangerous values.

    Args:
        value: Cell value to sanitize.

    Returns:
        Sanitized value, or original if safe.

    Raises:
        ValueError: If malicious DDE pattern detected.
    """
    if isinstance(value, str):
        # Check for DDE/external command patterns FIRST (these are malicious)
        dde_patterns = [
            r"=\s*CMD\s*\|",
            r"=\s*EXEC\s*\(",
            r"=\s*HYPERLINK\s*\(",
            r"=\s*WEBSERVICE\s*\(",
        ]
        for pattern in dde_patterns:
            if re.search(pattern, value, re.IGNORECASE):
                raise ValueError(
                    f"Potentially malicious formula detected: {value[:50]}..."
                )

        # Detect formula injection patterns and neutralize
        dangerous_prefixes = ("=", "+", "-", "@", "\t", "\r", "\n")
        if value.startswith(dangerous_prefixes):
            # Prefix with single quote to neutralize formula
            return f"'{value}"

    return value


def load_expected_prices(filepath: Path) -> pd.DataFrame:
    """Load Marketing's expected prices spreadsheet with security hardening.

    Args:
        filepath: Path to the Excel file.

    Returns:
        DataFrame with expected prices.

    Raises:
        FileNotFoundError: If file doesn't exist.
        ValueError: If file is too large, missing columns, or contains invalid data.
    """
    # Validate file exists
    if not filepath.exists():
        raise FileNotFoundError(f"Excel file not found: {filepath}")

    # Check file size to prevent DoS via large files
    file_size_mb = filepath.stat().st_size / (1024 * 1024)
    if file_size_mb > MAX_FILE_SIZE_MB:
        raise ValueError(
            f"File exceeds maximum size of {MAX_FILE_SIZE_MB}MB: {file_size_mb:.2f}MB"
        )

    # Load with specific columns and dtypes for performance
    try:
        df = pd.read_excel(
            filepath,
            engine="openpyxl",
            usecols=["product_name", "category", "province", "expected_price"],
            dtype={
                "product_name": "str",
                "category": "str",
                "province": "str",
                "expected_price": "float64",
            },
        )
    except ValueError:
        # If specific columns don't exist, try loading all and validate
        df = pd.read_excel(filepath, engine="openpyxl")

    # Normalize column names
    df.columns = df.columns.str.lower().str.strip()

    # Validate required columns exist
    required = ["product_name", "category", "province", "expected_price"]
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    # Sanitize all string values
    for col in df.select_dtypes(include=["object", "str"]).columns:
        df[col] = df[col].apply(sanitize_cell_value)

    # Validate province codes
    df["province"] = df["province"].str.upper().str.strip()
    invalid_provinces = set(df["province"].unique()) - VALID_PROVINCES
    if invalid_provinces:
        raise ValueError(f"Invalid province codes: {invalid_provinces}")

    # Validate prices are positive
    if (df["expected_price"] < 0).any():
        raise ValueError("expected_price cannot contain negative values")

    return df


def save_results(results: dict, output_dir: Path) -> Path:
    """Save comparison results to Excel with security controls.

    Args:
        results: Dictionary containing summary_df, details_df, discrepancies_df.
        output_dir: Directory to save the output file.

    Returns:
        Path to the created output file.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / f"results_{timestamp}.xlsx"

    # Use xlsxwriter for faster writing of large files
    with pd.ExcelWriter(output_path, engine="xlsxwriter") as writer:
        workbook = writer.book

        # Create formats
        header_format = workbook.add_format(
            {"bold": True, "bg_color": "#4F81BD", "font_color": "white"}
        )
        pass_format = workbook.add_format({"bg_color": "#C6EFCE"})
        fail_format = workbook.add_format({"bg_color": "#FFC7CE"})
        currency_format = workbook.add_format({"num_format": "$#,##0.00"})

        # Summary sheet
        summary_df = results["summary_df"]
        summary_df.to_excel(writer, sheet_name="Summary", index=False)
        worksheet = writer.sheets["Summary"]
        for col_num, value in enumerate(summary_df.columns.values):
            worksheet.write(0, col_num, value, header_format)

        # Details sheet
        details_df = results["details_df"]
        details_df.to_excel(writer, sheet_name="Details", index=False)
        worksheet = writer.sheets["Details"]
        for col_num, value in enumerate(details_df.columns.values):
            worksheet.write(0, col_num, value, header_format)

        # Apply conditional formatting if status column exists
        if "status" in details_df.columns:
            status_col = details_df.columns.get_loc("status")
            worksheet.conditional_format(
                1,
                status_col,
                len(details_df) + 1,
                status_col,
                {"type": "text", "criteria": "containing", "value": "PASS", "format": pass_format},
            )
            worksheet.conditional_format(
                1,
                status_col,
                len(details_df) + 1,
                status_col,
                {"type": "text", "criteria": "containing", "value": "FAIL", "format": fail_format},
            )

        # Discrepancies sheet
        discrepancies_df = results["discrepancies_df"]
        discrepancies_df.to_excel(writer, sheet_name="Discrepancies", index=False)
        worksheet = writer.sheets["Discrepancies"]
        for col_num, value in enumerate(discrepancies_df.columns.values):
            worksheet.write(0, col_num, value, header_format)

    return output_path
