# Audit of Errors and Risks (dashboard + strategy.py + config.yaml)

## Critical findings

1. **`strategy.py`: fill-detection methods reference undefined symbols (`datetime`, `self.logger`)**  
   In `_detect_fills_from_balances` and `_save_fill_to_db`, the implementation uses `datetime.now()` and `self.logger`, but the class only uses the module-level logger and does not import `datetime`. If these methods execute, they can raise `NameError` / `AttributeError`.

2. **`dashboard/web/app.py`: potential balance double-counting in `/api/portfolio`**  
   Balance totals were previously computed from mixed aliases such as `available + locked + held + free`. Most APIs expose `available/free` and `locked/held` as aliases, so summing all variants can overstate balances.

3. **`dashboard/web/app.py`: trade deduplication by `order_id` only**  
   A single order can produce many fills. Deduplication based only on `order_id` can drop valid fills as duplicates.

## Important findings

4. **`config.yaml` contains fields not consumed by runtime config parsing**  
   Fields like `inventory_target_ratio`, `min_profit_after_fees_pct`, `max_slippage_pct`, and sections such as `volatility_adapter` / `circuit_breaker` were not fully mapped in `market_maker/config.py` in earlier revisions, creating false expectations.

5. **`dashboard/web/app.py`: profitability can be misleading if using stored `pnl` field directly**  
   Trades are often persisted without precomputed `pnl`; profitability should be based on realized FIFO calculations or explicit accounting.

6. **`dashboard/web/app.py`: log parsing can distort original event timestamps**  
   If parser fallback uses current time rather than parsed log timestamp, trade chronology becomes inaccurate.

## Medium / technical findings

7. **`dashboard/web/app.py`: `sync_trades` can degrade with large history**  
   Repeated historical scans and per-row checks can lead to poor scaling without an indexed deduplication strategy.

8. **`test_dashboard.py`: historical mismatch with DataStore API**  
   Older tests used signatures that did not match the current `DataStore.add_snapshot(total_value)` interface.

## Recommended next steps

1. Harden `strategy.py` imports and logger usage for all paths.
2. Keep a single normalized balance schema when aggregating portfolio values.
3. Deduplicate fills using transaction-level identifiers and timestamp context.
4. Align `config.yaml` with `market_maker/config.py` to avoid ignored settings.
5. Keep profitability based on realized FIFO/accounting-derived values only.
