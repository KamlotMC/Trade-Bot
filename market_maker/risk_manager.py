"""
Risk manager for the Meowcoin Market Maker.

Enforces position limits, daily loss limits, and inventory skew adjustments
to keep the bot operating within predefined safety bounds.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, Optional

from market_maker.config import RiskConfig

logger = logging.getLogger("mewc_mm.risk")


@dataclass
class PositionState:
    """Tracks current inventory and P&L."""
    mewc_balance: float = 0.0
    usdt_balance: float = 0.0
    mewc_held: float = 0.0       # Locked in open orders
    usdt_held: float = 0.0       # Locked in open orders
    initial_mewc: float = 0.0
    initial_usdt: float = 0.0
    daily_pnl_usdt: float = 0.0
    day_start_ts: float = field(default_factory=time.time)
    last_mid_price: float = 0.0


class RiskManager:
    """Enforces risk limits and calculates inventory-adjusted quotes."""

    def __init__(self, config: RiskConfig):
        self.cfg = config
        self.position = PositionState()
        self._halted = False
        self._halt_reason = ""

    @property
    def is_halted(self) -> bool:
        return self._halted

    @property
    def halt_reason(self) -> str:
        return self._halt_reason

    def halt(self, reason: str) -> None:
        """Halt the bot with a reason."""
        self._halted = True
        self._halt_reason = reason
        logger.critical("RISK HALT: %s", reason)

    def resume(self) -> None:
        """Resume after a halt (manual intervention)."""
        self._halted = False
        self._halt_reason = ""
        logger.info("RISK RESUMED — bot is back online")

    # -------------------------------------------------------------------------
    # Balance updates
    # -------------------------------------------------------------------------

    def update_balances(self, mewc_available: float, mewc_held: float,
                        usdt_available: float, usdt_held: float,
                        mid_price: float) -> None:
        """Update position state from exchange balance data."""
        self.position.mewc_balance = mewc_available
        self.position.mewc_held = mewc_held
        self.position.usdt_balance = usdt_available
        self.position.usdt_held = usdt_held
        self.position.last_mid_price = mid_price

        # Reset daily tracking at midnight-ish (every 24h)
        if time.time() - self.position.day_start_ts > 86400:
            logger.info("Daily P&L reset. Previous: %.4f USDT", self.position.daily_pnl_usdt)
            self.position.daily_pnl_usdt = 0.0
            self.position.day_start_ts = time.time()
            self.position.initial_mewc = mewc_available + mewc_held
            self.position.initial_usdt = usdt_available + usdt_held

    def record_fill(self, side: str, quantity: float, price: float, fee: float = 0.0) -> None:
        """Record a trade fill to track P&L."""
        if side == "buy":
            cost = quantity * price + fee
            self.position.daily_pnl_usdt -= cost
        else:
            revenue = quantity * price - fee
            self.position.daily_pnl_usdt += revenue

        logger.info(
            "FILL RECORDED side=%s qty=%.4f price=%.8f fee=%.6f daily_pnl=%.4f",
            side, quantity, price, fee, self.position.daily_pnl_usdt,
        )
        self._check_daily_loss()

    # -------------------------------------------------------------------------
    # Pre-order checks
    # -------------------------------------------------------------------------

    def check_can_place_orders(self, num_new_orders: int, existing_orders: int) -> bool:
        """Check whether we're within order-count limits."""
        if self._halted:
            logger.warning("Order blocked — bot is halted: %s", self._halt_reason)
            return False

        total = existing_orders + num_new_orders
        if total > self.cfg.max_open_orders:
            logger.warning(
                "Order limit: %d existing + %d new = %d > max %d",
                existing_orders, num_new_orders, total, self.cfg.max_open_orders,
            )
            return False
        return True

    def check_exposure(self, side: str, quantity: float, price: float) -> bool:
        """Check whether a proposed order would exceed exposure limits."""
        if self._halted:
            return False

        if side == "buy":
            # Check USDT exposure
            additional_usdt = quantity * price
            total_usdt = self.position.usdt_held + additional_usdt
            if total_usdt > self.cfg.max_usdt_exposure:
                logger.warning(
                    "USDT exposure limit: held=%.2f + new=%.2f = %.2f > max=%.2f",
                    self.position.usdt_held, additional_usdt, total_usdt,
                    self.cfg.max_usdt_exposure,
                )
                return False
        else:
            # Check MEWC exposure
            total_mewc = self.position.mewc_held + quantity
            if total_mewc > self.cfg.max_mewc_exposure:
                logger.warning(
                    "MEWC exposure limit: held=%.2f + new=%.2f = %.2f > max=%.2f",
                    self.position.mewc_held, quantity, total_mewc,
                    self.cfg.max_mewc_exposure,
                )
                return False

        return True

    def get_available_buy_budget(self) -> float:
        """Max USDT available for buy orders."""
        return self.position.usdt_balance * self.cfg.max_balance_usage_pct

    def get_available_sell_inventory(self) -> float:
        """Max MEWC available for sell orders."""
        return self.position.mewc_balance * self.cfg.max_balance_usage_pct

    # -------------------------------------------------------------------------
    # Inventory skew
    # -------------------------------------------------------------------------

    def compute_inventory_skew(self) -> float:
        """
        Compute an inventory skew offset for the spread.

        Returns a value between -1.0 and 1.0:
          - Positive = we hold too much MEWC -> widen ask spread, tighten bid
          - Negative = we hold too little MEWC -> tighten ask spread, widen bid

        The idea: if inventory is heavy on one side, we incentivise fills on
        the other side to rebalance.
        """
        if self.cfg.inventory_skew_factor == 0:
            return 0.0

        total_mewc = self.position.mewc_balance + self.position.mewc_held
        mid = self.position.last_mid_price

        if mid <= 0:
            return 0.0

        mewc_value_usdt = total_mewc * mid
        total_usdt = self.position.usdt_balance + self.position.usdt_held
        total_portfolio = mewc_value_usdt + total_usdt

        if total_portfolio <= 0:
            return 0.0

        # Ratio of MEWC value in total portfolio (0 to 1)
        mewc_ratio = mewc_value_usdt / total_portfolio
        # Neutral is configurable via inventory_target_ratio
        target = min(max(self.cfg.inventory_target_ratio, 0.0), 1.0)
        # Normalize by the furthest possible distance to keep range roughly [-1, 1]
        denom = max(target, 1.0 - target, 1e-9)
        skew = (mewc_ratio - target) / denom
        skew = max(min(skew, 1.0), -1.0)
        return skew * self.cfg.inventory_skew_factor

    # -------------------------------------------------------------------------
    # Internal checks
    # -------------------------------------------------------------------------

    def _check_daily_loss(self) -> None:
        """Halt if daily loss limit is breached."""
        if self.position.daily_pnl_usdt < self.cfg.daily_loss_limit_usdt:
            self.halt(
                f"Daily loss limit breached: {self.position.daily_pnl_usdt:.2f} USDT "
                f"< {self.cfg.daily_loss_limit_usdt:.2f} USDT"
            )

    def _check_stop_loss(self) -> None:
        """Check unrealized P&L stop-loss."""
        mid = self.position.last_mid_price
        if mid <= 0:
            return

        total_mewc = self.position.mewc_balance + self.position.mewc_held
        unrealized = (total_mewc - self.position.initial_mewc) * mid
        unrealized += (self.position.usdt_balance + self.position.usdt_held) - self.position.initial_usdt

        if unrealized < self.cfg.stop_loss_usdt:
            self.halt(
                f"Stop-loss triggered: unrealized P&L {unrealized:.2f} USDT "
                f"< {self.cfg.stop_loss_usdt:.2f} USDT"
            )

    def periodic_check(self) -> None:
        """Run periodic risk checks (call from main loop)."""
        self._check_daily_loss()
        self._check_stop_loss()
