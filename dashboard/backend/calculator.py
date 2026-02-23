"""P&L calculations."""
from typing import Dict, List

class PnLCalculator:
    def __init__(self, data_store):
        self.store = data_store
    
    def get_current_pnl(self) -> Dict:
        """Calculate P&L for different periods using FIFO."""
        periods = {"daily": 1, "weekly": 7, "monthly": 30}
        result = {}
        
        for period_name, days in periods.items():
            trades = self.store.get_trades(limit=1000, days=days)
            
            # Calculate P&L using FIFO
            position = 0.0
            avg_buy_price = 0.0
            total_pnl = 0.0
            
            # Process trades in chronological order
            for trade in reversed(trades):
                side = trade.get("side", "").upper()
                qty = float(trade.get("quantity", 0))
                price = float(trade.get("price", 0))
                fee = float(trade.get("fee", 0))
                
                if side == "BUY" and qty > 0:
                    # Update average buy price
                    total_cost = (position * avg_buy_price) + (qty * price) + fee
                    position += qty
                    avg_buy_price = total_cost / position if position > 0 else 0
                elif side == "SELL" and position > 0 and qty > 0:
                    # Calculate P&L for this sell
                    revenue = (qty * price) - fee
                    cost = qty * avg_buy_price
                    pnl = revenue - cost
                    total_pnl += pnl
                    position -= qty
            
            profit = total_pnl if total_pnl > 0 else 0
            loss = abs(total_pnl) if total_pnl < 0 else 0
            
            result[period_name] = {
                "trades": len(trades),
                "profit": round(profit, 4),
                "loss": round(loss, 4),
                "net": round(total_pnl, 4)
            }
        
        return result
    
    def get_portfolio_value(self, balances_response: List, mewc_price: float) -> Dict:
        """Calculate portfolio value from balances."""
        try:
            def _f(v, default=0.0):
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return default

            def _asset_total(asset: str) -> float:
                total = 0.0
                for b in balances_response:
                    if b.get("asset") != asset:
                        continue
                    # Treat free/available and locked/held as aliases.
                    free = b.get("free")
                    available = b.get("available")
                    locked = b.get("locked")
                    held = b.get("held")
                    total += _f(free if free is not None else available)
                    total += _f(locked if locked is not None else held)
                return total

            mewc = _asset_total("MEWC")
            usdt = _asset_total("USDT")
            mewc_val = mewc * mewc_price
            total = mewc_val + usdt
            return {
                "mewc_balance": mewc,
                "mewc_value_usdt": mewc_val,
                "usdt_balance": usdt,
                "total_value_usdt": total,
                "mewc_percentage": (mewc_val / total * 100) if total > 0 else 0
            }
        except (TypeError, ValueError, AttributeError):
            return {
                "mewc_balance": 0,
                "mewc_value_usdt": 0,
                "usdt_balance": 0,
                "total_value_usdt": 0,
                "mewc_percentage": 0
            }
