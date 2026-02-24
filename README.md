# Meowcoin Market Maker + Trading Dashboard

Bot market-making dla pary **MEWC/USDT** na giełdzie NonKYC + webowy dashboard operacyjny (FastAPI + HTML/JS).

> **WAŻNE:** zanim uruchomisz bota, przeczytaj [LEGAL_NOTICE.md](LEGAL_NOTICE.md).

---

## 1) Co zawiera projekt

Projekt składa się z 2 głównych części:

1. **Silnik bota (`market_maker/`)**
   - pobiera orderbook i bilanse,
   - wylicza kwotowania (bid/ask) na wielu poziomach,
   - zarządza ryzykiem i inventory,
   - składa/anuluje zlecenia przez API NonKYC.

2. **Dashboard (`dashboard/`)**
   - podgląd ceny, portfela, PnL, open orders,
   - ręczne zlecenia i cancel-all,
   - zakładki: risk, automation, execution, backtest, journal,
   - API backendowe do integracji i monitoringu.

---

## 2) Aktualna struktura projektu

```text
Trade-Bot/
├── main.py
├── config.yaml
├── requirements.txt
├── README.md
├── LEGAL_NOTICE.md
├── LICENSE
├── AUDIT_REPORT.md
├── MeowcoinMarketMaker.spec
├── test_dashboard.py
├── market_maker/
│   ├── __init__.py
│   ├── config.py
│   ├── exchange_client.py
│   ├── gui.py
│   ├── logger.py
│   ├── risk_manager.py
│   └── strategy.py
└── dashboard/
    ├── backend/
    │   ├── __init__.py
    │   ├── api_client.py
    │   ├── calculator.py
    │   ├── data_store.py
    │   ├── log_parser.py
    │   ├── paths.py
    │   └── services/
    │       ├── __init__.py
    │       └── trading_service.py
    └── web/
        ├── app.py
        └── templates/
            └── index.html
```

---

## 3) Moduły i najważniejsze funkcje

## `main.py` (entrypoint bota)
- `main()`
  - parsuje argumenty CLI,
  - uruchamia GUI (domyślnie) lub tryb CLI,
  - ładuje config + logger,
  - obsługuje dry-run,
  - inicjalizuje klienta giełdy, risk manager i strategię,
  - uruchamia pętlę bota.
- `_pause_before_exit()` – bezpieczne zatrzymanie/„pauza” przy wyjściu.

### `market_maker/config.py`
- `load_config()` – ładuje `config.yaml` + `.env`, buduje `BotConfig`.
- `get_app_dir()`, `get_bundle_dir()` – ścieżki runtime (normal/PyInstaller).
- `_ensure_user_file()` – kopiuje pliki konfiguracyjne do katalogu użytkownika.
- `_sanitize_config()` – normalizuje pola procentowe i typowe błędy konfiguracyjne.

### `market_maker/exchange_client.py`
Klasa `NonKYCClient`:
- podpisywanie requestów HMAC (`_sign_get`, `_sign_post`),
- `_get`, `_post`, `_check_response` – bezpieczna komunikacja HTTP,
- API publiczne/prywatne:
  - ticker/orderbook/market info,
  - balances,
  - create/cancel/cancel-all,
  - listing open orders,
- helpery normalizacji precyzji i credentials.

### `market_maker/risk_manager.py`
Klasa `RiskManager`:
- tracking sald i inventory ratio,
- limity ekspozycji (MEWC/USDT),
- limity strat (session/day),
- checki ryzyka przed wysłaniem zleceń,
- wyliczanie skew inventory.

### `market_maker/strategy.py`
Klasa `MarketMaker`:
- główna pętla `run()`,
- odświeżanie danych rynkowych i bilansów,
- obliczanie quote levels (`_compute_quotes`),
- adaptive spread / skew / sesje,
- cancel-replace i składanie nowych zleceń,
- ochrona przed crossingiem i warunki maker-only.

### `market_maker/logger.py`
- `setup_logger()` – konfiguracja logowania (console + rotating file).

### `market_maker/gui.py`
- GUI desktop do uruchamiania i kontroli bota (fallback do CLI, gdy GUI niedostępne).

### `dashboard/web/app.py` (FastAPI)
- endpointy strony i API dashboardu:
  - `/` – UI,
  - `/api/price`, `/api/portfolio`, `/api/pnl`, `/api/win-rate`,
  - `/api/open-orders`, `/api/orderbook`, `/api/history`,
  - `/api/orders/manual`, `/api/orders/preflight`, `/api/orders/cancel-all`,
  - `/api/risk-cockpit`, `/api/live-pnl`, `/api/execution-quality`,
  - `/api/order-lifecycle`, `/api/order-lifecycle-metrics`,
  - `/api/backtest/import`, `/api/backtest/compare`,
  - `/api/strategy-journal`, `/api/strategy-reason-trace`, itd.
- helpery m.in.:
  - `get_price_data()`,
  - `manual_order_preflight()`,
  - `build_confirm_token()`,
  - normalizacja bilansów/trade’ów.

### `dashboard/backend/*`
- `api_client.py` – klient API NonKYC dla dashboardu,
- `data_store.py` – SQLite (trades, snapshots),
- `calculator.py` – metryki PnL,
- `log_parser.py` – parsowanie logów bota,
- `services/trading_service.py` – logika open orders, cancel, close trade,
- `paths.py` – odnajdywanie plików projektu.

### `dashboard/web/templates/index.html`
- frontend dashboardu (zakładki, karty, wykresy, manual order panel, status/refresh).

---

## 4) Wymagania środowiska

- Python **3.10+** (zalecane 3.11)
- System: Linux / macOS / Windows
- Dostęp do internetu do API NonKYC

Instalacja zależności:

```bash
python -m venv .venv
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\activate   # Windows PowerShell
pip install -r requirements.txt
```

---

## 5) Konfiguracja przed uruchomieniem

## 5.1 Klucze API (`.env`)
W katalogu głównym utwórz plik `.env`:

```env
NONKYC_API_KEY=twoj_klucz
NONKYC_API_SECRET=twoj_secret
```

> Jeśli uruchomisz `main.py` bez kluczy, aplikacja przeprowadzi Cię przez first-run setup i zapisze `.env`.

## 5.2 Parametry strategii (`config.yaml`)
Najczęściej używane pola:
- `strategy.spread_pct`
- `strategy.num_levels`
- `strategy.level_step_pct`
- `strategy.base_quantity`
- `strategy.refresh_interval_sec`
- `risk.max_mewc_exposure`
- `risk.max_usdt_exposure`
- `risk.stop_loss_usdt`
- `risk.daily_loss_limit_usdt`

---

## 6) Jak uruchomić bota

## Tryb domyślny (GUI)
```bash
python main.py
```

## Tryb CLI
```bash
python main.py --cli
```

## Dry run (bez składania zleceń)
```bash
python main.py --dry-run
```

## Własny plik config
```bash
python main.py --cli --config config.yaml
```

## Auto-akceptacja disclaimera
```bash
python main.py --cli --accept-disclaimer
```

---

## 7) Jak uruchomić dashboard

```bash
python -m uvicorn dashboard.web.app:app --host 0.0.0.0 --port 8000
```

Otwórz w przeglądarce:

- lokalnie: `http://127.0.0.1:8000`
- w sieci LAN: `http://<twoj_host>:8000`

Dashboard korzysta z danych z API i lokalnej bazy SQLite (`dashboard/data.db`).

---

## 8) Typowy workflow (polecany)

1. Uzupełnij `.env` i zweryfikuj `config.yaml`.
2. Uruchom `--dry-run`.
3. Uruchom dashboard.
4. Uruchom bota (GUI lub `--cli`).
5. Monitoruj:
   - `logs/market_maker.log`,
   - zakładki risk/execution,
   - open orders i PnL.

---

## 9) Testy i walidacja

Uruchom podstawową walidację:

```bash
python -m compileall -q .
pytest -q
```

`test_dashboard.py` sprawdza m.in. brak HTTP 500 na kluczowych endpointach dashboardu i poprawność manual preflight.

---

## 10) Najczęstsze problemy

- **401/403 z API**
  - sprawdź poprawność klucza i secret,
  - upewnij się, że klucz ma uprawnienia trading,
  - usuń ukryte znaki/whitespace w `.env`.

- **Pusty dashboard / brak danych**
  - sprawdź czy bot działa,
  - sprawdź połączenie z internetem,
  - sprawdź logi aplikacji i endpointy `/api/*`.

- **Brak GUI**
  - uruchom w trybie `--cli`.

---

## 11) Bezpieczeństwo i odpowiedzialność

To narzędzie tradingowe – używasz go na własne ryzyko.

- Zacznij od małego rozmiaru pozycji.
- Ustaw limity ryzyka (stop-loss/daily loss).
- Nie uruchamiaj bez monitoringu.
- Przeczytaj: [LEGAL_NOTICE.md](LEGAL_NOTICE.md).

---

## 12) Licencja

MIT (szczegóły: [LICENSE](LICENSE)).
