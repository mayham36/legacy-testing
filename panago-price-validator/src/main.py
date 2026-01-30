"""Panago Pricing Validation Tool - Main Entry Point."""
import argparse
import logging
import sys
from pathlib import Path

import structlog

from .models import AutomationConfig
from .excel_handler import load_expected_prices, save_results
from .browser_automation import PanagoAutomation
from .comparison import compare_prices


def configure_logging(verbose: bool = False) -> None:
    """Configure structured logging.

    Args:
        verbose: Enable debug level logging if True.
    """
    log_level = logging.DEBUG if verbose else logging.INFO

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(
        format="%(message)s",
        level=log_level,
        stream=sys.stdout,
    )


def parse_args() -> argparse.Namespace:
    """Parse command line arguments.

    Returns:
        Parsed arguments namespace.
    """
    parser = argparse.ArgumentParser(
        description="Panago Pricing Validation Tool - Automated price comparison",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic usage with required input file
  python -m src.main -i input/expected_prices.xlsx

  # Run with visible browser for debugging
  python -m src.main -i input/expected_prices.xlsx --visible

  # Test single province only
  python -m src.main -i input/expected_prices.xlsx --province BC

  # Increase parallelism for faster execution
  python -m src.main -i input/expected_prices.xlsx --max-concurrent 8
        """,
    )
    parser.add_argument(
        "--input",
        "-i",
        required=True,
        type=Path,
        help="Path to expected prices Excel file",
    )
    parser.add_argument(
        "--output",
        "-o",
        default="./output",
        type=Path,
        help="Output directory for results (default: ./output)",
    )
    parser.add_argument(
        "--config",
        "-c",
        type=Path,
        help="Path to locations.yaml configuration file",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        default=True,
        help="Run browser in headless mode (default)",
    )
    parser.add_argument(
        "--visible",
        action="store_true",
        help="Run browser with visible window (for debugging)",
    )
    parser.add_argument(
        "--province",
        help="Test single province only (e.g., BC, AB, ON)",
    )
    parser.add_argument(
        "--max-concurrent",
        type=int,
        default=5,
        help="Maximum concurrent browser contexts (default: 5)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30000,
        help="Page timeout in milliseconds (default: 30000)",
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=0.01,
        help="Price tolerance in dollars (default: 0.01)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    return parser.parse_args()


def main() -> int:
    """Run the pricing validation workflow.

    Returns:
        Exit code: 0 if all prices match, 1 if discrepancies found,
        2+ for errors.
    """
    args = parse_args()
    configure_logging(args.verbose)

    logger = structlog.get_logger()

    config = AutomationConfig(
        input_file=args.input,
        output_dir=args.output,
        headless=not args.visible,
        max_concurrent=args.max_concurrent,
        timeout_ms=args.timeout,
    )

    try:
        logger.info("starting_validation", input_file=str(config.input_file))

        # Load expected prices
        expected_prices = load_expected_prices(config.input_file)
        logger.info("loaded_expected_prices", count=len(expected_prices))

        # Filter by province if specified
        if args.province:
            province = args.province.upper()
            expected_prices = expected_prices[
                expected_prices["province"] == province
            ]
            logger.info(
                "filtered_by_province",
                province=province,
                remaining_count=len(expected_prices),
            )

        # Run browser automation
        automation = PanagoAutomation(config, args.config)
        actual_prices = automation.run_price_collection()
        logger.info("collected_actual_prices", count=len(actual_prices))

        # Compare prices
        results = compare_prices(
            expected_prices,
            actual_prices,
            tolerance=args.tolerance,
        )

        # Save results
        output_path = save_results(results, config.output_dir)

        logger.info(
            "validation_complete",
            summary=results["summary"],
            output_file=str(output_path),
        )

        # Print summary to console
        print(f"\n{'=' * 60}")
        print("VALIDATION COMPLETE")
        print(f"{'=' * 60}")
        print(f"Summary: {results['summary']}")
        print(f"Results saved to: {output_path}")

        if not results["discrepancies_df"].empty:
            print(f"\nDiscrepancies found: {len(results['discrepancies_df'])}")
            print("Review the 'Discrepancies' sheet in the output file.")

        print(f"{'=' * 60}\n")

        # Return non-zero exit code if failures found
        return 0 if results["discrepancies_df"].empty else 1

    except FileNotFoundError as e:
        logger.error("file_not_found", error=str(e))
        print(f"Error: {e}", file=sys.stderr)
        return 2

    except ValueError as e:
        logger.error("validation_error", error=str(e))
        print(f"Validation Error: {e}", file=sys.stderr)
        return 3

    except KeyboardInterrupt:
        logger.info("interrupted_by_user")
        print("\nValidation interrupted by user.", file=sys.stderr)
        return 130

    except Exception as e:
        logger.exception("unexpected_error", error=str(e))
        print(f"Unexpected Error: {e}", file=sys.stderr)
        return 4


if __name__ == "__main__":
    sys.exit(main())
