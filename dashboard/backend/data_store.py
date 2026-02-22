"""Data storage for trades and portfolio snapshots."""
import sqlite3
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from pathlib import Path

class DataStore:
    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            db_path = Path(__file__).parent.parent / "data.db"
        self.db_path = db_path
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._init_db()
    
    def _init_db(self):
        """Initialize database tables."""
        cursor = self.conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                side TEXT NOT NULL,
                quantity REAL NOT NULL,
                price REAL NOT NULL,
                fee REAL DEFAULT 0,
                pnl REAL DEFAULT 0,
                order_id TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                total_value_usdt REAL NOT NULL
            )
        """)
        self.conn.commit()
    
    def add_trade(self, side: str, quantity: float, price: float, fee: float = 0, order_id: str = None):
        """Add a trade to database."""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO trades (timestamp, side, quantity, price, fee, order_id)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (datetime.now().isoformat(), side, quantity, price, fee, order_id))
        self.conn.commit()
    
    def add_snapshot(self, total_value: float):
        """Add portfolio snapshot."""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO portfolio_snapshots (timestamp, total_value_usdt)
            VALUES (?, ?)
        """, (datetime.now().isoformat(), total_value))
        self.conn.commit()
    
    def get_trades(self, limit: int = 100, days: int = 30) -> List[Dict]:
        """Get trades from database."""
        cursor = self.conn.cursor()
        since = datetime.now() - timedelta(days=days)
        cursor.execute("""
            SELECT * FROM trades 
            WHERE timestamp > ? 
            ORDER BY timestamp DESC 
            LIMIT ?
        """, (since.isoformat(), limit))
        
        columns = ['id', 'timestamp', 'side', 'quantity', 'price', 'fee', 'pnl', 'order_id']
        trades = [dict(zip(columns, row)) for row in cursor.fetchall()]
        return trades
    
    def get_portfolio_history(self, days: int = 30) -> List[Dict]:
        """Get portfolio history."""
        cursor = self.conn.cursor()
        since = datetime.now() - timedelta(days=days)
        cursor.execute("""
            SELECT timestamp, total_value_usdt 
            FROM portfolio_snapshots 
            WHERE timestamp > ? 
            ORDER BY timestamp ASC
        """, (since.isoformat(),))
        
        return [{"timestamp": row[0], "total_value_usdt": row[1]} for row in cursor.fetchall()]
    
    def get_total_pnl(self, days: int = 1) -> Dict:
        """Calculate total P&L from trades."""
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
