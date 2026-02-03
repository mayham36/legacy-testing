"""Parser for Panago Master Pricing Document.

Parses the master Excel document (e.g., "Q3 2025 Master Checklist") and extracts
expected prices for each product across all pricing levels.
"""
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

import pandas as pd
import structlog

from .models import ExpectedPrice, PricingLevel

logger = structlog.get_logger()


class MasterDocumentParser:
    """Parse Panago master pricing document into expected prices."""

    # Pizza sizes in order (columns per PL)
    PIZZA_SIZES = ["Small", "Medium", "Large", "Extra-Large"]

    # Column indices for each PL in the Pizzas sheet
    # Each PL has 4 columns (S, M, L, XL)
    PIZZA_PL_COLUMNS = {
        PricingLevel.PL1: (3, 4, 5, 6),
        PricingLevel.PL2: (7, 8, 9, 10),
        PricingLevel.PL2_B: (11, 12, 13, 14),
        PricingLevel.PL3: (15, 16, 17, 18),
        PricingLevel.PL4: (19, 20, 21, 22),
    }

    # Column indices for Sides sheet (single price per PL)
    SIDES_PL_COLUMNS = {
        PricingLevel.PL1: 3,
        PricingLevel.PL2: 4,
        PricingLevel.PL2_B: 5,
        PricingLevel.PL3: 6,
        PricingLevel.PL4: 7,
    }

    # Column indices for Beverages sheet
    BEVERAGES_PL_COLUMNS = {
        PricingLevel.PL1: 2,
        PricingLevel.PL2: 3,
        PricingLevel.PL2_B: 4,
        PricingLevel.PL3: 5,
        PricingLevel.PL4: 6,
    }

    def __init__(self, file_path: Path):
        """Initialize parser with path to master document.

        Args:
            file_path: Path to the master Excel document (.xls or .xlsx)
        """
        self.file_path = Path(file_path)
        self._xlsx: Optional[pd.ExcelFile] = None
        self._prices: list[ExpectedPrice] = []

    def parse(self) -> list[ExpectedPrice]:
        """Parse all sheets and return expected prices.

        Returns:
            List of ExpectedPrice objects for all products/PLs.
        """
        logger.info("parsing_master_document", file=str(self.file_path))

        self._xlsx = pd.ExcelFile(self.file_path)
        self._prices = []

        # Parse each product sheet
        sheet_parsers = {
            "Pizzas": self._parse_pizzas,
            "Sides": self._parse_sides,
            "Beverages": self._parse_beverages,
            "Dip Pricing": self._parse_dips,
        }

        for sheet_name, parser_func in sheet_parsers.items():
            if sheet_name in self._xlsx.sheet_names:
                try:
                    count_before = len(self._prices)
                    parser_func()
                    count_after = len(self._prices)
                    logger.info(
                        "parsed_sheet",
                        sheet=sheet_name,
                        prices_found=count_after - count_before,
                    )
                except Exception as e:
                    logger.warning(
                        "sheet_parse_failed",
                        sheet=sheet_name,
                        error=str(e),
                    )

        logger.info("parsing_complete", total_prices=len(self._prices))
        return self._prices

    def _parse_pizzas(self) -> None:
        """Parse Pizzas sheet with size variants."""
        df = pd.read_excel(self._xlsx, sheet_name="Pizzas", header=None)

        last_category = ""
        # Data starts at row 5 (0-indexed)
        for idx in range(5, len(df)):
            row = df.iloc[idx]

            # Get category (column 0) - persists until next category
            category = row.iloc[0]
            if pd.notna(category) and str(category).strip():
                last_category = self._clean_category(str(category))

            # Get product name (column 1)
            product_name = row.iloc[1]
            if pd.isna(product_name) or not str(product_name).strip():
                continue

            product_name = str(product_name).strip()

            # Extract prices for each PL and size
            for pl, columns in self.PIZZA_PL_COLUMNS.items():
                for size_idx, col_idx in enumerate(columns):
                    try:
                        price_val = row.iloc[col_idx]
                        if pd.notna(price_val):
                            price = self._parse_price(price_val)
                            if price and price > 0:
                                self._prices.append(ExpectedPrice(
                                    category="pizzas",
                                    product_name=product_name,
                                    size=self.PIZZA_SIZES[size_idx],
                                    pricing_level=pl,
                                    price=price,
                                ))
                    except (IndexError, ValueError) as e:
                        logger.debug(
                            "price_extraction_failed",
                            product=product_name,
                            pl=pl,
                            error=str(e),
                        )

    def _parse_sides(self) -> None:
        """Parse Sides sheet (salads, desserts, breads, wings, etc.)."""
        df = pd.read_excel(self._xlsx, sheet_name="Sides", header=None)

        last_category = ""
        # Data starts at row 3 (0-indexed)
        for idx in range(3, len(df)):
            row = df.iloc[idx]

            # Get category (column 0)
            category = row.iloc[0]
            if pd.notna(category) and str(category).strip():
                last_category = self._clean_category(str(category))

            # Get product name (column 1)
            product_name = row.iloc[1]
            if pd.isna(product_name) or not str(product_name).strip():
                continue

            product_name = str(product_name).strip()

            # Get size if available (column 8)
            size = None
            try:
                size_val = row.iloc[8]
                if pd.notna(size_val):
                    size = str(size_val).strip()
            except IndexError:
                pass

            # Map category to standard names
            category_map = {
                "salads": "salads",
                "desserts": "dessert",
                "breads": "sides",
                "wings": "sides",
            }
            normalized_category = category_map.get(last_category.lower(), "sides")

            # Extract prices for each PL
            for pl, col_idx in self.SIDES_PL_COLUMNS.items():
                try:
                    price_val = row.iloc[col_idx]
                    if pd.notna(price_val):
                        price = self._parse_price(price_val)
                        if price and price > 0:
                            self._prices.append(ExpectedPrice(
                                category=normalized_category,
                                product_name=product_name,
                                size=size,
                                pricing_level=pl,
                                price=price,
                            ))
                except (IndexError, ValueError) as e:
                    logger.debug(
                        "sides_price_extraction_failed",
                        product=product_name,
                        pl=pl,
                        error=str(e),
                    )

    def _parse_beverages(self) -> None:
        """Parse Beverages sheet."""
        df = pd.read_excel(self._xlsx, sheet_name="Beverages", header=None)

        last_category = ""
        # Data starts at row 4 (0-indexed), after header rows
        for idx in range(4, len(df)):
            row = df.iloc[idx]

            # Get category/item type (column 0)
            item_type = row.iloc[0]
            if pd.notna(item_type) and str(item_type).strip():
                # Check if it's a category header (ends with ":")
                item_str = str(item_type).strip()
                if item_str.endswith(":"):
                    last_category = item_str.rstrip(":")
                    continue

            # Get product name (column 1)
            product_name = row.iloc[1]
            if pd.isna(product_name) or not str(product_name).strip():
                continue

            product_name = str(product_name).strip()

            # Get size if available (column 7)
            size = None
            try:
                size_val = row.iloc[7]
                if pd.notna(size_val):
                    size = str(size_val).strip()
            except IndexError:
                pass

            # Extract prices for each PL
            for pl, col_idx in self.BEVERAGES_PL_COLUMNS.items():
                try:
                    price_val = row.iloc[col_idx]
                    if pd.notna(price_val):
                        price = self._parse_price(price_val)
                        if price and price > 0:
                            self._prices.append(ExpectedPrice(
                                category="beverages",
                                product_name=product_name,
                                size=size,
                                pricing_level=pl,
                                price=price,
                            ))
                except (IndexError, ValueError) as e:
                    logger.debug(
                        "beverage_price_extraction_failed",
                        product=product_name,
                        pl=pl,
                        error=str(e),
                    )

    def _parse_dips(self) -> None:
        """Parse Dip Pricing sheet for dip prices."""
        # The Dip Pricing sheet primarily contains store mappings,
        # but also has dip prices. For now, we'll use a standard dip price
        # from the sheet header or use the Dip Pricing sheet's structure.
        # This is a simpler sheet - dip prices are generally uniform.
        pass  # TODO: Implement if dip prices need individual tracking

    def _parse_price(self, value) -> Optional[Decimal]:
        """Parse a price value to Decimal.

        Args:
            value: Raw value from Excel cell.

        Returns:
            Decimal price or None if unparseable.
        """
        if pd.isna(value):
            return None

        try:
            # Handle numeric values directly
            if isinstance(value, (int, float)):
                return Decimal(str(value)).quantize(Decimal("0.01"))

            # Handle string values
            str_val = str(value).strip()

            # Remove currency symbols and whitespace
            str_val = str_val.replace("$", "").replace(",", "").strip()

            # Extract numeric part
            match = re.search(r"(\d+\.?\d*)", str_val)
            if match:
                return Decimal(match.group(1)).quantize(Decimal("0.01"))

        except (InvalidOperation, ValueError):
            pass

        return None

    def _clean_category(self, category: str) -> str:
        """Clean and normalize category name.

        Args:
            category: Raw category string.

        Returns:
            Cleaned category name.
        """
        # Remove common suffixes
        category = category.strip()
        category = re.sub(r"\s*(pizzas?|items?)\s*$", "", category, flags=re.IGNORECASE)
        return category.strip()

    def get_summary(self) -> dict:
        """Get summary of parsed prices.

        Returns:
            Dictionary with counts by category and pricing level.
        """
        if not self._prices:
            return {"total": 0, "by_category": {}, "by_pl": {}}

        by_category: dict[str, int] = {}
        by_pl: dict[str, int] = {}

        for price in self._prices:
            by_category[price.category] = by_category.get(price.category, 0) + 1
            pl_str = str(price.pricing_level)
            by_pl[pl_str] = by_pl.get(pl_str, 0) + 1

        return {
            "total": len(self._prices),
            "by_category": by_category,
            "by_pl": by_pl,
        }


def load_master_document(file_path: Path) -> list[ExpectedPrice]:
    """Convenience function to parse a master document.

    Args:
        file_path: Path to the master Excel document.

    Returns:
        List of ExpectedPrice objects.
    """
    parser = MasterDocumentParser(file_path)
    return parser.parse()
