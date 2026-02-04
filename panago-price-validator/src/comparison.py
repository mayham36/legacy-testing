"""Price comparison logic with bug fixes."""
import re
from decimal import Decimal
from difflib import get_close_matches
from typing import Optional

import numpy as np
import pandas as pd

pd.options.mode.copy_on_write = True

from .models import ValidationStatus, PriceRecord, PriceSource


def normalize_product_name(name: str) -> str:
    """Normalize product name for comparison.

    Handles:
    - Trailing/leading whitespace
    - "NEW " prefix in master documents
    - Common beverage brand prefixes (Bubly, Organic Juice)
    - Multiple internal spaces
    - Case normalization
    - Hyphen/space normalization (e.g., "7 Up" matches "7-Up")

    Args:
        name: Raw product name.

    Returns:
        Normalized product name (lowercase, stripped).
    """
    if pd.isna(name) or name is None:
        return ""

    name = str(name).strip()
    name = " ".join(name.split())  # Normalize internal whitespace

    # Remove common prefixes (case-insensitive)
    # Order matters - check longer prefixes first
    prefixes_to_remove = [
        # Beverage brand prefixes
        "Organic Juice - ",
        "organic juice - ",
        "Bubly ",
        "bubly ",
        # Master document prefixes
        "NEW ",
        "new ",
        "New ",
    ]
    for prefix in prefixes_to_remove:
        if name.startswith(prefix):
            name = name[len(prefix):]
            break  # Only remove one prefix

    # Normalize hyphens and spaces for matching (e.g., "7 Up" vs "7-Up")
    # Replace hyphens with spaces, then normalize
    name_normalized = name.replace("-", " ")
    name_normalized = " ".join(name_normalized.split())

    return name_normalized.lower()


def find_best_match(
    product_name: str,
    candidates: list[str],
    threshold: float = 0.8,
) -> Optional[str]:
    """Find best matching product name from candidates using fuzzy matching.

    Uses difflib's get_close_matches for fuzzy string matching when exact
    match is not found.

    Args:
        product_name: Product name to match.
        candidates: List of candidate product names.
        threshold: Minimum similarity ratio (0.0 to 1.0, default 0.8).

    Returns:
        Best matching candidate name, or None if no match found.
    """
    if not product_name or not candidates:
        return None

    normalized = normalize_product_name(product_name)
    if not normalized:
        return None

    # Build mapping of normalized -> original
    normalized_candidates = {}
    for c in candidates:
        norm_c = normalize_product_name(c)
        if norm_c:
            normalized_candidates[norm_c] = c

    # Exact match first (after normalization)
    if normalized in normalized_candidates:
        return normalized_candidates[normalized]

    # Fuzzy match
    matches = get_close_matches(
        normalized, list(normalized_candidates.keys()), n=1, cutoff=threshold
    )
    if matches:
        return normalized_candidates[matches[0]]

    return None


def _apply_name_normalization(df: pd.DataFrame, column: str = "product_name") -> pd.DataFrame:
    """Apply name normalization to a DataFrame column.

    Creates a new normalized column for matching while preserving the original.

    Args:
        df: DataFrame to modify.
        column: Column name to normalize.

    Returns:
        DataFrame with added normalized column.
    """
    df = df.copy()
    if column in df.columns:
        df[f"{column}_normalized"] = df[column].apply(normalize_product_name)
    return df


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

    # Apply name normalization for better matching
    expected_df = _apply_name_normalization(expected_df, "product_name")
    actual_df = _apply_name_normalization(actual_df, "product_name")

    # Rename actual_price for merge
    if "expected_price" in expected_df.columns:
        expected_df = expected_df.rename(columns={"expected_price": "expected_price"})

    # Determine merge keys based on available columns
    # Use normalized product_name for matching
    merge_keys = ["product_name_normalized", "category"]

    # Use pricing_level if available in both, otherwise try province
    if "pricing_level" in expected_df.columns and "pricing_level" in actual_df.columns:
        merge_keys.append("pricing_level")
    elif "province" in expected_df.columns and "province" in actual_df.columns:
        merge_keys.append("province")
    # If neither matches, just merge on product_name_normalized and category

    if "size" in actual_df.columns:
        # Add size to merge keys if present (for products with size variants)
        merge_keys.append("size")
        # Ensure expected_df also has size column (may be None)
        if "size" not in expected_df.columns:
            expected_df["size"] = None

    merged = pd.merge(
        expected_df,
        actual_df,
        on=merge_keys,
        how="outer",
        suffixes=("_expected", "_actual"),
    )

    # Handle column naming from merge
    if "expected_price" not in merged.columns and "expected_price_expected" in merged.columns:
        merged["expected_price"] = merged["expected_price_expected"]
    if "actual_price" not in merged.columns and "actual_price_actual" in merged.columns:
        merged["actual_price"] = merged["actual_price_actual"]

    # Coalesce product_name from both sides (prefer expected, fall back to actual)
    if "product_name_expected" in merged.columns and "product_name_actual" in merged.columns:
        merged["product_name"] = merged["product_name_expected"].fillna(merged["product_name_actual"])
    elif "product_name_expected" in merged.columns:
        merged["product_name"] = merged["product_name_expected"]
    elif "product_name_actual" in merged.columns:
        merged["product_name"] = merged["product_name_actual"]

    # Calculate difference
    merged["price_difference"] = (
        merged["actual_price"].astype(float) - merged["expected_price"].astype(float)
    ).round(2)

    # Determine pass/fail using vectorized np.select
    conditions = [
        pd.isna(merged["expected_price"]),
        pd.isna(merged["actual_price"]),
        merged["price_difference"].abs() <= tolerance,
    ]
    choices = [
        ValidationStatus.MISSING_EXPECTED,
        ValidationStatus.MISSING_ACTUAL,
        ValidationStatus.PASS,
    ]
    merged["status"] = np.select(conditions, choices, default=ValidationStatus.FAIL)

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

    # Clean up output columns - include both province and pricing_level
    output_columns = [
        "pricing_level",
        "province",
        "store_name",
        "category",
        "product_name",
        "size",
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
        "pricing_level",
        "province",
        "store_name",
        "category",
        "product_name",
        "size",
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

    # Calculate pass rate with division-by-zero protection using vectorized operation
    summary["pass_rate"] = np.where(
        summary["total_products"] > 0,
        (summary["passed"] / summary["total_products"] * 100).round(1).astype(str) + "%",
        "N/A",
    )

    return summary


def compare_menu_vs_cart(
    prices: list[PriceRecord],
    tolerance: float = 0.01,
) -> dict:
    """Compare menu prices to cart prices for the same products.

    This function filters prices by source (menu vs cart), merges them by
    product identifier, and calculates whether the prices match within tolerance.

    Args:
        prices: List of PriceRecord objects containing both menu and cart prices.
        tolerance: Maximum acceptable price difference in dollars (default: $0.01).

    Returns:
        Dictionary containing:
            - summary: Human-readable summary string
            - comparison_df: Full merged DataFrame with menu and cart prices side by side
            - mismatches_df: DataFrame with only products where menu != cart price
    """
    if not prices:
        return _create_empty_menu_vs_cart_results("No prices to compare")

    # Convert to DataFrame
    all_df = pd.DataFrame([p.to_dict() for p in prices])

    # Split by price source
    menu_df = all_df[all_df["price_source"] == str(PriceSource.MENU)].copy()
    cart_df = all_df[all_df["price_source"] == str(PriceSource.CART)].copy()

    if menu_df.empty:
        return _create_empty_menu_vs_cart_results("No menu prices found")

    if cart_df.empty:
        return _create_empty_menu_vs_cart_results("No cart prices found")

    # Merge on product identifiers - use pricing_level if available, otherwise province
    merge_keys = ["product_name", "store_name", "category"]
    if "pricing_level" in menu_df.columns and "pricing_level" in cart_df.columns:
        merge_keys.append("pricing_level")
    if "province" in menu_df.columns and "province" in cart_df.columns:
        merge_keys.append("province")
    if "size" in menu_df.columns and "size" in cart_df.columns:
        merge_keys.append("size")

    merged = pd.merge(
        menu_df,
        cart_df,
        on=merge_keys,
        how="outer",
        suffixes=("_menu", "_cart"),
    )

    # Calculate price difference
    merged["price_difference"] = (
        merged["actual_price_cart"].astype(float) - merged["actual_price_menu"].astype(float)
    ).round(2)

    # Determine if prices match within tolerance
    merged["prices_match"] = abs(merged["price_difference"]) <= tolerance

    # Generate summary statistics
    total_compared = len(merged)
    matched = merged["prices_match"].sum()
    mismatched = total_compared - matched

    # Select output columns - include pricing_level if present
    output_columns = [
        "pricing_level",
        "province",
        "store_name",
        "category",
        "product_name",
    ]
    if "size" in merge_keys:
        output_columns.append("size")
    output_columns.extend([
        "actual_price_menu",
        "actual_price_cart",
        "price_difference",
        "prices_match",
    ])

    available_columns = [c for c in output_columns if c in merged.columns]
    comparison_df = merged[available_columns].copy()

    # Rename columns for clarity
    comparison_df = comparison_df.rename(columns={
        "actual_price_menu": "menu_price",
        "actual_price_cart": "cart_price",
    })

    mismatches_df = comparison_df[~comparison_df["prices_match"]].copy()

    return {
        "summary": f"Menu vs Cart - Matched: {matched}, Mismatched: {mismatched} of {total_compared} products",
        "comparison_df": comparison_df,
        "mismatches_df": mismatches_df,
    }


def _create_empty_menu_vs_cart_results(message: str) -> dict:
    """Create empty results structure for menu vs cart comparison.

    Args:
        message: Summary message to include.

    Returns:
        Dictionary with empty DataFrames and summary.
    """
    output_columns = [
        "pricing_level",
        "province",
        "store_name",
        "category",
        "product_name",
        "size",
        "menu_price",
        "cart_price",
        "price_difference",
        "prices_match",
    ]

    return {
        "summary": message,
        "comparison_df": pd.DataFrame(columns=output_columns),
        "mismatches_df": pd.DataFrame(columns=output_columns),
    }


def compare_all_prices(
    expected_df: pd.DataFrame,
    actual_prices: list[PriceRecord],
    tolerance: float = 0.01,
) -> dict:
    """Compare expected, menu, and cart prices in a single comprehensive view.

    Creates a unified comparison showing all three price sources side-by-side:
    - Expected price (from Marketing spreadsheet)
    - Menu price (scraped from website menu)
    - Cart price (scraped from shopping cart)

    Args:
        expected_df: DataFrame with expected prices from Marketing.
        actual_prices: List of PriceRecord objects (both menu and cart).
        tolerance: Maximum acceptable price difference in dollars.

    Returns:
        Dictionary containing:
            - summary: Human-readable summary string
            - full_comparison_df: DataFrame with all three prices side by side
            - issues_df: DataFrame with any price mismatches
    """
    if not actual_prices:
        return _create_empty_all_prices_results("No actual prices collected")

    # Split actual prices by source
    menu_prices = [p for p in actual_prices if p.price_source == PriceSource.MENU]
    cart_prices = [p for p in actual_prices if p.price_source == PriceSource.CART]

    if not menu_prices:
        return _create_empty_all_prices_results("No menu prices collected")

    # Convert to DataFrames
    menu_df = pd.DataFrame([p.to_dict() for p in menu_prices])
    menu_df = menu_df.rename(columns={"actual_price": "menu_price"})

    cart_df = None
    if cart_prices:
        cart_df = pd.DataFrame([p.to_dict() for p in cart_prices])
        cart_df = cart_df.rename(columns={"actual_price": "cart_price"})

    # Normalize expected_df
    expected_df = expected_df.copy()
    expected_df.columns = expected_df.columns.str.lower().str.strip()

    # Apply name normalization for better matching
    expected_df = _apply_name_normalization(expected_df, "product_name")
    menu_df = _apply_name_normalization(menu_df, "product_name")
    if cart_df is not None:
        cart_df = _apply_name_normalization(cart_df, "product_name")

    # Determine merge keys - use normalized product_name for matching
    merge_keys = ["product_name_normalized", "category"]

    # Check which location identifier to use
    if "pricing_level" in expected_df.columns and "pricing_level" in menu_df.columns:
        merge_keys.append("pricing_level")
    elif "province" in expected_df.columns and "province" in menu_df.columns:
        merge_keys.append("province")

    if "size" in menu_df.columns:
        merge_keys.append("size")
        if "size" not in expected_df.columns:
            expected_df["size"] = None

    # Determine which columns to include from menu_df
    menu_cols = merge_keys.copy()
    # Include original product_name for display
    if "product_name" in menu_df.columns and "product_name" not in menu_cols:
        menu_cols.append("product_name")
    if "store_name" in menu_df.columns:
        menu_cols.append("store_name")
    if "province" in menu_df.columns and "province" not in menu_cols:
        menu_cols.append("province")
    if "pricing_level" in menu_df.columns and "pricing_level" not in menu_cols:
        menu_cols.append("pricing_level")
    menu_cols.append("menu_price")

    # Start with menu prices as the base
    result_df = menu_df[[c for c in menu_cols if c in menu_df.columns]].copy()

    # Determine expected columns for merge
    expected_merge_cols = [c for c in merge_keys if c in expected_df.columns]
    expected_merge_cols.append("expected_price")

    # Merge with expected prices
    if not expected_df.empty:
        result_df = pd.merge(
            result_df,
            expected_df[[c for c in expected_merge_cols if c in expected_df.columns]],
            on=[c for c in merge_keys if c in expected_df.columns],
            how="left",
        )
    else:
        result_df["expected_price"] = None

    # Merge with cart prices if available
    if cart_df is not None and not cart_df.empty:
        cart_merge_keys = [k for k in merge_keys if k in cart_df.columns]
        cart_subset = cart_df[cart_merge_keys + ["cart_price"]].copy()
        result_df = pd.merge(
            result_df,
            cart_subset,
            on=cart_merge_keys,
            how="left",
        )
    else:
        result_df["cart_price"] = None

    # Calculate differences
    result_df["menu_vs_expected_diff"] = (
        result_df["menu_price"].astype(float) - result_df["expected_price"].astype(float)
    ).round(2)

    result_df["cart_vs_menu_diff"] = (
        result_df["cart_price"].astype(float) - result_df["menu_price"].astype(float)
    ).round(2)

    # Determine status
    def get_status(row):
        issues = []

        # Check menu vs expected
        if pd.notna(row["expected_price"]) and pd.notna(row["menu_price"]):
            if abs(float(row["menu_vs_expected_diff"])) > tolerance:
                issues.append("MENU≠EXPECTED")
        elif pd.isna(row["expected_price"]):
            issues.append("NO_EXPECTED")

        # Check cart vs menu
        if pd.notna(row["cart_price"]) and pd.notna(row["menu_price"]):
            if abs(float(row["cart_vs_menu_diff"])) > tolerance:
                issues.append("CART≠MENU")
        elif pd.isna(row["cart_price"]) and cart_prices:  # Only flag if cart capture was enabled
            issues.append("NO_CART")

        return "PASS" if not issues else ", ".join(issues)

    result_df["status"] = result_df.apply(get_status, axis=1)

    # Reorder columns for clarity - include both province and pricing_level if present
    output_columns = [
        "pricing_level",
        "province",
        "store_name",
        "category",
        "product_name",
        "size",
        "expected_price",
        "menu_price",
        "cart_price",
        "menu_vs_expected_diff",
        "cart_vs_menu_diff",
        "status",
    ]
    available_columns = [c for c in output_columns if c in result_df.columns]
    result_df = result_df[available_columns]

    # Generate summary
    total = len(result_df)
    passed = len(result_df[result_df["status"] == "PASS"])
    menu_issues = len(result_df[result_df["status"].str.contains("MENU≠EXPECTED", na=False)])
    cart_issues = len(result_df[result_df["status"].str.contains("CART≠MENU", na=False)])

    issues_df = result_df[result_df["status"] != "PASS"].copy()

    return {
        "summary": f"Total: {total}, Pass: {passed}, Menu≠Expected: {menu_issues}, Cart≠Menu: {cart_issues}",
        "full_comparison_df": result_df,
        "issues_df": issues_df,
    }


def _create_empty_all_prices_results(message: str) -> dict:
    """Create empty results for all-prices comparison."""
    output_columns = [
        "pricing_level",
        "province",
        "store_name",
        "category",
        "product_name",
        "size",
        "expected_price",
        "menu_price",
        "cart_price",
        "menu_vs_expected_diff",
        "cart_vs_menu_diff",
        "status",
    ]
    return {
        "summary": message,
        "full_comparison_df": pd.DataFrame(columns=output_columns),
        "issues_df": pd.DataFrame(columns=output_columns),
    }
