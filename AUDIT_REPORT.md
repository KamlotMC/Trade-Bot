# Audyt błędów i ryzyk (dashboard + strategy.py + config.yaml)

Data: 2026-02-23

## Krytyczne

1. **`strategy.py`: metody detekcji filli używają niezdefiniowanych symboli (`datetime`, `self.logger`)**  
   W metodach `_detect_fills_from_balances` i `_save_fill_to_db` wykorzystywane są `datetime.now()` oraz `self.logger`, ale klasa importuje tylko modułowy `logger` i nie importuje `datetime`. Jeśli te metody zostaną wywołane, poleci `NameError` / `AttributeError`.

2. **`dashboard/web/app.py`: ryzyko podwójnego liczenia salda w `/api/portfolio`**  
   Suma salda jest liczona jako `available + locked + held + free`. Różne endpointy zwykle zwracają *alternatywne* nazwy pól (`available/free`, `locked/held`), więc taki sumator może zawyżać saldo 2x.

3. **`dashboard/web/app.py`: deduplikacja trade'ów po `order_id` zamiast po ID transakcji**  
   W `sync_trades` sprawdzane jest tylko `order_id`. Jeden order może mieć wiele filli, więc część poprawnych wpisów może być odrzucona jako „duplikat”.

## Wysokie

4. **`config.yaml` zawiera klucze, których kod nie wczytuje**  
   Pola `inventory_target_ratio`, `min_profit_after_fees_pct`, `max_slippage_pct` oraz sekcje `volatility_adapter` i `circuit_breaker` nie są mapowane w `market_maker/config.py` do dataclassy konfiguracyjnej. Są więc aktualnie ignorowane (fałszywe poczucie, że działają).

5. **`dashboard/web/app.py`: `/api/profitability` bazuje na polu `pnl`, które zwykle pozostaje 0**  
   `DataStore.add_trade(...)` zapisuje trade bez liczenia PnL, a endpoint profitability filtruje po `t.get("pnl", 0)`. Statystyki „profit/loss factor” mogą być mylące, bo często liczone z samych zer.

6. **`dashboard/web/app.py`: parser logów zapisuje bieżący czas zamiast czasu z logu**  
   W `parse_fills_from_logs()` timestamp trade'a jest ustawiany na `datetime.now()`, przez co historia trade'ów jest czasowo zniekształcona.

## Średnie / techniczne

7. **`dashboard/web/app.py`: `sync_trades` ma złożoność O(n²)**  
   W pętli po fillach każdorazowo pobiera pełną listę `get_trades(1000, 365)` i robi `any(...)`. Dla większej historii endpoint będzie szybko zwalniał.

8. **`test_dashboard.py` jest nieaktualny względem API klasy `DataStore`**  
   Wywołanie `store.add_snapshot(1000000, 50, 0.000037, 87)` nie zgadza się z sygnaturą `add_snapshot(self, total_value: float)`.

## Priorytet poprawek (propozycja)

1. Naprawić `strategy.py` (`datetime`, `self.logger`) lub usunąć martwy kod, jeśli nieużywany.  
2. Poprawić agregację balansu w dashboardzie (znormalizować jeden model pól).  
3. Wprowadzić poprawną deduplikację filli (np. `trade_id` + `order_id` + timestamp).  
4. Ujednolicić `config.yaml` z `market_maker/config.py` (albo wdrożyć brakujące pola, albo usunąć z YAML).  
5. Przerobić `/api/profitability` na liczenie z `calculated_pnl` lub rzeczywistego modelu księgowania.
