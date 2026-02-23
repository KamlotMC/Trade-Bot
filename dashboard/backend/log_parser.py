"""Parse bot logs."""
import re
from typing import List, Dict, Optional
from pathlib import Path

class LogParser:
    def __init__(self, log_path: Optional[str] = None):
        if log_path is None:
            self.log_path = Path.home() / "Trade-Bot" / "logs" / "market_maker.log"
        else:
            self.log_path = Path(log_path)
    
    def get_errors(self, lines: int = 200) -> List[str]:
        """Get error lines from logs."""
        if not self.log_path.exists():
            return []
        
        try:
            with open(self.log_path, 'r') as f:
                log_lines = f.readlines()[-lines:]
            
            return [line.strip() for line in log_lines if 'ERROR' in line or 'Exception' in line][:10]
        except:
            return []
    
    def get_bot_status(self, lines: int = 100) -> Dict:
        """Get bot status from logs."""
        status = {
            "last_cycle": 0,
            "last_mid_price": 0,
            "last_skew": 0,
            "active_bids": 0,
            "active_asks": 0
        }
        
        if not self.log_path.exists():
            return status
        
        try:
            with open(self.log_path, 'r') as f:
                log_lines = f.readlines()[-lines:]
            
            active_orders = {}
            
            for line in reversed(log_lines):
                # Parse cycle number
                if not status["last_cycle"]:
                    cycle_match = re.search(r'Cycle #(\d+)', line)
                    if cycle_match:
                        status["last_cycle"] = int(cycle_match.group(1))
                
                # Parse mid price and skew (allow negative skew)
                if not status["last_mid_price"]:
                    mid_match = re.search(r'mid=([\d.]+)\s+skew=(-?[\d.]+)', line)
                    if mid_match:
                        status["last_mid_price"] = float(mid_match.group(1))
                        status["last_skew"] = float(mid_match.group(2))
                
                # Parse PLACED orders
                placed_match = re.search(r'PLACED\s+(BUY|SELL)\s+L\d+\s+price=([\d.]+)\s+qty=([\d.]+)\s+id=([a-zA-Z0-9_-]+)', line)
                if placed_match:
                    side, price, qty, order_id = placed_match.groups()
                    if order_id not in active_orders:
                        active_orders[order_id] = {
                            "id": order_id,
                            "side": side,
                            "price": float(price),
                            "quantity": float(qty)
                        }
                
                # Parse CANCELLED orders
                cancel_match = re.search(r'CANCEL ORDER\s+id=([a-zA-Z0-9_-]+)', line)
                if cancel_match:
                    order_id = cancel_match.group(1)
                    if order_id in active_orders:
                        del active_orders[order_id]
                
                # Break if we have what we need
                # Keep scanning to better reconstruct active orders.
            
            # Count active bids and asks
            status["active_bids"] = sum(1 for o in active_orders.values() if o["side"] == "BUY")
            status["active_asks"] = sum(1 for o in active_orders.values() if o["side"] == "SELL")
            
        except Exception as e:
            print(f"Log parser error: {e}")
        
        return status
    
    def get_open_orders_from_logs(self, lines: int = 200) -> List[Dict]:
        """Get open orders from logs."""
        orders = []
        
        if not self.log_path.exists():
            return orders
        
        try:
            with open(self.log_path, 'r') as f:
                log_lines = f.readlines()[-lines:]
            
            active_orders = {}
            
            for line in reversed(log_lines):
                # Parse PLACED orders
                placed_match = re.search(r'PLACED\s+(BUY|SELL)\s+L\d+\s+price=([\d.]+)\s+qty=([\d.]+)\s+id=([a-zA-Z0-9_-]+)', line)
                if placed_match:
                    side, price, qty, order_id = placed_match.groups()
                    if order_id not in active_orders:
                        active_orders[order_id] = {
                            "id": order_id,
                            "side": side,
                            "price": float(price),
                            "quantity": float(qty)
                        }
                
                # Parse CANCELLED orders
                cancel_match = re.search(r'CANCEL ORDER\s+id=([a-zA-Z0-9_-]+)', line)
                if cancel_match:
                    order_id = cancel_match.group(1)
                    if order_id in active_orders:
                        del active_orders[order_id]
            
            orders = list(active_orders.values())[:4]
            
        except Exception as e:
            print(f"Log parser error: {e}")
        
        return orders

    def get_order_lifecycle(self, lines: int = 400) -> List[Dict]:
        """Return recent order lifecycle events (placed/cancel)."""
        if not self.log_path.exists():
            return []

        events: List[Dict] = []
        try:
            with open(self.log_path, 'r') as f:
                log_lines = f.readlines()[-lines:]

            for line in log_lines:
                ts_match = re.match(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s*\|', line)
                ts = ts_match.group(1) if ts_match else ""

                placed = re.search(r'PLACED\s+(BUY|SELL)\s+L(\d+)\s+price=([\d.]+)\s+qty=([\d.]+)\s+id=([a-zA-Z0-9_-]+)', line)
                if placed:
                    side, level, price, qty, oid = placed.groups()
                    events.append({
                        "timestamp": ts,
                        "event": "placed",
                        "order_id": oid,
                        "side": side,
                        "level": int(level),
                        "price": float(price),
                        "quantity": float(qty),
                    })
                    continue

                canceled = re.search(r'CANCEL ORDER\s+id=([a-zA-Z0-9_-]+)', line)
                if canceled:
                    oid = canceled.group(1)
                    events.append({
                        "timestamp": ts,
                        "event": "canceled",
                        "order_id": oid,
                    })

        except Exception as e:
            print(f"Log parser error: {e}")

        return events[-80:]
