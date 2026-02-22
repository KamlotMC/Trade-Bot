"""
Configuration loader for the Meowcoin Market Maker bot.

Reads config.yaml and .env to build a unified settings object.
Handles PyInstaller frozen mode (single-file .exe) by:
  - Reading bundled defaults from sys._MEIPASS
  - Creating user-editable config/env next to the executable on first run
"""

import os
import sys
import shutil
import yaml
from dataclasses import dataclass, field
from pathlib import Path
from dotenv import load_dotenv


def get_app_dir() -> Path:
    """Return the directory where the executable (or script) lives.

    For a PyInstaller one-file build this is the folder containing the .exe,
    NOT the temp extraction folder.  For normal Python execution it is the
    directory containing main.py / the working directory.
    """
    if getattr(sys, 'frozen', False):
        # Running as a PyInstaller bundle
        return Path(sys.executable).parent
    return Path.cwd()


def get_bundle_dir() -> Path:
    """Return the directory where bundled data files are extracted.

    For a PyInstaller one-file build this is the temp _MEIPASS folder.
    For normal Python execution it is cwd().
    """
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return Path(sys._MEIPASS)
    return Path.cwd()


def _ensure_user_file(filename: str, force: bool = False) -> Path:
    """Ensure a user-editable copy of *filename* exists next to the exe.

    If the file doesn't exist in the app dir yet (or *force* is True),
    copy the bundled default from the _MEIPASS temp dir (or cwd for
    dev mode).  Returns the path to the user-editable file.
    """
    app_dir = get_app_dir()
    user_file = app_dir / filename
    if force or not user_file.exists():
        bundled = get_bundle_dir() / filename
        if bundled.exists():
            if bundled.resolve() != user_file.resolve():
                shutil.copy2(bundled, user_file)
    return user_file


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
    base_quantity: float = 100000.0
    quantity_multiplier: float = 1.5
    min_spread_pct: float = 0.01
    min_bid_price: float = 0.0
    min_order_value_usdt: float = 1.10
    refresh_interval_sec: int = 30
    order_type: str = "limit"


@dataclass
class RiskConfig:
    max_mewc_exposure: float = 50000000.0
    max_usdt_exposure: float = 5000.0
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
    """Load configuration from YAML file and environment variables.

    When running as a frozen .exe the function will:
      1. Copy the bundled config.yaml / .env.example to the exe directory
         on first run so the user can edit them.
      2. Read from those user-editable copies.
    """
    app_dir = get_app_dir()

    # Resolve config path — if the caller passed the default, look next to exe
    if config_path == "config.yaml":
        user_config = _ensure_user_file("config.yaml", force=True)
    else:
        user_config = Path(config_path)

    # Ensure .env.example is copied so user sees the template
    _ensure_user_file(".env.example")

    # Load .env from next to the config file (or next to exe)
    env_path = user_config.parent / ".env"
    if not env_path.exists():
        # Also try next to the executable
        env_path = app_dir / ".env"
    load_dotenv(dotenv_path=env_path)

    # Read YAML
    if user_config.exists():
        with open(user_config, "r") as f:
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
        min_bid_price=st_raw.get("min_bid_price", StrategyConfig.min_bid_price),
        min_order_value_usdt=st_raw.get("min_order_value_usdt", StrategyConfig.min_order_value_usdt),
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

    return _sanitize_config(BotConfig(
        exchange=exchange,
        strategy=strategy,
        risk=risk,
        logging=logging_cfg,
    ))


def _sanitize_config(cfg: BotConfig) -> BotConfig:
    """Auto-correct common mis-entries.

    Percentage fields are stored as fractions (0.02 = 2%).  If the user
    entered a value > 1 it almost certainly means they typed the percentage
    directly (e.g. ``2`` instead of ``0.02``).  Fix it silently.
    """
    pct_fields = [
        (cfg.strategy, "spread_pct"),
        (cfg.strategy, "level_step_pct"),
        (cfg.strategy, "min_spread_pct"),
        (cfg.risk, "max_balance_usage_pct"),
    ]
    for obj, attr in pct_fields:
        val = getattr(obj, attr)
        if val > 1:
            setattr(obj, attr, val / 100.0)
    return cfg
