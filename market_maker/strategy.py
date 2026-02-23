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
from datetime import datetime
from typing import Dict, List, Optional

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
        self._active_orders: Dict[str, QuoteLevel] = {}
        self._running = False
        self._cycle_count = 0
        self._mid_history: List[float] = []
        self._recent_realized: List[float] = []
        self._last_fill_count = 0

    # -------------------------------------------------------------------------
    # Main loop
    # -------------------------------------------------------------------------

    def run(self, stop_event=None) -> None:
        """Start the market-making loop.

        Args:
            stop_event: optional ``threading.Event`` that, when set, tells
                        the bot to exit promptly (used by the GUI).
        """
        logger.info("=" * 60)
        logger.info("  Meowcoin Market Maker starting")
        logger.info("  Symbol:  %s", self.exchange_cfg.symbol)
        logger.info("  Spread:  %.2f%%", self.cfg.spread_pct * 100)
        logger.info("  Levels:  %d per side", self.cfg.num_levels)
        logger.info("  Refresh: %ds", self.cfg.refresh_interval_sec)
        logger.info("=" * 60)

        self._running = True
        try:
            # Validate credentials before doing anything else
            logger.info("Testing API connection...")
            conn = self.client.test_connection()
            if not conn["ok"]:
                logger.error("Connection test failed: %s", conn["error"])
                raise RuntimeError(conn["error"])

            # Load market precision metadata
            logger.info("Loading market metadata for %s...", self.exchange_cfg.symbol)
            self.client.load_market_metadata()

            while self._running:
                self._cycle()
                # Use stop_event for responsive shutdown when available
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
            raise  # Re-raise so main() can show the error to the user
        finally:
            self._shutdown()

    def stop(self) -> None:
        """Signal the loop to stop after the current cycle."""
        self._running = False

    # -------------------------------------------------------------------------
    # Single refresh cycle
    # -------------------------------------------------------------------------

    def _cycle(self) -> None:
        """Execute one complete refresh cycle."""
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
        except Exception as e:
            logger.error("Error fetching balances: %s", e)
            return

        # 4. Detect fill-like changes and execution quality stats
        self._record_execution_quality_snapshot(mid_price)

        # 5. Compute quotes
        quotes = self._compute_quotes(mid_price)
        if not quotes:
            logger.info("No quotes to place this cycle")
            return

        # 6. Reprice only when stale (queue-position aware refresh)
        self._reprice_orders(quotes, mid_price)

    # -------------------------------------------------------------------------
    # Price discovery
    # -------------------------------------------------------------------------

    def _get_mid_price(self) -> Optional[float]:
        """
        Calculate the mid-price from the orderbook.
        Falls back to last trade price if the book is empty on one side.
        """
        ob = self.client.get_orderbook(limit=5)
        bids = ob.get("bids", [])
        asks = ob.get("asks", [])

        best_bid = float(bids[0]["price"]) if bids else None
        best_ask = float(asks[0]["price"]) if asks else None

        if best_bid and best_ask:
            mid = (best_bid + best_ask) / 2.0
            logger.debug("Orderbook mid: %.8f  (bid=%.8f ask=%.8f)", mid, best_bid, best_ask)
            return mid

        # Fallback: use last traded price
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
        """Fetch balances and update the risk manager."""
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
        """
        Build a list of bid and ask quotes at multiple levels around mid.

        Incorporates inventory skew: if we're long MEWC, the ask spread narrows
        and the bid spread widens (to encourage selling MEWC back).
        """
        self._mid_history.append(mid_price)
        if len(self._mid_history) > 60:
            self._mid_history = self._mid_history[-60:]

        skew = self.risk.compute_inventory_skew()
        effective_spread = self._adaptive_spread(mid_price)
        orderbook = None
        try:
            orderbook = self.client.get_orderbook(limit=10)
        except Exception:
            orderbook = None

        imbalance = self._orderbook_imbalance_skew(orderbook)
        total_skew = max(min(skew + imbalance, 1.0), -1.0)

        # Capital allocation bands: stop quoting one side at extremes.
        inv_ratio = self.risk.get_inventory_ratio()
        target = min(max(self.risk.cfg.inventory_target_ratio, 0.0), 1.0)
        low_band = min(max(getattr(self.risk.cfg, "inventory_band_low", max(0.0, target - 0.2)), 0.0), 1.0)
        high_band = min(max(getattr(self.risk.cfg, "inventory_band_high", min(1.0, target + 0.2)), 0.0), 1.0)
        if low_band > high_band:
            low_band, high_band = high_band, low_band
        allow_buy = inv_ratio < high_band
        allow_sell = inv_ratio > low_band

        # Dynamic sizing by inventory pressure.
        pressure = abs(inv_ratio - target) / max(target, 1 - target, 1e-9)
        size_mult_buy = max(0.5, 1.0 - pressure) if inv_ratio > target else min(1.5, 1.0 + pressure)
        size_mult_sell = max(0.5, 1.0 - pressure) if inv_ratio < target else min(1.5, 1.0 + pressure)

        buy_budget = self.risk.get_available_buy_budget()
        sell_inventory = self.risk.get_available_sell_inventory()

        quotes: List[QuoteLevel] = []

        for level in range(self.cfg.num_levels):
            offset = effective_spread + (level * self.cfg.level_step_pct)
            qty = self.cfg.base_quantity * (self.cfg.quantity_multiplier ** level)

            # --- BID (buy) ---
            bid_offset = offset + (total_skew * effective_spread * 0.5)  # Widen if long
            bid_price = mid_price * (1.0 - bid_offset)
            bid_qty = qty * size_mult_buy
            bid_cost = bid_qty * bid_price

            # Ensure order meets exchange minimum value
            if bid_price > 0 and bid_cost < self.cfg.min_order_value_usdt:
                bid_qty = self.cfg.min_order_value_usdt / bid_price * 1.05  # 5% buffer
                bid_cost = bid_qty * bid_price

            if bid_price < self.cfg.min_bid_price and self.cfg.min_bid_price > 0:
                logger.debug("Bid L%d price %.8f below min_bid_price %.4f — skipping",
                             level, bid_price, self.cfg.min_bid_price)
                bid_allowed = False
            else:
                bid_allowed = True

            # Maker-only safeguard + capital allocation bands.
            if orderbook and orderbook.get("asks"):
                try:
                    best_ask = float(orderbook["asks"][0]["price"])
                    if bid_price >= best_ask:
                        bid_allowed = False
                except Exception:
                    pass
            bid_allowed = bid_allowed and allow_buy

            if bid_allowed and bid_cost <= buy_budget and bid_price > 0:
                if self.risk.check_exposure("buy", bid_qty, bid_price):
                    quotes.append(QuoteLevel(
                        side="buy", price=bid_price, quantity=bid_qty, level=level,
                    ))
                    buy_budget -= bid_cost

            # --- ASK (sell) ---
            ask_offset = offset - (total_skew * effective_spread * 0.5)  # Tighten if long
            ask_offset = max(ask_offset, self.cfg.min_spread_pct)  # Floor
            ask_price = mid_price * (1.0 + ask_offset)

            # Reset qty for ask side (recalculate from base)
            ask_qty = self.cfg.base_quantity * (self.cfg.quantity_multiplier ** level) * size_mult_sell

            # Ensure order meets exchange minimum value
            if ask_price > 0 and (ask_qty * ask_price) < self.cfg.min_order_value_usdt:
                ask_qty = self.cfg.min_order_value_usdt / ask_price * 1.05

            ask_allowed = allow_sell
            if orderbook and orderbook.get("bids"):
                try:
                    best_bid = float(orderbook["bids"][0]["price"])
                    if ask_price <= best_bid:
                        ask_allowed = False
                except Exception:
                    pass

            if ask_allowed and ask_qty <= sell_inventory and ask_price > 0:
                if self.risk.check_exposure("sell", ask_qty, ask_price):
                    quotes.append(QuoteLevel(
                        side="sell", price=ask_price, quantity=ask_qty, level=level,
                    ))
                    sell_inventory -= ask_qty

        logger.info(
            "Quotes computed: %d bids + %d asks | mid=%.8f skew=%.4f spread=%.4f inv=%.3f",
            sum(1 for q in quotes if q.side == "buy"),
            sum(1 for q in quotes if q.side == "sell"),
            mid_price, total_skew, effective_spread, inv_ratio,
        )
        return quotes

    def _adaptive_spread(self, mid_price: float) -> float:
        """Adaptive spread by recent volatility + microtrend."""
        base = max(self.cfg.spread_pct, self.cfg.min_spread_pct)
        if not getattr(self.cfg, "adaptive_spread_enabled", True):
            return base

        lookback = max(int(getattr(self.cfg, "volatility_lookback", 10)), 4)
        trend_lb = max(int(getattr(self.cfg, "trend_lookback", 10)), 2)

        if len(self._mid_history) < lookback:
            return base
        recent = self._mid_history[-lookback:]
        hi = max(recent)
        lo = min(recent)
        vol = (hi - lo) / mid_price if mid_price > 0 else 0
        trend_slice = self._mid_history[-trend_lb:]
        trend = (trend_slice[-1] - trend_slice[0]) / trend_slice[0] if trend_slice[0] > 0 else 0
        # Widen on volatility; nudge wider on strong trend to reduce adverse selection.
        spread = base * (1.0 + min(vol * 8.0, 1.5) + min(abs(trend) * 2.0, 0.5))
        return max(self.cfg.min_spread_pct, spread)

    def _orderbook_imbalance_skew(self, orderbook: Optional[dict] = None) -> float:
        """Compute additional skew from top book imbalance."""
        if not getattr(self.cfg, "imbalance_skew_enabled", True):
            return 0.0
        try:
            ob = orderbook or self.client.get_orderbook(limit=10)
            bids = ob.get("bids", [])[:5]
            asks = ob.get("asks", [])[:5]
            bid_vol = sum(float(b.get("quantity", 0)) for b in bids)
            ask_vol = sum(float(a.get("quantity", 0)) for a in asks)
            total = bid_vol + ask_vol
            if total <= 0:
                return 0.0
            imbalance = (bid_vol - ask_vol) / total
            return max(min(imbalance * 0.3, 0.3), -0.3)
        except Exception:
            return 0.0

    def _reprice_orders(self, quotes: List[QuoteLevel], mid_price: float) -> None:
        """Queue-aware refresh: replace only stale quotes."""
        if not self._active_orders:
            self._place_orders(quotes)
            return

        desired = {(q.side, q.level): q for q in quotes}
        stale = []
        for oid, old in list(self._active_orders.items()):
            new = desired.get((old.side, old.level))
            if new is None:
                stale.append(oid)
                continue
            price_move = abs(new.price - old.price) / old.price if old.price > 0 else 1
            threshold = max(float(getattr(self.cfg, "queue_reprice_threshold_pct", 0.002)), 0.0001)
            if price_move > threshold:
                stale.append(oid)

        for oid in stale:
            try:
                self.client.cancel_order(oid)
                self._active_orders.pop(oid, None)
                if oid in self._active_order_ids:
                    self._active_order_ids.remove(oid)
            except Exception as e:
                logger.debug("Reprice cancel failed %s: %s", oid, e)

        # place missing/updated orders
        existing_keys = {(q.side, q.level) for q in self._active_orders.values()}
        to_place = [q for q in quotes if (q.side, q.level) not in existing_keys]
        if to_place:
            self._place_orders(to_place)

    def _record_execution_quality_snapshot(self, mid_price: float) -> None:
        """Execution quality module from balance-detected fills."""
        # Placeholder for future exchange fills endpoint integration.
        pass

    # -------------------------------------------------------------------------
    # Order placement
    # -------------------------------------------------------------------------

    def _place_orders(self, quotes: List[QuoteLevel]) -> None:
        """Place all computed quotes as limit orders."""
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

                result = self.client.create_order(
                    side=q.side,
                    quantity=qty_str,
                    price=price_str,
                )

                order_id = result.get("id")
                if order_id:
                    self._active_order_ids.append(order_id)
                    self._active_orders[order_id] = q
                    placed += 1
                    logger.info(
                        "PLACED  %s L%d  price=%s qty=%s  id=%s",
                        q.side.upper(), q.level, price_str, qty_str, order_id,
                    )
            except Exception as e:
                logger.error("Failed to place %s order at %s: %s", q.side, q.price, e)

        logger.info("Placed %d / %d orders", placed, len(quotes))

    # -------------------------------------------------------------------------
    # Order cancellation
    # -------------------------------------------------------------------------

    def _cancel_all(self) -> None:
        """Cancel all bot-placed orders for the trading pair."""
        if not self._active_order_ids:
            # Use the bulk cancel as a safety sweep
            try:
                self.client.cancel_all_orders()
            except Exception as e:
                logger.error("Error in bulk cancel: %s", e)
            return

        cancelled = 0
        for oid in self._active_order_ids:
            try:
                self.client.cancel_order(oid)
                cancelled += 1
            except Exception as e:
                logger.debug("Cancel order %s failed (may already be filled): %s", oid, e)

        logger.info("Cancelled %d / %d tracked orders", cancelled, len(self._active_order_ids))
        self._active_order_ids.clear()
        self._active_orders.clear()

    # -------------------------------------------------------------------------
    # Shutdown
    # -------------------------------------------------------------------------

    def _shutdown(self) -> None:
        """Clean shutdown — cancel all orders."""
        logger.info("Shutting down — cancelling all open orders...")
        try:
            self.client.cancel_all_orders()
        except Exception as e:
            logger.error("Error cancelling orders during shutdown: %s", e)
        self._active_order_ids.clear()
        self._active_orders.clear()
        logger.info("Market Maker stopped. Total cycles: %d", self._cycle_count)


    def _detect_fills_from_balances(self, prev_bal: dict, curr_bal: dict) -> list:
        """Detect fills by comparing balance changes between cycles."""
        fills = []
        try:
            prev_mewc = prev_bal.get("MEWC", {}).get("available", 0) + prev_bal.get("MEWC", {}).get("held", 0)
            prev_usdt = prev_bal.get("USDT", {}).get("available", 0) + prev_bal.get("USDT", {}).get("held", 0)
            curr_mewc = curr_bal.get("MEWC", {}).get("available", 0) + curr_bal.get("MEWC", {}).get("held", 0)
            curr_usdt = curr_bal.get("USDT", {}).get("available", 0) + curr_bal.get("USDT", {}).get("held", 0)
            
            mewc_delta = curr_mewc - prev_mewc
            usdt_delta = curr_usdt - prev_usdt
            
            # Thresholds to ignore small changes
            if abs(mewc_delta) < 1000 or abs(usdt_delta) < 0.01:
                return fills
            
            # Detect SELL: MEWC down, USDT up
            if mewc_delta < -1000 and usdt_delta > 0.01:
                price = abs(usdt_delta / mewc_delta)
                fills.append({"side": "SELL", "quantity": abs(mewc_delta), "price": price, "timestamp": datetime.now().isoformat()})
                logger.info("🟢 Detected SELL: %.0f MEWC @ %.8f", abs(mewc_delta), price)
            # Detect BUY: MEWC up, USDT down
            elif mewc_delta > 1000 and usdt_delta < -0.01:
                price = abs(usdt_delta / mewc_delta)
                fills.append({"side": "BUY", "quantity": mewc_delta, "price": price, "timestamp": datetime.now().isoformat()})
                logger.info("🔴 Detected BUY: %.0f MEWC @ %.8f", mewc_delta, price)
        except Exception as e:
            logger.error("Fill detection error: %s", e)
        return fills

    def _save_fill_to_db(self, fill: dict):
        """Save detected fill to database."""
        try:
            import sqlite3
            from pathlib import Path
            db_path = Path(__file__).parent.parent / "data.db"
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            c.execute("INSERT INTO trades (timestamp, side, quantity, price, fee, pnl, order_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (fill["timestamp"], fill["side"], fill["quantity"], fill["price"], 0, 0, f"detected_{int(datetime.now().timestamp())}"))
            conn.commit()
            conn.close()
            logger.info("💾 Saved fill: %s %.0f @ %.8f", fill["side"], fill["quantity"], fill["price"])
        except Exception as e:
            logger.error("Save fill error: %s", e)
