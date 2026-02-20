#!/usr/bin/env python3
"""
Meowcoin Market Maker Bot — Entry Point

A market-making bot for the MEWC/USDT pair on the NonKYC exchange.
Places symmetric bid/ask limit orders around the mid-price, with
inventory skew and configurable risk management.

Usage:
    python main.py                   # Run with default config.yaml
    python main.py --config my.yaml  # Run with custom config
    python main.py --dry-run         # Show what would happen (no orders placed)

IMPORTANT: Read LEGAL_NOTICE.md before running this bot.
"""

import argparse
import sys

from market_maker.config import load_config
from market_maker.exchange_client import NonKYCClient
from market_maker.logger import setup_logger
from market_maker.risk_manager import RiskManager
from market_maker.strategy import MarketMaker


BANNER = r"""
  __  __                         _         __  __ __  __
 |  \/  | ___  _____      _____ (_)_ __   |  \/  |  \/  |
 | |\/| |/ _ \/ _ \ \ /\ / / __| | '_ \  | |\/| | |\/| |
 | |  | |  __/ (_) \ V  V / (__| | | | | | |  | | |  | |
 |_|  |_|\___|\___/ \_/\_/ \___|_|_| |_| |_|  |_|_|  |_|

          MEWC/USDT Market Maker — NonKYC Exchange
"""

LEGAL_DISCLAIMER = """
╔═══════════════════════════════════════════════════════════════╗
║                    LEGAL DISCLAIMER                         ║
╠═══════════════════════════════════════════════════════════════╣
║ This software is provided for EDUCATIONAL and INFORMATIONAL ║
║ purposes only. By using this bot you acknowledge that:      ║
║                                                             ║
║ 1. You are solely responsible for compliance with all       ║
║    applicable laws and regulations in your jurisdiction.    ║
║                                                             ║
║ 2. Cryptocurrency trading carries significant risk of       ║
║    financial loss. Past performance does not guarantee       ║
║    future results.                                          ║
║                                                             ║
║ 3. Market making on unregulated or lightly regulated        ║
║    exchanges may carry legal risk depending on your         ║
║    jurisdiction. Consult a qualified legal professional.    ║
║                                                             ║
║ 4. This bot does NOT engage in wash trading, spoofing,      ║
║    layering, or any form of market manipulation. All        ║
║    orders are genuine two-sided liquidity.                  ║
║                                                             ║
║ 5. The developers assume no liability for financial         ║
║    losses or legal consequences from using this software.   ║
║                                                             ║
║ 6. You confirm you have read LEGAL_NOTICE.md in full.       ║
╚═══════════════════════════════════════════════════════════════╝
"""


def main():
    parser = argparse.ArgumentParser(
        description="Meowcoin MEWC/USDT Market Maker Bot for NonKYC Exchange"
    )
    parser.add_argument(
        "--config", "-c",
        default="config.yaml",
        help="Path to YAML configuration file (default: config.yaml)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print configuration and exit without placing orders",
    )
    parser.add_argument(
        "--accept-disclaimer",
        action="store_true",
        help="Accept the legal disclaimer without interactive prompt",
    )
    args = parser.parse_args()

    # Show banner
    print(BANNER)

    # Load configuration
    try:
        config = load_config(args.config)
    except Exception as e:
        print(f"ERROR: Failed to load config from '{args.config}': {e}")
        sys.exit(1)

    # Set up logging
    log = setup_logger("mewc_mm", config.logging)
    # Also configure sub-loggers
    setup_logger("mewc_mm.exchange", config.logging)
    setup_logger("mewc_mm.strategy", config.logging)
    setup_logger("mewc_mm.risk", config.logging)

    # Validate API keys
    if not config.exchange.api_key or not config.exchange.api_secret:
        log.error(
            "API credentials not configured. "
            "Copy .env.example to .env and fill in your NonKYC API key and secret."
        )
        sys.exit(1)

    # Legal disclaimer
    print(LEGAL_DISCLAIMER)
    if not args.accept_disclaimer:
        try:
            resp = input("Do you accept the above disclaimer? (yes/no): ").strip().lower()
            if resp not in ("yes", "y"):
                print("Disclaimer not accepted. Exiting.")
                sys.exit(0)
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            sys.exit(0)

    # Dry-run check
    if args.dry_run:
        log.info("=== DRY RUN MODE ===")
        log.info("Exchange:  %s", config.exchange.base_url)
        log.info("Symbol:    %s", config.exchange.symbol)
        log.info("Spread:    %.2f%%", config.strategy.spread_pct * 100)
        log.info("Levels:    %d", config.strategy.num_levels)
        log.info("Base Qty:  %.2f MEWC", config.strategy.base_quantity)
        log.info("Refresh:   %ds", config.strategy.refresh_interval_sec)
        log.info("Max MEWC:  %.2f", config.risk.max_mewc_exposure)
        log.info("Max USDT:  %.2f", config.risk.max_usdt_exposure)
        log.info("Stop Loss: %.2f USDT", config.risk.stop_loss_usdt)
        log.info("Daily Cap: %.2f USDT", config.risk.daily_loss_limit_usdt)
        log.info("=== END DRY RUN — no orders placed ===")
        sys.exit(0)

    # Initialize components
    client = NonKYCClient(config.exchange)
    risk = RiskManager(config.risk)
    bot = MarketMaker(config, client, risk)

    # Run
    log.info("Starting Meowcoin Market Maker...")
    bot.run()


if __name__ == "__main__":
    main()
