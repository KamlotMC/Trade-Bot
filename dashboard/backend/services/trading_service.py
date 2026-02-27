from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class TradingService:
    api_client: Any
    data_store: Any

    @staticmethod
    def _sf(val: Any, default: float = 0.0) -> float:
        try:
            if val is None:
                return default
            return float(val)
        except (ValueError, TypeError):
            return default

    def get_open_orders(self, symbol: str = "MEWC_USDT") -> List[Dict[str, Any]]:
        result = self.api_client.get_open_orders(symbol)

        # Handle error response
        if isinstance(result, dict) and "error" in result:
            return []

        # Normalize all possible response shapes to a flat list
        if isinstance(result, list):
            rows = result
        elif isinstance(result, dict):
            # Try common wrapper keys in order of preference
            for key in ("orders", "data", "result", "items"):
                val = result.get(key)
                if isinstance(val, list):
                    rows = val
                    break
            else:
                # If no wrapper key found, treat the dict values as a list
                rows = []
        else:
            rows = []

        if not rows:
            return []

        normalized = []
        closed_statuses = {"FILLED", "CANCELED", "CANCELLED", "REJECTED", "EXPIRED", "CLOSED"}
        open_statuses = {"OPEN", "NEW", "PARTIALLY_FILLED", "PARTIAL", "ACTIVE"}

        for order in rows:
            if not isinstance(order, dict):
                continue
            side = str(order.get("side") or order.get("type") or "").upper()
            price_val = self._sf(order.get("price") or order.get("rate") or order.get("limitPrice"))
            qty_val = self._sf(order.get("quantity") or order.get("origQty") or order.get("qty") or order.get("amount"))
            status = str(order.get("status") or order.get("state") or "OPEN").upper()
            filled = self._sf(order.get("filled") or order.get("executedQty") or order.get("cumQty"))

            remaining_raw = order.get("remaining") or order.get("leavesQty") or order.get("openQty")
            remaining = self._sf(remaining_raw, max(qty_val - filled, 0.0))
            if remaining <= 0 and qty_val > filled:
                remaining = max(qty_val - filled, 0.0)

            oid = str(order.get("id") or order.get("orderId") or order.get("clientOrderId") or "")
            normalized.append(
                {
                    "id": oid,
                    "side": side,
                    "price": price_val,
                    "quantity": qty_val,
                    "remaining": remaining,
                    "status": status,
                    "symbol": order.get("symbol", symbol),
                }
            )

        return [
            o
            for o in normalized
            if (o["status"] in open_statuses)
            or (o["status"] not in closed_statuses and o["remaining"] > 0)
        ]

    def cancel_open_order(self, order_id: str) -> Dict[str, Any]:
        result = self.api_client.cancel_order(order_id)
        ok = "error" not in result if isinstance(result, dict) else True
        return {"ok": ok, "order_id": order_id, "result": result}

    def get_orderbook(self, symbol: str = "MEWC_USDT", limit: int = 20) -> Dict[str, Any]:
        result = self.api_client.get_orderbook(symbol, limit=max(5, min(limit, 60)))
        if isinstance(result, dict) and "error" in result:
            return {"bids": [], "asks": [], "error": result.get("error")}

        bids = result.get("bids", []) if isinstance(result, dict) else []
        asks = result.get("asks", []) if isinstance(result, dict) else []

        def normalize(levels: List[Any]) -> List[Dict[str, float]]:
            out = []
            for lvl in levels:
                if isinstance(lvl, dict):
                    p = self._sf(lvl.get("price") or lvl.get("rate"))
                    q = self._sf(lvl.get("quantity") or lvl.get("qty") or lvl.get("amount"))
                elif isinstance(lvl, (list, tuple)) and len(lvl) >= 2:
                    p = self._sf(lvl[0])
                    q = self._sf(lvl[1])
                else:
                    continue
                out.append({"price": p, "quantity": q})
            return out

        return {"bids": normalize(bids), "asks": normalize(asks)}

    def close_trade(self, trade_id: int, symbol: str = "MEWC_USDT") -> Dict[str, Any]:
        trades = self.data_store.get_trades(1000, 365)
        target = next((t for t in trades if int(t.get("id", -1)) == trade_id), None)
        if not target:
            return {"ok": False, "error": "Trade not found"}

        side = str(target.get("side", "")).upper()
        if side not in {"BUY", "SELL"}:
            return {"ok": False, "error": "Unknown trade side"}

        qty = self._sf(target.get("quantity"))
        close_side = "SELL" if side == "BUY" else "BUY"
        result = self.api_client.create_market_order(close_side, qty, symbol)
        ok = "error" not in result if isinstance(result, dict) else True

        return {
            "ok": ok,
            "trade_id": trade_id,
            "close_side": close_side,
            "quantity": qty,
            "result": result,
        }
