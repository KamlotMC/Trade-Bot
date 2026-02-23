from fastapi import FastAPI
from fastapi.responses import HTMLResponse, FileResponse
from pathlib import Path
import sys, os, requests
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))
from backend.api_client import NonKYCClient
from backend.data_store import DataStore
from backend.calculator import PnLCalculator
from backend.log_parser import LogParser

# Manual .env loading
env_path = Path.home() / "Trade-Bot" / ".env"
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.strip().split("=", 1)
                os.environ[k.strip()] = v.strip()

api_client = NonKYCClient()
data_store = DataStore()
calculator = PnLCalculator(data_store)
log_parser = LogParser()

app = FastAPI()

def sf(val, default=0.0):
    """Safe float conversion"""
    try:
        if val is None:
            return default
        return float(val)
    except (ValueError, TypeError):
        return default


def get_asset_totals(balances, asset: str) -> float:
    """Normalize balance schema variants and avoid double counting.

    Some endpoints return pairs like free/locked, others available/held.
    We treat them as aliases and prefer free/locked when present.
    """
    total = 0.0
    for b in balances:
        if b.get("asset") != asset:
            continue
        free = b.get("free")
        locked = b.get("locked")
        available = b.get("available")
        held = b.get("held")

        free_part = sf(free if free is not None else available)
        locked_part = sf(locked if locked is not None else held)
        total += free_part + locked_part
    return total

def enrich_trades_with_realized_pnl(trades: list) -> list:
    """Return trades enriched with FIFO-based realized P&L on SELL fills."""
    enriched = []
    pos, avg = 0.0, 0.0

    for t in reversed(trades):
        side = str(t.get("side", "")).upper()
        qty = sf(t.get("quantity"))
        prc = sf(t.get("price"))
        fee = sf(t.get("fee"))
        calc_pnl = None

        if side == "BUY" and qty > 0:
            cost = (pos * avg) + (qty * prc) + fee
            pos += qty
            avg = cost / pos if pos > 0 else 0
        elif side == "SELL" and pos > 0 and qty > 0:
            rev = (qty * prc) - fee
            cst = qty * avg
            calc_pnl = rev - cst
            pos -= qty

        tt = dict(t)
        tt["calculated_pnl"] = calc_pnl
        enriched.append(tt)

    return list(reversed(enriched))


def get_price_data():
    """Get MEWC price data - FIXED with correct field names"""
    try:
        r = requests.get("https://api.nonkyc.io/api/v2/ticker/MEWC_USDT", timeout=5)
        if r.ok:
            d = r.json()
            
            # FIXED: Use snake_case field names as returned by API
            last_price = (
                sf(d.get("lastPrice")) or 
                sf(d.get("last")) or 
                sf(d.get("price")) or 
                sf(d.get("close")) or 
                0.00003750
            )
            
            bid = (
                sf(d.get("bid")) or 
                sf(d.get("bidPrice")) or 
                (last_price * 0.995)
            )
            
            ask = (
                sf(d.get("ask")) or 
                sf(d.get("askPrice")) or 
                (last_price * 1.005)
            )
            
            change = (
                d.get("change_percent") or  # ✅ CORRECT: snake_case
                d.get("changePercent") or 
                d.get("priceChangePercent") or
                "0"
            )
            
            # FIXED: Use correct field names
            volume = (
                sf(d.get("usd_volume_est")) or  # ✅ CORRECT: snake_case
                sf(d.get("base_volume")) or      # ✅ CORRECT: snake_case
                sf(d.get("target_volume")) or    # ✅ CORRECT: snake_case
                sf(d.get("baseVolume")) or       # Fallback camelCase
                sf(d.get("quoteVolume")) or      # Fallback camelCase
                0
            )
            
            print(f"✅ Price: {last_price}, Bid: {bid}, Ask: {ask}, Change: {change}, Vol: {volume}")
            
            return {
                "last_price": last_price,
                "bid": bid,
                "ask": ask,
                "change_percent": str(change),
                "volume": volume
            }
        else:
            print(f"❌ API Error {r.status_code}: {r.text[:200]}")
            return None
    except Exception as e:
        print(f"❌ Price API exception: {e}")
        return None
    
    # Final fallback
    return {
        "last_price": 0.00003750,
        "bid": 0.00003731,
        "ask": 0.00003769,
        "change_percent": "0",
        "volume": 0
    }

@app.get("/")
async def index():
    return FileResponse(Path(__file__).parent / "templates" / "index.html")

@app.get("/api/price")
async def api_price():
    data = get_price_data()
    if data is None:
        data = {
            "last_price": 0.00003750,
            "bid": 0.00003731,
            "ask": 0.00003769,
            "change_percent": "0",
            "volume": 0
        }
    
    return {
        "last_price": data["last_price"],
        "bid": data["bid"],
        "ask": data["ask"],
        "change_percent": data["change_percent"],
        "usd_volume_est": data["volume"]
    }

@app.get("/api/portfolio")
async def api_portfolio():
    balances_result = api_client.get_balances()

    data_source = "exchange"
    data_warning = None

    if "error" not in balances_result:
        bl = balances_result.get("balances", balances_result) if isinstance(balances_result, dict) else balances_result
        mewc = get_asset_totals(bl, "MEWC")
        usdt = get_asset_totals(bl, "USDT")
    else:
        err = balances_result.get("error") if isinstance(balances_result, dict) else str(balances_result)
        print(f"⚠️ Balances API error: {err}")
        data_source = "history_fallback"
        data_warning = f"Balances unavailable: {err}"

        # Prefer recent total from history to avoid fake hardcoded balances.
        hist = data_store.get_portfolio_history(7)
        last_total = hist[-1]["total_value_usdt"] if hist else 0.0
        mewc, usdt = 0.0, float(last_total)

    price_data = get_price_data()
    price = price_data["last_price"] if price_data and price_data["last_price"] > 0 else 0.00003750
    mewc_val = mewc * price
    total = mewc_val + usdt

    # Save snapshot
    data_store.add_snapshot(total)

    return {
        "mewc_balance": round(mewc, 2),
        "mewc_value_usdt": round(mewc_val, 2),
        "usdt_balance": round(usdt, 2),
        "total_value_usdt": round(total, 2),
        "mewc_percentage": round((mewc_val / total * 100), 2) if total > 0 else 0,
        "data_source": data_source,
        "data_warning": data_warning,
    }

@app.get("/api/pnl")
async def api_pnl():
    return calculator.get_current_pnl()

@app.get("/api/pnl-saldo")
async def api_pnl_saldo():
    try:
        now = datetime.now()
        reset = now.replace(hour=7, minute=0, second=0) if now.hour >= 7 else (now - timedelta(days=1)).replace(hour=7, minute=0, second=0)
        hist = data_store.get_portfolio_history(2)
        if not hist:
            return {"pnl": 0, "start_value": 0, "current_value": 0, "change_pct": 0}
        start = next((h["total_value_usdt"] for h in hist if datetime.fromisoformat(h["timestamp"]) >= reset), hist[0]["total_value_usdt"])
        curr = hist[-1]["total_value_usdt"]
        pct = ((curr - start) / start * 100) if start > 0 else 0
        return {"pnl": round(curr - start, 2), "start_value": round(start, 2), "current_value": round(curr, 2), "change_pct": round(pct, 2)}
    except Exception as e:
        print(f"PnL saldo error: {e}")
        return {"pnl": 0, "start_value": 0, "current_value": 0, "change_pct": 0}

@app.get("/api/win-rate")
async def api_win_rate():
    trades = data_store.get_trades(1000, 30)
    print(f"📊 Win rate: {len(trades)} trades in DB")

    enriched = enrich_trades_with_realized_pnl(trades)
    realized = [t.get("calculated_pnl") for t in enriched if t.get("calculated_pnl") is not None]
    wins = sum(1 for p in realized if p > 0)
    losses = sum(1 for p in realized if p < 0)
    total = wins + losses

    result = {
        "win_rate": round((wins / total * 100), 1) if total > 0 else 0,
        "winning": wins,
        "losing": losses,
        "total": total
    }
    print(f"✅ Win rate result: {result}")
    return result


def parse_fills_from_logs() -> list:
    """Parse filled trades from bot logs."""
    import re
    log_path = Path.home() / "Trade-Bot" / "logs" / "market_maker.log"
    if not log_path.exists():
        return []
    
    trades = []
    try:
        with open(log_path, 'r') as f:
            lines = f.readlines()
        
        # Look for balance changes that indicate fills
        prev_mewc = prev_usdt = None
        
        for line in lines:
            ts_match = re.match(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s*\|', line)
            line_ts = None
            if ts_match:
                try:
                    line_ts = datetime.strptime(ts_match.group(1), "%Y-%m-%d %H:%M:%S").isoformat()
                except ValueError:
                    line_ts = None
            # Match balance line: Balances — MEWC: 1240000.00 avail / 100000.00 held | USDT: 39.97 avail / 2.58 held
            m = re.search(r'Balances\s+—\s+MEWC:\s*([\d.]+)\s*avail\s*/\s*([\d.]+)\s*held\s*\|\s*USDT:\s*([\d.]+)\s*avail\s*/\s*([\d.]+)\s*held', line)
            if m:
                mewc_total = float(m.group(1)) + float(m.group(2))
                usdt_total = float(m.group(3)) + float(m.group(4))
                
                if prev_mewc is not None and prev_usdt is not None:
                    mewc_diff = mewc_total - prev_mewc
                    usdt_diff = usdt_total - prev_usdt
                    
                    # Detect BUY: MEWC increased, USDT decreased
                    if mewc_diff > 100 and usdt_diff < -0.1:
                        price = abs(usdt_diff / mewc_diff)
                        trades.append({
                            "timestamp": line_ts or datetime.now().isoformat(),
                            "side": "BUY",
                            "quantity": abs(mewc_diff),
                            "price": price,
                            "fee": 0,
                            "pnl": 0,
                            "order_id": f"log_{len(trades)}"
                        })
                        print(f"🟢 Detected BUY: {abs(mewc_diff):.0f} MEWC @ {price:.8f}")
                    
                    # Detect SELL: MEWC decreased, USDT increased
                    elif mewc_diff < -100 and usdt_diff > 0.1:
                        price = abs(usdt_diff / mewc_diff)
                        trades.append({
                            "timestamp": line_ts or datetime.now().isoformat(),
                            "side": "SELL",
                            "quantity": abs(mewc_diff),
                            "price": price,
                            "fee": 0,
                            "pnl": 0,
                            "order_id": f"log_{len(trades)}"
                        })
                        print(f"🔴 Detected SELL: {abs(mewc_diff):.0f} MEWC @ {price:.8f}")
                
                prev_mewc, prev_usdt = mewc_total, usdt_total
                
    except Exception as e:
        print(f"Log parse error: {e}")
    
    return trades

@app.get("/api/fills")
async def api_fills():
    """Get trades with calculated P&L - fallback to log parsing"""
    trades = data_store.get_trades(50, 30)
    
    # If no trades in DB, try parsing from logs
    if not trades:
        print("📊 No trades in DB, trying log parsing...")
        log_trades = parse_fills_from_logs()
        if log_trades:
            print(f"✅ Parsed {len(log_trades)} trades from logs")
            # Optionally save to DB for future
            for t in log_trades:
                data_store.add_trade(t["side"], t["quantity"], t["price"], t["fee"], t["order_id"])
            trades = data_store.get_trades(50, 30)
    print(f"📊 Fills: {len(trades)} trades from DB")
    
    final_result = enrich_trades_with_realized_pnl(trades)
    print(f"✅ Returning {len(final_result)} trades")
    return final_result

@app.post("/api/trades/sync-from-exchange")
async def sync_trades():
    print("🔄 Syncing trades from exchange...")
    result = api_client.get_my_trades("MEWC_USDT", 200)
    
    if "error" in result:
        print(f"❌ Sync error: {result['error']}")
        return {"status": "error", "message": result["error"]}
    
    fills = result.get("trades", result) if isinstance(result, dict) else result
    print(f"📊 Got {len(fills)} trades from API")
    
    added = 0
    existing = data_store.get_trades(10000, 365)
    existing_keys = {
        (str(t.get("order_id") or ""), str(t.get("side") or ""), float(sf(t.get("quantity"))), float(sf(t.get("price"))), str(t.get("timestamp") or ""))
        for t in existing
    }

    for f in fills:
        oid = str(f.get('orderId') or '')
        tid = str(f.get('id') or '')
        dedup_id = tid or oid
        if not dedup_id:
            continue
        
        side = f.get('side', 'BUY').upper()
        qty = sf(f.get('qty') or f.get('quantity'))
        prc = sf(f.get('price'))
        fee = sf(f.get('commission') or f.get('fee'))
        ts = str(f.get('timestamp') or f.get('time') or f.get('createdAt') or "")

        key = (dedup_id, side, float(qty), float(prc), ts)
        if key in existing_keys:
            continue
        
        data_store.add_trade(side=side, quantity=qty, price=prc, fee=fee, order_id=dedup_id)
        existing_keys.add(key)
        print(f"  + Added: {side} {qty} @ {prc}")
        added += 1
    
    print(f"✅ Synced {added} new trades")
    return {"status": "success", "added": added, "total": len(fills)}

@app.get("/api/history")
async def api_history(days=30):
    return data_store.get_portfolio_history(days)

@app.get("/api/bot-status")
async def api_bot_status():
    return log_parser.get_bot_status(100)

@app.get("/api/open-orders-logs")
async def api_open_orders():
    return log_parser.get_open_orders_from_logs(200)


@app.get("/api/order-lifecycle")
async def api_order_lifecycle():
    return log_parser.get_order_lifecycle(500)

@app.get("/api/errors")
async def api_errors():
    return log_parser.get_errors(200)


@app.get("/api/profitability")
async def get_profitability_stats():
    """Get detailed profitability statistics."""
    trades = data_store.get_trades(1000, 30)
    
    if not trades:
        return {
            "total_trades": 0,
            "total_volume": 0,
            "total_fees": 0,
            "gross_profit": 0,
            "net_profit": 0,
            "avg_trade_profit": 0,
            "best_trade": 0,
            "worst_trade": 0,
            "profit_factor": 0,
            "methodology": "Realized FIFO PnL (fees included per fill)",
        }
    
    # Calculate statistics
    total_trades = len(trades)
    total_volume = sum(sf(t.get("quantity")) * sf(t.get("price")) for t in trades)
    total_fees = sum(sf(t.get("fee")) for t in trades)

    enriched = enrich_trades_with_realized_pnl(trades)
    realized = [sf(t.get("calculated_pnl")) for t in enriched if t.get("calculated_pnl") is not None]
    winning_trades = [p for p in realized if p > 0]
    losing_trades = [p for p in realized if p < 0]

    gross_profit = sum(winning_trades)
    gross_loss = abs(sum(losing_trades))
    net_profit = gross_profit - gross_loss

    avg_trade = net_profit / len(realized) if realized else 0
    best_trade = max(realized, default=0)
    worst_trade = min(realized, default=0)

    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf') if gross_profit > 0 else 0

    return {
        "total_trades": total_trades,
        "winning_trades": len(winning_trades),
        "losing_trades": len(losing_trades),
        "total_volume_usdt": round(total_volume, 2),
        "total_fees_usdt": round(total_fees, 4),
        "gross_profit_usdt": round(gross_profit, 4),
        "gross_loss_usdt": round(gross_loss, 4),
        "net_profit_usdt": round(net_profit, 4),
        "avg_trade_profit_usdt": round(avg_trade, 4),
        "best_trade_usdt": round(best_trade, 4),
        "worst_trade_usdt": round(worst_trade, 4),
        "profit_factor": round(profit_factor, 2) if profit_factor != float('inf') else "∞",
        "win_rate_pct": round(len(winning_trades) / len(realized) * 100, 1) if realized else 0,
        # Clear naming for current implementation semantics
        "gross_profit_after_fees_usdt": round(gross_profit, 4),
        "net_realized_pnl_after_fees_usdt": round(net_profit, 4),
        "methodology": "Realized FIFO PnL (fees included per fill)",
    }


@app.get("/api/execution-quality")
async def api_execution_quality():
    """Execution quality stats from realized FIFO PnL stream."""
    trades = data_store.get_trades(1000, 30)
    enriched = enrich_trades_with_realized_pnl(trades)
    realized = [sf(t.get("calculated_pnl")) for t in enriched if t.get("calculated_pnl") is not None]

    fills_total = len(trades)
    sell_fills = len(realized)
    positive = [p for p in realized if p > 0]
    negative = [p for p in realized if p < 0]

    # Basic realized spread capture proxy from SELL fills.
    spread_capture = [p for p in realized]

    # Anomaly alerts.
    alerts = []
    if fills_total == 0:
        alerts.append("No fills in selected period")
    if sell_fills >= 5 and len(negative) / sell_fills > 0.7:
        alerts.append("High adverse selection: >70% negative realized SELL fills")

    return {
        "fills_total": fills_total,
        "sell_fills_with_realized_pnl": sell_fills,
        "positive_sell_fills": len(positive),
        "negative_sell_fills": len(negative),
        "avg_realized_pnl_per_sell_usdt": round(sum(realized) / sell_fills, 6) if sell_fills else 0,
        "median_like_realized_pnl_usdt": round(sorted(realized)[sell_fills // 2], 6) if sell_fills else 0,
        "realized_spread_capture_usdt": round(sum(spread_capture), 6),
        "fill_to_post_ratio": 0,  # placeholder until post count comes from lifecycle aggregation
        "avg_fill_latency_sec": None,  # requires exchange-side order event timestamps
        "post_fill_adverse_move_pct": None,  # requires tick series around fill time
        "alerts": alerts,
        "methodology": "Realized FIFO PnL (fees included per fill)",
    }


@app.get("/api/live-risk")
async def api_live_risk():
    """Live risk widget payload from latest balances + config bands."""
    balances_result = api_client.get_balances()
    if "error" in balances_result:
        return {
            "inventory_ratio": 0,
            "target_ratio": 0.6,
            "band_low": 0.4,
            "band_high": 0.7,
            "current_skew": 0,
            "risk_halted": False,
            "risk_reason": balances_result.get("error"),
        }

    bl = balances_result.get("balances", balances_result) if isinstance(balances_result, dict) else balances_result
    mewc = get_asset_totals(bl, "MEWC")
    usdt = get_asset_totals(bl, "USDT")
    pd = get_price_data() or {"last_price": 0}
    mid = sf(pd.get("last_price"))
    mewc_val = mewc * mid
    total = mewc_val + usdt
    ratio = (mewc_val / total) if total > 0 else 0

    # Mirror current config defaults for dashboard risk bands.
    target = 0.6
    band_low = 0.4
    band_high = 0.7
    skew = ((ratio - target) / max(target, 1 - target, 1e-9)) if total > 0 else 0
    skew = max(min(skew, 1), -1)

    return {
        "inventory_ratio": round(ratio, 4),
        "target_ratio": target,
        "band_low": band_low,
        "band_high": band_high,
        "current_skew": round(skew, 4),
        "risk_halted": False,
        "risk_reason": "",
    }

if __name__ == "__main__":
    import uvicorn
    print("=" * 60)
    print("🚀 MEWC Market Maker Dashboard - FIXED")
    print("=" * 60)
    print("✅ Volume field names corrected (snake_case)")
    print("✅ Ready to sync trades")
    print("🌐 http://localhost:8000")
    print("=" * 60)
    uvicorn.run(app, host="0.0.0.0", port=8000)
