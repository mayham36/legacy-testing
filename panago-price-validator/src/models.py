"""Data contracts for type safety and documentation."""
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Optional


class ValidationStatus(StrEnum):
    """Status values for price validation."""

    PASS = "PASS"
    FAIL = "FAIL"
    MISSING_EXPECTED = "MISSING_EXPECTED"
    MISSING_ACTUAL = "MISSING_ACTUAL"


class PriceSource(StrEnum):
    """Source of the price data."""

    MENU = "menu"
    CART = "cart"


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
    size: Optional[str] = None  # Size variant (e.g., "Small", "Medium", "Large", "Extra-Large")
    price_source: PriceSource = PriceSource.MENU  # Source of price (menu or cart)
    scraped_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        """Convert to dictionary for DataFrame creation."""
        return {
            "province": self.province,
            "store_name": self.store_name,
            "category": self.category,
            "product_name": self.product_name,
            "size": self.size,
            "actual_price": float(self.actual_price),
            "raw_price_text": self.raw_price_text,
            "price_source": str(self.price_source),
            "scraped_at": self.scraped_at.isoformat(),
        }


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
    size: Optional[str] = None  # Size variant for products with multiple sizes
    price_difference: Optional[Decimal] = None

    def __post_init__(self) -> None:
        """Calculate price difference after initialization."""
        if self.expected_price is not None and self.actual_price is not None:
            self.price_difference = self.actual_price - self.expected_price
