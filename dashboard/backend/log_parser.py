"""Parse bot logs."""
import re
from typing import List, Dict, Optional
from pathlib import Path

from .paths import find_project_file

class LogParser:
    def __init__(self, log_path: Optional[str] = None):
        if log_path is None:
            self.log_path = find_project_file("logs", "market_maker.log")
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
        except Exception:
            return []
    
    def get_bot_status(self, lines: int = 0) -> Dict:
        """Get bot status from logs. lines=0 reads the entire file."""
        status = {
            "last_cycle": 0,
            "last_mid_price": 0,
            "last_skew": 0,
            "active_bids": 0,
            "active_asks": 0,
        }

        if not self.log_path.exists():
            return status

        try:
            with open(self.log_path, "rb") as f:
                raw = f.read()
            all_lines = raw.decode("utf-8", errors="replace").splitlines()
            log_lines = all_lines if lines == 0 else all_lines[-max(lines, 1):]

            active_orders: dict = {}
            prev_line = None

            for line in log_lines:
                # Skip exact duplicates (double-handler bug in bot logger)
                if line == prev_line:
                    prev_line = line
                    continue
                prev_line = line

                # Cycle number
                m = re.search(r'Cycle #(\d+)', line)
                if m:
                    status["last_cycle"] = int(m.group(1))

                # Mid price and skew
                m = re.search(r'mid=([\d.e+-]+)\s+skew=(-?[\d.e+-]+)', line)
                if m:
                    status["last_mid_price"] = float(m.group(1))
                    status["last_skew"] = float(m.group(2))

                # PLACED
                m = re.search(
                    r'PLACED\s+(BUY|SELL)\s+\S+\s+price=([\d.e+-]+)\s+qty=([\d.e+-]+)\s+id=([a-zA-Z0-9_-]+)',
                    line,
                )
                if m:
                    side, price, qty, oid = m.groups()
                    active_orders[oid] = {"side": side, "price": float(price), "quantity": float(qty)}
                    continue

                # CANCEL single
                m = re.search(r'CANCEL ORDER\s+id=([a-zA-Z0-9_-]+)', line)
                if m:
                    active_orders.pop(m.group(1), None)
                    continue

                # CANCEL ALL
                if re.search(r'CANCEL ALL ORDERS', line, re.IGNORECASE):
                    active_orders.clear()

            status["active_bids"] = sum(1 for o in active_orders.values() if o["side"] == "BUY")
            status["active_asks"] = sum(1 for o in active_orders.values() if o["side"] == "SELL")

        except Exception as e:
            import logging as _log
            _log.getLogger(__name__).warning("get_bot_status error: %s", e)

        return status
    
    def get_open_orders_from_logs(self, lines: int = 0) -> List[Dict]:
        """Get open orders by replaying the full log (PLACED minus CANCELLED).
        
        lines=0 means read the entire log file.
        Handles both 'CANCEL ORDER id=xxx' and 'CANCEL ALL ORDERS' patterns.
        """
        if not self.log_path.exists():
            return []

        try:
            with open(self.log_path, "rb") as f:
                raw = f.read()
            all_lines = raw.decode("utf-8", errors="replace").splitlines()
            log_lines = all_lines if lines == 0 else all_lines[-max(lines, 1):]

            active_orders: dict = {}

            for line in log_lines:
                # PLACED order
                placed = re.search(
                    r'PLACED\s+(BUY|SELL)\s+\S+\s+price=([\d.e+-]+)\s+qty=([\d.e+-]+)\s+id=([a-zA-Z0-9_-]+)',
                    line,
                )
                if placed:
                    side, price, qty, oid = placed.groups()
                    active_orders[oid] = {
                        "id": oid,
                        "side": side,
                        "price": float(price),
                        "quantity": float(qty),
                        "remaining": float(qty),
                        "status": "OPEN",
                    }
                    continue

                # CANCEL single order
                cancel_single = re.search(r'CANCEL ORDER\s+id=([a-zA-Z0-9_-]+)', line)
                if cancel_single:
                    active_orders.pop(cancel_single.group(1), None)
                    continue

                # CANCEL ALL ORDERS — wipe everything placed before this line
                if re.search(r'CANCEL ALL ORDERS', line, re.IGNORECASE):
                    active_orders.clear()

            return list(active_orders.values())

        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("get_open_orders_from_logs error: %s", e)
            return []

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
