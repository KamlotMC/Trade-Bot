"""
Configuration loader for the Meowcoin Market Maker bot.

Reads config.yaml and .env to build a unified settings object.
"""

import os
import yaml
from dataclasses import dataclass, field
from pathlib import Path
from dotenv import load_dotenv


@dataclass
class ExchangeConfig:
    base_url: str = "https://api.nonkyc.io/api/v2"
    ws_url: str = "wss://ws.nonkyc.io"
    symbol: str = "MEWC/USDT"
    api_key: str = ""
    api_secret: str = ""


@dataclass
class StrategyConfig:
    spread_pct: float = 0.02
    num_levels: int = 3
    level_step_pct: float = 0.005
    base_quantity: float = 1000.0
    quantity_multiplier: float = 1.5
    min_spread_pct: float = 0.01
    refresh_interval_sec: int = 30
    order_type: str = "limit"


@dataclass
class RiskConfig:
    max_mewc_exposure: float = 50000.0
    max_usdt_exposure: float = 500.0
    inventory_skew_factor: float = 0.5
    max_balance_usage_pct: float = 0.80
    stop_loss_usdt: float = -50.0
    max_open_orders: int = 20
    daily_loss_limit_usdt: float = -100.0


@dataclass
class LoggingConfig:
    level: str = "INFO"
    file: str = "logs/market_maker.log"
    console: bool = True
    max_file_size_mb: int = 10
    backup_count: int = 5


@dataclass
class BotConfig:
    exchange: ExchangeConfig = field(default_factory=ExchangeConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)


def load_config(config_path: str = "config.yaml") -> BotConfig:
    """Load configuration from YAML file and environment variables."""
    # Load .env file
    env_path = Path(config_path).parent / ".env"
    load_dotenv(dotenv_path=env_path)

    # Read YAML
    config_file = Path(config_path)
    if config_file.exists():
        with open(config_file, "r") as f:
            raw = yaml.safe_load(f) or {}
    else:
        raw = {}

    # Build config
    ex_raw = raw.get("exchange", {})
    st_raw = raw.get("strategy", {})
    rk_raw = raw.get("risk", {})
    lg_raw = raw.get("logging", {})

    exchange = ExchangeConfig(
        base_url=ex_raw.get("base_url", ExchangeConfig.base_url),
        ws_url=ex_raw.get("ws_url", ExchangeConfig.ws_url),
        symbol=ex_raw.get("symbol", ExchangeConfig.symbol),
        api_key=os.getenv("NONKYC_API_KEY", ""),
        api_secret=os.getenv("NONKYC_API_SECRET", ""),
    )

    strategy = StrategyConfig(
        spread_pct=st_raw.get("spread_pct", StrategyConfig.spread_pct),
        num_levels=st_raw.get("num_levels", StrategyConfig.num_levels),
        level_step_pct=st_raw.get("level_step_pct", StrategyConfig.level_step_pct),
        base_quantity=st_raw.get("base_quantity", StrategyConfig.base_quantity),
        quantity_multiplier=st_raw.get("quantity_multiplier", StrategyConfig.quantity_multiplier),
        min_spread_pct=st_raw.get("min_spread_pct", StrategyConfig.min_spread_pct),
        refresh_interval_sec=st_raw.get("refresh_interval_sec", StrategyConfig.refresh_interval_sec),
        order_type=st_raw.get("order_type", StrategyConfig.order_type),
    )

    risk = RiskConfig(
        max_mewc_exposure=rk_raw.get("max_mewc_exposure", RiskConfig.max_mewc_exposure),
        max_usdt_exposure=rk_raw.get("max_usdt_exposure", RiskConfig.max_usdt_exposure),
        inventory_skew_factor=rk_raw.get("inventory_skew_factor", RiskConfig.inventory_skew_factor),
        max_balance_usage_pct=rk_raw.get("max_balance_usage_pct", RiskConfig.max_balance_usage_pct),
        stop_loss_usdt=rk_raw.get("stop_loss_usdt", RiskConfig.stop_loss_usdt),
        max_open_orders=rk_raw.get("max_open_orders", RiskConfig.max_open_orders),
        daily_loss_limit_usdt=rk_raw.get("daily_loss_limit_usdt", RiskConfig.daily_loss_limit_usdt),
    )

    logging_cfg = LoggingConfig(
        level=lg_raw.get("level", LoggingConfig.level),
        file=lg_raw.get("file", LoggingConfig.file),
        console=lg_raw.get("console", LoggingConfig.console),
        max_file_size_mb=lg_raw.get("max_file_size_mb", LoggingConfig.max_file_size_mb),
        backup_count=lg_raw.get("backup_count", LoggingConfig.backup_count),
    )

    return BotConfig(
        exchange=exchange,
        strategy=strategy,
        risk=risk,
        logging=logging_cfg,
    )
