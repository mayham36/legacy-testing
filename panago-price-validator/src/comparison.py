"""Price comparison logic with bug fixes."""
from decimal import Decimal
from typing import Optional

import pandas as pd

from .models import ValidationStatus, PriceRecord


def compare_prices(
    expected_df: pd.DataFrame,
    actual_prices: list[PriceRecord],
    tolerance: float = 0.01,
) -> dict:
    """Compare expected vs actual prices and generate report.

    Performs a full outer merge between expected and actual prices,
    calculates discrepancies, and generates summary statistics.

    Args:
        expected_df: DataFrame with expected prices from Marketing.
            Must contain columns: product_name, category, province, expected_price.
        actual_prices: List of PriceRecord objects from web scraping.
        tolerance: Maximum acceptable price difference in dollars (default: $0.01).

    Returns:
        Dictionary containing:
            - summary: Human-readable summary string
            - summary_df: DataFrame with summary statistics
            - details_df: Full merged DataFrame with all products
            - discrepancies_df: DataFrame with non-passing items only
    """
    # Convert actual prices to DataFrame
    if actual_prices:
        actual_df = pd.DataFrame([p.to_dict() for p in actual_prices])
    else:
        actual_df = pd.DataFrame()

    # Handle empty DataFrames
    if actual_df.empty:
        return _create_empty_results("No actual prices collected")

    if expected_df.empty:
        return _create_empty_results("No expected prices provided")

    # Ensure column name consistency
    expected_df = expected_df.copy()
    expected_df.columns = expected_df.columns.str.lower().str.strip()

    # Rename actual_price for merge
    if "expected_price" in expected_df.columns:
        expected_df = expected_df.rename(columns={"expected_price": "expected_price"})

    # Merge on product_name, category, province
    merged = pd.merge(
        expected_df,
        actual_df,
        on=["product_name", "category", "province"],
        how="outer",
        suffixes=("_expected", "_actual"),
    )

    # Handle column naming from merge
    if "expected_price" not in merged.columns and "expected_price_expected" in merged.columns:
        merged["expected_price"] = merged["expected_price_expected"]
    if "actual_price" not in merged.columns and "actual_price_actual" in merged.columns:
        merged["actual_price"] = merged["actual_price_actual"]

    # Calculate difference
    merged["price_difference"] = (
        merged["actual_price"].astype(float) - merged["expected_price"].astype(float)
    ).round(2)

    # Determine pass/fail using vectorized operation
    merged["status"] = merged.apply(
        lambda row: _determine_status(row, tolerance), axis=1
    )

    # Generate summary with division-by-zero protection
    total_products = len(merged)
    summary = {
        "total_products": total_products,
        "passed": len(merged[merged["status"] == ValidationStatus.PASS]),
        "failed": len(merged[merged["status"] == ValidationStatus.FAIL]),
        "missing_expected": len(merged[merged["status"] == ValidationStatus.MISSING_EXPECTED]),
        "missing_actual": len(merged[merged["status"] == ValidationStatus.MISSING_ACTUAL]),
    }

    # FIX: Division by zero protection
    if total_products > 0:
        summary["pass_rate"] = f"{(summary['passed'] / total_products * 100):.1f}%"
    else:
        summary["pass_rate"] = "N/A"

    summary_df = pd.DataFrame([summary])
    discrepancies_df = merged[merged["status"] != ValidationStatus.PASS].copy()

    # Clean up output columns
    output_columns = [
        "province",
        "store_name",
        "category",
        "product_name",
        "expected_price",
        "actual_price",
        "price_difference",
        "status",
    ]
    available_columns = [c for c in output_columns if c in merged.columns]
    details_df = merged[available_columns].copy()
    discrepancies_df = discrepancies_df[available_columns].copy() if not discrepancies_df.empty else pd.DataFrame(columns=available_columns)

    return {
        "summary": f"Pass: {summary['passed']}, Fail: {summary['failed']}, Rate: {summary['pass_rate']}",
        "summary_df": summary_df,
        "details_df": details_df,
        "discrepancies_df": discrepancies_df,
    }


def _determine_status(row: pd.Series, tolerance: float) -> str:
    """Determine pass/fail status for a single row.

    Args:
        row: DataFrame row containing expected_price and actual_price.
        tolerance: Maximum acceptable price difference.

    Returns:
        ValidationStatus value as string.
    """
    expected = row.get("expected_price")
    actual = row.get("actual_price")

    if pd.isna(expected):
        return ValidationStatus.MISSING_EXPECTED
    if pd.isna(actual):
        return ValidationStatus.MISSING_ACTUAL

    price_diff = row.get("price_difference")
    if price_diff is not None and abs(float(price_diff)) <= tolerance:
        return ValidationStatus.PASS

    return ValidationStatus.FAIL


def _create_empty_results(message: str) -> dict:
    """Create empty results structure when no data collected.

    Args:
        message: Summary message to include.

    Returns:
        Dictionary with empty DataFrames and summary.
    """
    output_columns = [
        "province",
        "store_name",
        "category",
        "product_name",
        "expected_price",
        "actual_price",
        "price_difference",
        "status",
    ]

    return {
        "summary": message,
        "summary_df": pd.DataFrame(
            [
                {
                    "total_products": 0,
                    "passed": 0,
                    "failed": 0,
                    "missing_expected": 0,
                    "missing_actual": 0,
                    "pass_rate": "N/A",
                }
            ]
        ),
        "details_df": pd.DataFrame(columns=output_columns),
        "discrepancies_df": pd.DataFrame(columns=output_columns),
    }


def calculate_summary_by_province(details_df: pd.DataFrame) -> pd.DataFrame:
    """Calculate summary statistics grouped by province.

    Args:
        details_df: Full details DataFrame from compare_prices.

    Returns:
        DataFrame with per-province statistics.
    """
    if details_df.empty:
        return pd.DataFrame()

    summary = details_df.groupby("province").agg(
        total_products=("product_name", "count"),
        passed=("status", lambda x: (x == ValidationStatus.PASS).sum()),
        failed=("status", lambda x: (x == ValidationStatus.FAIL).sum()),
    ).reset_index()

    # Calculate pass rate with division-by-zero protection
    summary["pass_rate"] = summary.apply(
        lambda row: f"{(row['passed'] / row['total_products'] * 100):.1f}%"
        if row["total_products"] > 0
        else "N/A",
        axis=1,
    )

    return summary
