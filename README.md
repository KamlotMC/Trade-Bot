# Meowcoin Market Maker Bot

A Python market-making bot for the **MEWC/USDT** trading pair on the [NonKYC exchange](https://nonkyc.io).

> **⚠️ Read [LEGAL_NOTICE.md](LEGAL_NOTICE.md) before using this software.**

---

## What It Does

The bot continuously places **limit buy and sell orders** around the current mid-price of MEWC/USDT, providing two-sided liquidity to the order book. It earns the bid-ask spread on every round-trip fill.

**Features:**
- Multi-level order placement (configurable depth)
- Inventory-aware quote skewing (rebalances when one side gets heavy)
- Risk management: stop-loss, daily loss limit, exposure caps, max order count
- Automatic order refresh cycle
- Structured logging to console and file
- HMAC-SHA256 authenticated API calls (NonKYC REST API v2)
- Dry-run mode for testing configuration

---

## Quick Start

### 1. Clone & Install

```bash
cd ~/MeowcoinMarketMaker
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure API Keys

1. Log in to your [NonKYC account](https://nonkyc.io) and generate an API key with trading permissions.
2. Copy the example env file and add your credentials:

```bash
cp .env.example .env
```

Edit `.env`:
```
NONKYC_API_KEY=your_actual_api_key
NONKYC_API_SECRET=your_actual_api_secret
```

### 3. Adjust Configuration

Edit `config.yaml` to tune the strategy:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `spread_pct` | `0.02` (2%) | Distance from mid-price per side |
| `num_levels` | `3` | Order levels on each side |
| `level_step_pct` | `0.005` (0.5%) | Extra offset per deeper level |
| `base_quantity` | `1000` | MEWC per order at level 0 |
| `quantity_multiplier` | `1.5` | Size increase per level |
| `refresh_interval_sec` | `30` | Seconds between refresh cycles |
| `max_mewc_exposure` | `50000` | Maximum MEWC position |
| `max_usdt_exposure` | `500` | Maximum USDT at risk |
| `stop_loss_usdt` | `-50` | Halt if unrealized P&L drops below |
| `daily_loss_limit_usdt` | `-100` | Halt if daily loss exceeds |

### 4. Test (Dry Run)

```bash
python main.py --dry-run
```

This prints the loaded configuration without placing any orders.

### 5. Run

```bash
python main.py
```

Or to auto-accept the disclaimer:
```bash
python main.py --accept-disclaimer
```

Press `Ctrl+C` to gracefully shut down (all orders will be cancelled).

---


## Trading Center Dashboard

The project includes a web dashboard (FastAPI + HTML/JS) that works as a **Trading Center** with tabs:

- Overview
- Trading (manual order panel)
- Risk (risk cockpit)
- Automation (rule engine)
- Execution (quality + lifecycle)
- Backtest (summary)
- Journal (strategy trace)

### Start the dashboard

```bash
python -m uvicorn dashboard.web.app:app --host 0.0.0.0 --port 8000
```

Then open: `http://localhost:8000`

### Key dashboard endpoints

- `POST /api/orders/manual`
- `POST /api/orders/cancel-all`
- `GET /api/open-orders`
- `POST /api/open-orders/{order_id}/cancel`
- `GET /api/orderbook`
- `POST /api/trades/{trade_id}/close`
- `GET /api/risk-cockpit`
- `GET /api/automation-rules`
- `POST /api/automation-rules`
- `GET /api/execution-quality`
- `GET /api/order-lifecycle`
- `GET /api/backtest-replay-summary`
- `GET /api/strategy-journal`

### Testing

```bash
python -m compileall -q .
pytest -q
```

## Architecture

```
MeowcoinMarketMaker/
├── main.py                    # Entry point & CLI
├── config.yaml                # Strategy & risk configuration
├── .env                       # API keys (gitignored)
├── requirements.txt           # Python dependencies
├── LEGAL_NOTICE.md            # Full legal/compliance documentation
├── README.md                  # This file
└── market_maker/
    ├── __init__.py
    ├── config.py              # YAML + env config loader
    ├── exchange_client.py     # NonKYC REST API client (HMAC-SHA256)
    ├── strategy.py            # Market-making logic & order management
    ├── risk_manager.py        # Position tracking, skew, and safety halts
    └── logger.py              # Rotating file + console logger setup
```

### How a Cycle Works

Every `refresh_interval_sec` seconds:

1. **Risk check** — verify no halt conditions (daily loss, stop-loss)
2. **Fetch orderbook** — calculate mid-price from best bid/ask
3. **Refresh balances** — get MEWC and USDT available/held
4. **Cancel all existing orders** — clean slate each cycle
5. **Compute quotes** — calculate bid/ask prices at each level with inventory skew
6. **Place orders** — submit limit orders that pass exposure checks

### Inventory Skew

When the bot accumulates more MEWC than USDT (or vice versa), it tilts quotes:
- **Long MEWC** → tighten ask (encourage sells), widen bid (discourage buys)
- **Short MEWC** → tighten bid (encourage buys), widen ask (discourage sells)

This naturally rebalances inventory toward a 50/50 portfolio split.

---

## Safety Features

| Feature | Description |
|---------|-------------|
| **Stop-Loss** | Halts if unrealized P&L drops below threshold |
| **Daily Loss Limit** | Halts if cumulative daily losses exceed threshold |
| **Exposure Caps** | Per-side maximum for MEWC and USDT |
| **Max Open Orders** | Prevents runaway order placement |
| **Balance Usage Cap** | Only uses 80% of available balance by default |
| **Graceful Shutdown** | Cancels all orders on Ctrl+C or fatal error |
| **Min Spread Floor** | Never tightens below `min_spread_pct` |

---

## API Reference

This bot uses the [NonKYC REST API v2](https://api.nonkyc.io/):

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/market/orderbook` | GET | Fetch order book |
| `/market/info` | GET | Get price/quantity decimals |
| `/ticker/{symbol}` | GET | Get 24h ticker data |
| `/balances` | GET (signed) | Get account balances |
| `/createorder` | POST (signed) | Place a limit order |
| `/cancelorder` | POST (signed) | Cancel an order by ID |
| `/cancelallorders` | POST (signed) | Cancel all open orders |
| `/account/orders` | GET (signed) | List account orders |

---

## Legal & Compliance

**This bot is designed to be a legitimate market maker**, not a manipulation tool:

- All orders are genuine two-sided liquidity intended to be filled
- No wash trading, spoofing, layering, or front-running
- Inventory skew prevents directional accumulation
- Full compliance details in [LEGAL_NOTICE.md](LEGAL_NOTICE.md)

**You are responsible for:**
- Ensuring this activity is legal in your jurisdiction
- All applicable tax reporting
- Complying with AML regulations regardless of exchange KYC status
- Monitoring and managing the bot's risk parameters

---

## License

MIT License. See [LEGAL_NOTICE.md](LEGAL_NOTICE.md) for full terms and risk disclosures.
