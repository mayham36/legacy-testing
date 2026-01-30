"""Tests for price comparison module."""
from decimal import Decimal
from datetime import datetime

import pandas as pd
import pytest

from src.comparison import (
    compare_prices,
    _determine_status,
    _create_empty_results,
    calculate_summary_by_province,
)
from src.models import ValidationStatus, PriceRecord


class TestCompareprices:
    """Tests for the compare_prices function."""

    def test_all_prices_match(self):
        """Test when all actual prices match expected."""
        expected_df = pd.DataFrame({
            "product_name": ["Pizza A", "Pizza B"],
            "category": ["pizzas", "pizzas"],
            "province": ["BC", "BC"],
            "expected_price": [14.99, 19.99],
        })

        actual_prices = [
            PriceRecord(
                province="BC",
                store_name="Test Store",
                category="pizzas",
                product_name="Pizza A",
                actual_price=Decimal("14.99"),
                raw_price_text="$14.99",
            ),
            PriceRecord(
                province="BC",
                store_name="Test Store",
                category="pizzas",
                product_name="Pizza B",
                actual_price=Decimal("19.99"),
                raw_price_text="$19.99",
            ),
        ]

        results = compare_prices(expected_df, actual_prices)

        assert results["summary_df"]["passed"].iloc[0] == 2
        assert results["summary_df"]["failed"].iloc[0] == 0
        assert results["discrepancies_df"].empty

    def test_price_mismatch_detected(self):
        """Test that price mismatches are flagged."""
        expected_df = pd.DataFrame({
            "product_name": ["Pizza A"],
            "category": ["pizzas"],
            "province": ["BC"],
            "expected_price": [14.99],
        })

        actual_prices = [
            PriceRecord(
                province="BC",
                store_name="Test Store",
                category="pizzas",
                product_name="Pizza A",
                actual_price=Decimal("15.99"),  # Wrong price
                raw_price_text="$15.99",
            ),
        ]

        results = compare_prices(expected_df, actual_prices)

        assert results["summary_df"]["failed"].iloc[0] == 1
        assert len(results["discrepancies_df"]) == 1

    def test_tolerance_applied(self):
        """Test that small differences within tolerance pass."""
        expected_df = pd.DataFrame({
            "product_name": ["Pizza A"],
            "category": ["pizzas"],
            "province": ["BC"],
            "expected_price": [14.99],
        })

        actual_prices = [
            PriceRecord(
                province="BC",
                store_name="Test Store",
                category="pizzas",
                product_name="Pizza A",
                actual_price=Decimal("14.995"),  # Within $0.01 tolerance
                raw_price_text="$15.00",
            ),
        ]

        results = compare_prices(expected_df, actual_prices, tolerance=0.01)

        assert results["summary_df"]["passed"].iloc[0] == 1

    def test_missing_actual_price(self):
        """Test detection of missing actual prices."""
        expected_df = pd.DataFrame({
            "product_name": ["Pizza A", "Pizza B"],
            "category": ["pizzas", "pizzas"],
            "province": ["BC", "BC"],
            "expected_price": [14.99, 19.99],
        })

        actual_prices = [
            PriceRecord(
                province="BC",
                store_name="Test Store",
                category="pizzas",
                product_name="Pizza A",
                actual_price=Decimal("14.99"),
                raw_price_text="$14.99",
            ),
            # Pizza B is missing
        ]

        results = compare_prices(expected_df, actual_prices)

        assert results["summary_df"]["missing_actual"].iloc[0] == 1

    def test_missing_expected_price(self):
        """Test detection of unexpected products on website."""
        expected_df = pd.DataFrame({
            "product_name": ["Pizza A"],
            "category": ["pizzas"],
            "province": ["BC"],
            "expected_price": [14.99],
        })

        actual_prices = [
            PriceRecord(
                province="BC",
                store_name="Test Store",
                category="pizzas",
                product_name="Pizza A",
                actual_price=Decimal("14.99"),
                raw_price_text="$14.99",
            ),
            PriceRecord(
                province="BC",
                store_name="Test Store",
                category="pizzas",
                product_name="Pizza NEW",  # Not in expected
                actual_price=Decimal("17.99"),
                raw_price_text="$17.99",
            ),
        ]

        results = compare_prices(expected_df, actual_prices)

        assert results["summary_df"]["missing_expected"].iloc[0] == 1

    def test_empty_actual_prices(self):
        """Test handling of empty actual prices list."""
        expected_df = pd.DataFrame({
            "product_name": ["Pizza A"],
            "category": ["pizzas"],
            "province": ["BC"],
            "expected_price": [14.99],
        })

        results = compare_prices(expected_df, [])

        assert "No actual prices" in results["summary"]
        assert results["summary_df"]["total_products"].iloc[0] == 0

    def test_empty_expected_prices(self):
        """Test handling of empty expected DataFrame."""
        expected_df = pd.DataFrame(columns=["product_name", "category", "province", "expected_price"])

        actual_prices = [
            PriceRecord(
                province="BC",
                store_name="Test Store",
                category="pizzas",
                product_name="Pizza A",
                actual_price=Decimal("14.99"),
                raw_price_text="$14.99",
            ),
        ]

        results = compare_prices(expected_df, actual_prices)

        assert "No expected prices" in results["summary"]

    def test_division_by_zero_protection(self):
        """Test that empty results don't cause division by zero."""
        results = _create_empty_results("Test message")

        assert results["summary_df"]["pass_rate"].iloc[0] == "N/A"

    def test_multiple_provinces(self):
        """Test comparison across multiple provinces."""
        expected_df = pd.DataFrame({
            "product_name": ["Pizza A", "Pizza A"],
            "category": ["pizzas", "pizzas"],
            "province": ["BC", "AB"],
            "expected_price": [14.99, 15.99],  # Different prices by province
        })

        actual_prices = [
            PriceRecord(
                province="BC",
                store_name="Vancouver",
                category="pizzas",
                product_name="Pizza A",
                actual_price=Decimal("14.99"),
                raw_price_text="$14.99",
            ),
            PriceRecord(
                province="AB",
                store_name="Calgary",
                category="pizzas",
                product_name="Pizza A",
                actual_price=Decimal("15.99"),
                raw_price_text="$15.99",
            ),
        ]

        results = compare_prices(expected_df, actual_prices)

        assert results["summary_df"]["passed"].iloc[0] == 2
        assert results["summary_df"]["failed"].iloc[0] == 0


class TestDetermineStatus:
    """Tests for the _determine_status helper."""

    def test_pass_within_tolerance(self):
        """Test PASS status when difference within tolerance."""
        row = pd.Series({
            "expected_price": 14.99,
            "actual_price": 14.99,
            "price_difference": 0.0,
        })

        status = _determine_status(row, tolerance=0.01)
        assert status == ValidationStatus.PASS

    def test_fail_outside_tolerance(self):
        """Test FAIL status when difference exceeds tolerance."""
        row = pd.Series({
            "expected_price": 14.99,
            "actual_price": 15.50,
            "price_difference": 0.51,
        })

        status = _determine_status(row, tolerance=0.01)
        assert status == ValidationStatus.FAIL

    def test_missing_expected(self):
        """Test MISSING_EXPECTED when expected is NaN."""
        row = pd.Series({
            "expected_price": None,
            "actual_price": 14.99,
            "price_difference": None,
        })

        status = _determine_status(row, tolerance=0.01)
        assert status == ValidationStatus.MISSING_EXPECTED

    def test_missing_actual(self):
        """Test MISSING_ACTUAL when actual is NaN."""
        row = pd.Series({
            "expected_price": 14.99,
            "actual_price": None,
            "price_difference": None,
        })

        status = _determine_status(row, tolerance=0.01)
        assert status == ValidationStatus.MISSING_ACTUAL


class TestCalculateSummaryByProvince:
    """Tests for per-province summary calculation."""

    def test_summary_by_province(self):
        """Test grouping statistics by province."""
        details_df = pd.DataFrame({
            "province": ["BC", "BC", "AB", "AB"],
            "product_name": ["A", "B", "A", "B"],
            "status": [
                ValidationStatus.PASS,
                ValidationStatus.FAIL,
                ValidationStatus.PASS,
                ValidationStatus.PASS,
            ],
        })

        summary = calculate_summary_by_province(details_df)

        bc_row = summary[summary["province"] == "BC"].iloc[0]
        assert bc_row["passed"] == 1
        assert bc_row["failed"] == 1
        assert bc_row["pass_rate"] == "50.0%"

        ab_row = summary[summary["province"] == "AB"].iloc[0]
        assert ab_row["passed"] == 2
        assert ab_row["failed"] == 0
        assert ab_row["pass_rate"] == "100.0%"

    def test_empty_dataframe(self):
        """Test handling of empty DataFrame."""
        summary = calculate_summary_by_province(pd.DataFrame())
        assert summary.empty
