"""
Market-making strategy for MEWC/USDT on NonKYC exchange.

Implements a symmetric spread-based market maker with:
  - Configurable multi-level order placement
  - Inventory-aware quote skewing
  - Automatic order refresh cycle
"""

import logging
import time
from dataclasses import dataclass
from typing import List, Optional

from market_maker.config import StrategyConfig, BotConfig
from market_maker.exchange_client import NonKYCClient
from market_maker.risk_manager import RiskManager

logger = logging.getLogger("mewc_mm.strategy")


@dataclass
class QuoteLevel:
    """A single price/quantity level to be placed on the book."""
    side: str          # "buy" or "sell"
    price: float
    quantity: float
    level: int         # 0 = closest to mid


class MarketMaker:
    """
    Core market-making engine.

    On each refresh cycle:
      1. Fetch current orderbook mid-price
      2. Cancel all existing bot orders
      3. Compute new bid/ask quotes with inventory skew
      4. Place new orders respecting risk limits
    """

    def __init__(self, config: BotConfig, client: NonKYCClient, risk: RiskManager):
        self.cfg = config.strategy
        self.exchange_cfg = config.exchange
        self.client = client
        self.risk = risk
        self._active_order_ids: List[str] = []
        self._running = False
        self._cycle_count = 0

    # -------------------------------------------------------------------------
    # Execution quality snapshot (RiskManager compatible)
    # -------------------------------------------------------------------------

    def _record_execution_quality_snapshot(self, mid_price: float) -> None:
        """
        Record a snapshot of execution quality using current RiskManager state.
        Compatible with your RiskManager.
        """
        if not hasattr(self, "risk"):
            return

        rm = self.risk
        mewc_bal = rm.position.mewc_balance
        usdt_bal = rm.position.usdt_balance
        mewc_held = rm.position.mewc_held
        usdt_held = rm.position.usdt_held
        daily_pnl = rm.position.daily_pnl_usdt
        inventory_ratio = rm.get_inventory_ratio()

        logger.debug(
            "Execution snapshot — mid_price=%.8f, MEWC=%.4f (held %.4f), USDT=%.4f (held %.4f), daily_pnl=%.4f, inv_ratio=%.4f",
            mid_price, mewc_bal, mewc_held, usdt_bal, usdt_held, daily_pnl, inventory_ratio
        )

    # -------------------------------------------------------------------------
    # Main loop
    # -------------------------------------------------------------------------

    def run(self, stop_event=None) -> None:
        """Start the market-making loop."""
        logger.info("=" * 60)
        logger.info("  Meowcoin Market Maker starting")
        logger.info("  Symbol:  %s", self.exchange_cfg.symbol)
        logger.info("  Spread:  %.2f%%", self.cfg.spread_pct * 100)
        logger.info("  Levels:  %d per side", self.cfg.num_levels)
        logger.info("  Refresh: %ds", self.cfg.refresh_interval_sec)
        logger.info("=" * 60)

        self._running = True
        try:
            logger.info("Testing API connection...")
            conn = self.client.test_connection()
            if not conn["ok"]:
                logger.error("Connection test failed: %s", conn["error"])
                raise RuntimeError(conn["error"])

            logger.info("Loading market metadata for %s...", self.exchange_cfg.symbol)
            self.client.load_market_metadata()

            while self._running:
                self._cycle()
                if stop_event is not None:
                    stop_event.wait(timeout=self.cfg.refresh_interval_sec)
                    if stop_event.is_set():
                        self._running = False
                else:
                    time.sleep(self.cfg.refresh_interval_sec)
        except KeyboardInterrupt:
            logger.info("Shutdown requested by user (Ctrl+C)")
        except Exception as e:
            logger.exception("Fatal error in main loop: %s", e)
            raise
        finally:
            self._shutdown()

    def stop(self) -> None:
        self._running = False

    # -------------------------------------------------------------------------
    # Single refresh cycle
    # -------------------------------------------------------------------------

    def _cycle(self) -> None:
        self._cycle_count += 1
        logger.info("--- Cycle #%d ---", self._cycle_count)

        # 1. Risk check
        self.risk.periodic_check()
        if self.risk.is_halted:
            logger.warning("Bot is halted: %s — skipping cycle", self.risk.halt_reason)
            self._cancel_all()
            return

        # 2. Fetch data
        try:
            mid_price = self._get_mid_price()
            if mid_price is None or mid_price <= 0:
                logger.warning("Cannot determine mid-price — skipping cycle")
                return
        except Exception as e:
            logger.error("Error fetching orderbook: %s", e)
            return

        # 3. Update balances & risk state
        try:
            self._refresh_balances(mid_price)
            self._record_execution_quality_snapshot(mid_price)
        except Exception as e:
            logger.error("Error fetching balances: %s", e)
            return

        # 4. Check for filled orders and record P&L
        self._check_and_record_fills()

        # 5. Cancel existing orders
        self._cancel_all()

        # 6. Compute quotes
        quotes = self._compute_quotes(mid_price)
        if not quotes:
            logger.info("No quotes to place this cycle")
            return

        # 7. Place orders
        self._place_orders(quotes)

    # -------------------------------------------------------------------------
    # Price discovery
    # -------------------------------------------------------------------------

    def _get_mid_price(self) -> Optional[float]:
        ob = self.client.get_orderbook(limit=5)
        bids = ob.get("bids", [])
        asks = ob.get("asks", [])

        best_bid = float(bids[0]["price"]) if bids else None
        best_ask = float(asks[0]["price"]) if asks else None

        if best_bid and best_ask:
            mid = (best_bid + best_ask) / 2.0
            logger.debug("Orderbook mid: %.8f  (bid=%.8f ask=%.8f)", mid, best_bid, best_ask)
            return mid

        try:
            ticker = self.client.get_ticker()
            last = float(ticker.get("last_price", 0))
            if last > 0:
                logger.debug("Using last trade price as mid: %.8f", last)
                return last
        except Exception:
            pass

        return None

    # -------------------------------------------------------------------------
    # Balance refresh
    # -------------------------------------------------------------------------

    def _refresh_balances(self, mid_price: float) -> None:
        mewc = self.client.get_balance("MEWC")
        usdt = self.client.get_balance("USDT")

        self.risk.update_balances(
            mewc_available=float(mewc.get("available", 0)),
            mewc_held=float(mewc.get("held", 0)),
            usdt_available=float(usdt.get("available", 0)),
            usdt_held=float(usdt.get("held", 0)),
            mid_price=mid_price,
        )

        logger.info(
            "Balances — MEWC: %.2f avail / %.2f held | USDT: %.4f avail / %.4f held",
            float(mewc.get("available", 0)), float(mewc.get("held", 0)),
            float(usdt.get("available", 0)), float(usdt.get("held", 0)),
        )

    # -------------------------------------------------------------------------
    # Quote computation
    # -------------------------------------------------------------------------

    def _compute_quotes(self, mid_price: float) -> List[QuoteLevel]:
        skew = self.risk.compute_inventory_skew()
        effective_spread = max(self.cfg.spread_pct, self.cfg.min_spread_pct)
        buy_budget = self.risk.get_available_buy_budget()
        sell_inventory = self.risk.get_available_sell_inventory()

        quotes: List[QuoteLevel] = []

        for level in range(self.cfg.num_levels):
            offset = effective_spread + (level * self.cfg.level_step_pct)
            qty = self.cfg.base_quantity * (self.cfg.quantity_multiplier ** level)

            # BID
            bid_offset = offset + (skew * effective_spread * 0.5)
            bid_price = mid_price * (1.0 - bid_offset)
            bid_cost = qty * bid_price
            if bid_price > 0 and bid_cost < self.cfg.min_order_value_usdt:
                qty = self.cfg.min_order_value_usdt / bid_price * 1.05
                bid_cost = qty * bid_price
            # Enforce minimum bid price floor
            if self.cfg.min_bid_price > 0 and bid_price < self.cfg.min_bid_price:
                logger.debug("Bid price %.8f below min_bid_price %.8f — skipping level %d", bid_price, self.cfg.min_bid_price, level)
                bid_price = 0  # skip this level
            if bid_cost <= buy_budget and bid_price > 0:
                if self.risk.check_exposure("buy", qty, bid_price):
                    quotes.append(QuoteLevel(side="buy", price=bid_price, quantity=qty, level=level))
                    buy_budget -= bid_cost

            # ASK
            ask_offset = offset - (skew * effective_spread * 0.5)
            ask_offset = max(ask_offset, self.cfg.min_spread_pct)
            ask_price = mid_price * (1.0 + ask_offset)
            ask_qty = self.cfg.base_quantity * (self.cfg.quantity_multiplier ** level)
            if ask_price > 0 and (ask_qty * ask_price) < self.cfg.min_order_value_usdt:
                ask_qty = self.cfg.min_order_value_usdt / ask_price * 1.05
            if ask_qty <= sell_inventory and ask_price > 0:
                if self.risk.check_exposure("sell", ask_qty, ask_price):
                    quotes.append(QuoteLevel(side="sell", price=ask_price, quantity=ask_qty, level=level))
                    sell_inventory -= ask_qty

        logger.info(
            "Quotes computed: %d bids + %d asks | mid=%.8f skew=%.4f",
            sum(1 for q in quotes if q.side == "buy"),
            sum(1 for q in quotes if q.side == "sell"),
            mid_price, skew,
        )
        return quotes

    def _check_and_record_fills(self) -> None:
        """Check tracked orders for fills and record realized P&L to RiskManager.

        Compares active_order_ids against current open orders from exchange.
        Any tracked order that is no longer open has been filled (or cancelled).
        We poll its status to distinguish fill from cancel and record P&L.
        """
        if not self._active_order_ids:
            return

        try:
            open_orders_raw = self.client.get_active_orders(symbol=self.exchange_cfg.symbol)
            open_ids = set()
            if isinstance(open_orders_raw, list):
                for o in open_orders_raw:
                    oid = str(o.get("id") or o.get("orderId") or "")
                    if oid:
                        open_ids.add(oid)
        except Exception as e:
            logger.debug("Could not fetch active orders for fill check: %s", e)
            return

        for oid in list(self._active_order_ids):
            if oid in open_ids:
                continue  # still open
            # Order is gone — check if it was filled
            try:
                order = self.client.get_order(oid)
                status = str(order.get("status") or order.get("state") or "").upper()
                side = str(order.get("side") or "").lower()
                filled_qty = float(order.get("filled") or order.get("executedQty") or order.get("cumQty") or 0)
                price = float(order.get("price") or order.get("avgPrice") or order.get("rate") or 0)
                fee_rate = float(self.exchange_cfg.fee_maker_pct) if hasattr(self.exchange_cfg, 'fee_maker_pct') else 0.002
                fee = filled_qty * price * fee_rate

                if status in ("FILLED", "PARTIALLY_FILLED") and filled_qty > 0 and price > 0:
                    self.risk.record_fill(side=side, quantity=filled_qty, price=price, fee=fee)
                    logger.info(
                        "FILL DETECTED  id=%s  side=%s  qty=%.2f  price=%.8f  fee=%.6f",
                        oid, side, filled_qty, price, fee,
                    )
            except Exception as e:
                logger.debug("Could not fetch order %s for fill check: %s", oid, e)

    # -------------------------------------------------------------------------
    # Order placement & cancellation
    # -------------------------------------------------------------------------

    def _place_orders(self, quotes: List[QuoteLevel]) -> None:
        existing = len(self._active_order_ids)
        if not self.risk.check_can_place_orders(len(quotes), existing):
            logger.warning("Risk check blocked order placement")
            return

        placed = 0
        for q in quotes:
            try:
                price_str = self.client.format_price(q.price)
                qty_str = self.client.format_quantity(q.quantity)
                if float(qty_str) <= 0 or float(price_str) <= 0:
                    continue
                result = self.client.create_order(side=q.side, quantity=qty_str, price=price_str)
                order_id = result.get("id")
                if order_id:
                    self._active_order_ids.append(order_id)
                    placed += 1
                    logger.info(
                        "PLACED  %s L%d  price=%s qty=%s  id=%s",
                        q.side.upper(), q.level, price_str, qty_str, order_id,
                    )
            except Exception as e:
                logger.error("Failed to place %s order at %s: %s", q.side, q.price, e)

        logger.info("Placed %d / %d orders", placed, len(quotes))

    def _cancel_all(self) -> None:
        cancelled = 0
        for oid in self._active_order_ids:
            try:
                self.client.cancel_order(oid)
                cancelled += 1
            except Exception as e:
                logger.debug("Cancel order %s failed (may already be filled): %s", oid, e)

        if self._active_order_ids:
            logger.info("Cancelled %d / %d tracked orders", cancelled, len(self._active_order_ids))

        self._active_order_ids.clear()

        # Safety net: bulk cancel catches any orphaned orders (placed without returned ID)
        try:
            self.client.cancel_all_orders()
        except Exception as e:
            logger.debug("Bulk safety-cancel: %s", e)

    def _shutdown(self) -> None:
        logger.info("Shutting down — cancelling all open orders...")
        try:
            self.client.cancel_all_orders()
        except Exception as e:
            logger.error("Error cancelling orders during shutdown: %s", e)
        self._active_order_ids.clear()
        logger.info("Market Maker stopped. Total cycles: %d", self._cycle_count)
