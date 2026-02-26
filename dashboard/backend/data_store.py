"""Data storage for trades and portfolio snapshots."""
import hashlib
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

class DataStore:
    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            db_path = Path(__file__).parent.parent / "data.db"
        self.db_path = db_path
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._lock = threading.Lock()
        self._init_db()
    
    def _init_db(self):
        """Initialize database tables."""
        with self._lock:
            cursor = self.conn.cursor()

            # WAL mode: eliminuje database-is-locked przy jednoczesnym dostępie bot + dashboard
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")

            cursor.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                side TEXT NOT NULL,
                quantity REAL NOT NULL,
                price REAL NOT NULL,
                fee REAL DEFAULT 0,
                pnl REAL DEFAULT 0,
                order_id TEXT,
                source_trade_id TEXT,
                dedupe_key TEXT UNIQUE
            )
        """)

            trade_columns = {row[1] for row in cursor.execute("PRAGMA table_info(trades)").fetchall()}
            if "source_trade_id" not in trade_columns:
                cursor.execute("ALTER TABLE trades ADD COLUMN source_trade_id TEXT")
            if "dedupe_key" not in trade_columns:
                cursor.execute("ALTER TABLE trades ADD COLUMN dedupe_key TEXT")

            rows_without_key = cursor.execute(
                "SELECT id FROM trades WHERE dedupe_key IS NULL OR dedupe_key = ''"
            ).fetchall()
            for row in rows_without_key:
                cursor.execute("UPDATE trades SET dedupe_key = ? WHERE id = ?", (f"legacy-{row[0]}", row[0]))

            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_order_id ON trades(order_id)")
            cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_trades_dedupe_key ON trades(dedupe_key)")

            cursor.execute("""
            CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                total_value_usdt REAL NOT NULL
            )
        """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_timestamp ON portfolio_snapshots(timestamp)")

            # Tabela automation rules — persystencja między restartami dashboardu
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS automation_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                condition_str TEXT NOT NULL,
                action TEXT NOT NULL,
                enabled INTEGER DEFAULT 1,
                extra_json TEXT DEFAULT '{}'
            )
        """)
            # Wgraj domyślne reguły jeśli tabela jest pusta
            count = cursor.execute("SELECT COUNT(*) FROM automation_rules").fetchone()[0]
            if count == 0:
                defaults = [
                    ("Spread Guard",   "spread_pct > 0.6",        "pause_quotes",      1),
                    ("PnL Protection", "session_pnl_usdt < -25",  "reduce_size_50pct", 1),
                ]
                cursor.executemany(
                    "INSERT INTO automation_rules (name, condition_str, action, enabled) VALUES (?,?,?,?)",
                    defaults,
                )
            self.conn.commit()

    @staticmethod
    def build_trade_key(
        side: str,
        quantity: float,
        price: float,
        order_id: Optional[str] = None,
        source_trade_id: Optional[str] = None,
        timestamp: Optional[str] = None,
    ) -> str:
        key_parts = [
            (source_trade_id or "").strip(),
            (order_id or "").strip(),
            str(side).upper(),
            f"{float(quantity):.12f}",
            f"{float(price):.12f}",
            (timestamp or "").strip(),
        ]
        return hashlib.sha256("|".join(key_parts).encode()).hexdigest()

    def add_trade(
        self,
        side: str,
        quantity: float,
        price: float,
        fee: float = 0,
        order_id: str = None,
        source_trade_id: str = None,
        timestamp: Optional[str] = None,
    ) -> bool:
        """Add a trade to database.

        Returns True when a new row is inserted, False when deduplicated.
        """
        ts = timestamp or datetime.now().isoformat()
        dedupe_key = self.build_trade_key(
            side=side,
            quantity=quantity,
            price=price,
            order_id=order_id,
            source_trade_id=source_trade_id,
            timestamp=ts,
        )
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute("""
            INSERT OR IGNORE INTO trades (timestamp, side, quantity, price, fee, order_id, source_trade_id, dedupe_key)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (ts, side, quantity, price, fee, order_id, source_trade_id, dedupe_key))
            self.conn.commit()
            return cursor.rowcount == 1
    
    def add_snapshot(self, total_value: float):
        """Add portfolio snapshot."""
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute("""
            INSERT INTO portfolio_snapshots (timestamp, total_value_usdt)
            VALUES (?, ?)
            """, (datetime.now().isoformat(), total_value))
            self.conn.commit()
    
    def get_trades(self, limit: int = 100, days: int = 30) -> List[Dict]:
        """Get trades from database."""
        with self._lock:
            cursor = self.conn.cursor()
            since = datetime.now() - timedelta(days=days)
            cursor.execute("""
            SELECT * FROM trades
            WHERE timestamp > ?
            ORDER BY timestamp DESC
            LIMIT ?
            """, (since.isoformat(), limit))
            rows = cursor.fetchall()

        columns = ['id', 'timestamp', 'side', 'quantity', 'price', 'fee', 'pnl', 'order_id', 'source_trade_id', 'dedupe_key']
        trades = [dict(zip(columns, row)) for row in rows]
        return trades
    
    def get_portfolio_history(self, days: int = 30) -> List[Dict]:
        """Get portfolio history."""
        with self._lock:
            cursor = self.conn.cursor()
            since = datetime.now() - timedelta(days=days)
            cursor.execute("""
            SELECT timestamp, total_value_usdt
            FROM portfolio_snapshots
            WHERE timestamp > ?
            ORDER BY timestamp ASC
            """, (since.isoformat(),))
            rows = cursor.fetchall()

        return [{"timestamp": row[0], "total_value_usdt": row[1]} for row in rows]

    # ------------------------------------------------------------------
    # Automation rules — persystencja
    # ------------------------------------------------------------------

    def get_automation_rules(self) -> List[Dict]:
        """Zwróć wszystkie automation rules z bazy."""
        import json
        with self._lock:
            cursor = self.conn.cursor()
            rows = cursor.execute(
                "SELECT id, name, condition_str, action, enabled, extra_json FROM automation_rules ORDER BY id"
            ).fetchall()
        result = []
        for row in rows:
            extra = {}
            try:
                extra = json.loads(row[5] or "{}")
            except Exception:
                pass
            result.append({
                "id": row[0], "name": row[1], "condition": row[2],
                "action": row[3], "enabled": bool(row[4]),
                **extra,
            })
        return result

    def add_automation_rule(self, name: str, condition: str, action: str, extra: dict = None) -> Dict:
        """Dodaj nową regułę i zwróć ją z nadanym id."""
        import json
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute(
                "INSERT INTO automation_rules (name, condition_str, action, enabled, extra_json) VALUES (?,?,?,1,?)",
                (name, condition, action, json.dumps(extra or {}))
            )
            self.conn.commit()
            rid = cursor.lastrowid
        return {"id": rid, "name": name, "condition": condition, "action": action, "enabled": True}

    def update_automation_rule(self, rule_id: int, **fields) -> bool:
        """Zaktualizuj regułę (name, condition, action, enabled)."""
        import json
        allowed = {"name", "condition_str", "action", "enabled"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        # condition → condition_str
        if "condition" in fields and "condition_str" not in updates:
            updates["condition_str"] = fields["condition"]
        if not updates:
            return False
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute(
                f"UPDATE automation_rules SET {set_clause} WHERE id = ?",
                (*updates.values(), rule_id)
            )
            self.conn.commit()
            return cursor.rowcount > 0

    def delete_automation_rule(self, rule_id: int) -> bool:
        """Usuń regułę."""
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute("DELETE FROM automation_rules WHERE id = ?", (rule_id,))
            self.conn.commit()
            return cursor.rowcount > 0
    
    def get_total_pnl(self, days: int = 1) -> Dict:
        """Calculate total P&L from trades."""
        with self._lock:
            cursor = self.conn.cursor()
            since = datetime.now() - timedelta(days=days)
            cursor.execute("""
            SELECT COUNT(*),
                   SUM(CASE WHEN pnl > 0 THEN pnl ELSE 0 END),
                   SUM(CASE WHEN pnl < 0 THEN ABS(pnl) ELSE 0 END),
                   SUM(pnl)
            FROM trades
            WHERE timestamp > ?
            """, (since.isoformat(),))
            row = cursor.fetchone() or (0, 0, 0, 0)
        return {
            "trade_count": row[0] or 0,
            "total_profit": float(row[1] or 0),
            "total_loss": float(row[2] or 0),
            "net_pnl": float(row[3] or 0)
        }
