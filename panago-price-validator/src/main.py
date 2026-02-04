"""Panago Pricing Validation Tool - Main Entry Point."""
import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

import structlog

from .models import AutomationConfig
from .excel_handler import load_expected_prices, save_results
from .browser_automation import PanagoAutomation
from .comparison import compare_prices, compare_menu_vs_cart
from .config_loader import load_settings


def run_web_server(host: str = "0.0.0.0", port: int = 8080):
    """Start the web UI server."""
    import uvicorn
    from .web.app import app

    print(f"\n{'=' * 60}")
    print("PANAGO PRICE VALIDATOR - WEB UI")
    print(f"{'=' * 60}")
    print(f"Starting web server on http://{host}:{port}")
    print(f"{'=' * 60}\n")

    uvicorn.run(app, host=host, port=port, log_level="info")


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
        type=Path,
        help="Path to expected prices Excel file (required for CLI mode)",
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
        default=Path("config/locations.yaml"),
        help="Path to locations.yaml configuration file (default: config/locations.yaml)",
    )
    parser.add_argument(
        "--settings",
        "-s",
        type=Path,
        default=Path("config/settings.yaml"),
        help="Path to settings.yaml configuration file",
    )
    parser.add_argument(
        "--env",
        "-e",
        choices=["qa", "production"],
        default="qa",
        help="Environment to run against (default: qa)",
    )
    parser.add_argument(
        "--safe-mode",
        action="store_true",
        default=True,
        help="Enable safe mode with conservative rate limiting (default: enabled)",
    )
    parser.add_argument(
        "--no-safe-mode",
        action="store_true",
        help="Disable safe mode (use with caution on production)",
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
    parser.add_argument(
        "--cart-prices",
        action="store_true",
        help="Compare menu prices to cart prices (slower - adds each item to cart)",
    )
    parser.add_argument(
        "--web",
        action="store_true",
        help="Start web UI server instead of CLI",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Port for web server (default: 8080)",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host for web server (default: 0.0.0.0)",
    )

    return parser.parse_args()


def main() -> int:
    """Run the pricing validation workflow.

    Returns:
        Exit code: 0 if all prices match, 1 if discrepancies found,
        2+ for errors.
    """
    args = parse_args()

    # Web UI mode
    if args.web:
        run_web_server(host=args.host, port=args.port)
        return 0

    # CLI mode requires input file
    if not args.input:
        print("Error: --input/-i is required for CLI mode", file=sys.stderr)
        print("Use --web to start the web UI instead", file=sys.stderr)
        return 2

    configure_logging(args.verbose)

    logger = structlog.get_logger()

    # Load settings from YAML
    settings = {}
    if args.settings.exists():
        settings = load_settings(args.settings)

    # Determine environment settings
    env_name = args.env
    env_settings = settings.get("environments", {}).get(env_name, {})
    base_url = env_settings.get("base_url", "https://www.panago.com")

    # Determine if safe mode is enabled
    safe_mode = args.safe_mode and not args.no_safe_mode
    if safe_mode:
        safe_settings = settings.get("safe_mode_settings", {})
        max_concurrent = safe_settings.get("max_concurrent", 1)
        min_delay = safe_settings.get("min_delay_ms", 5000)
        max_delay = safe_settings.get("max_delay_ms", 10000)
    else:
        max_concurrent = env_settings.get("max_concurrent", args.max_concurrent)
        min_delay = env_settings.get("min_delay_ms", 3000)
        max_delay = env_settings.get("max_delay_ms", 6000)

    config = AutomationConfig(
        input_file=args.input,
        output_dir=args.output,
        headless=not args.visible,
        max_concurrent=max_concurrent,
        timeout_ms=args.timeout,
    )

    try:
        logger.info(
            "starting_validation",
            input_file=str(config.input_file),
            environment=env_name,
            base_url=base_url,
            safe_mode=safe_mode,
            max_concurrent=max_concurrent,
            delay_range=f"{min_delay}-{max_delay}ms",
        )

        print(f"\n{'=' * 60}")
        print(f"PANAGO PRICING VALIDATION")
        print(f"{'=' * 60}")
        print(f"Environment: {env_name.upper()}")
        print(f"Base URL: {base_url}")
        print(f"Safe Mode: {'ENABLED' if safe_mode else 'DISABLED'}")
        print(f"Max Concurrent: {max_concurrent}")
        print(f"Delay Range: {min_delay/1000:.1f}s - {max_delay/1000:.1f}s")
        print(f"{'=' * 60}\n")

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
        started_at = datetime.now()
        automation = PanagoAutomation(
            config,
            args.config,
            base_url=base_url,
            min_delay_ms=min_delay,
            max_delay_ms=max_delay,
            capture_cart_prices=args.cart_prices,
        )
        actual_prices = automation.run_price_collection()
        ended_at = datetime.now()
        elapsed_seconds = (ended_at - started_at).total_seconds()
        logger.info("collected_actual_prices", count=len(actual_prices), elapsed_seconds=elapsed_seconds)

        # Compare prices (expected vs actual menu prices)
        results = compare_prices(
            expected_prices,
            actual_prices,
            tolerance=args.tolerance,
        )

        # Compare menu vs cart prices if cart capture was enabled
        menu_vs_cart_results = None
        if args.cart_prices:
            menu_vs_cart_results = compare_menu_vs_cart(
                actual_prices,
                tolerance=args.tolerance,
            )
            logger.info(
                "menu_vs_cart_comparison",
                summary=menu_vs_cart_results["summary"],
            )

        # Build timing info
        timing_info = {
            "started_at": started_at.isoformat(),
            "ended_at": ended_at.isoformat(),
            "elapsed_seconds": elapsed_seconds,
            "locations_count": len(set(p.store_name for p in actual_prices)) if actual_prices else 0,
        }

        # Save results
        output_path = save_results(
            results,
            config.output_dir,
            menu_vs_cart_results=menu_vs_cart_results,
            timing_info=timing_info,
        )

        logger.info(
            "validation_complete",
            summary=results["summary"],
            output_file=str(output_path),
        )

        # Print summary to console
        elapsed_str = f"{int(elapsed_seconds // 60)}m {int(elapsed_seconds % 60)}s"
        print(f"\n{'=' * 60}")
        print("VALIDATION COMPLETE")
        print(f"{'=' * 60}")
        print(f"Duration: {elapsed_str}")
        print(f"Summary: {results['summary']}")

        if menu_vs_cart_results:
            print(f"Cart Comparison: {menu_vs_cart_results['summary']}")

        print(f"Results saved to: {output_path}")

        if not results["discrepancies_df"].empty:
            print(f"\nDiscrepancies found: {len(results['discrepancies_df'])}")
            print("Review the 'Discrepancies' sheet in the output file.")

        if menu_vs_cart_results and not menu_vs_cart_results["mismatches_df"].empty:
            print(f"\nCart price mismatches: {len(menu_vs_cart_results['mismatches_df'])}")
            print("Review the 'Cart Mismatches' sheet in the output file.")

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
