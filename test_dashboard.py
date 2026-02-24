from fastapi.testclient import TestClient

from dashboard.web.app import app, build_confirm_token, manual_order_preflight
from dashboard.backend.services import TradingService

client = TestClient(app)


def test_dashboard_core_endpoints_no_500():
    checks = [
        ("GET", "/"),
        ("GET", "/api/price"),
        ("GET", "/api/portfolio"),
        ("GET", "/api/pnl"),
        ("GET", "/api/pnl-saldo"),
        ("GET", "/api/win-rate"),
        ("GET", "/api/fills"),
        ("POST", "/api/trades/sync-from-exchange"),
        ("POST", "/api/orders/cancel-all"),
        ("GET", "/api/risk-cockpit"),
        ("GET", "/api/backtest-replay-summary"),
        ("GET", "/api/strategy-journal"),
        ("GET", "/api/automation-rules"),
        ("GET", "/api/open-orders"),
        ("GET", "/api/orderbook"),
        ("GET", "/api/history"),
        ("GET", "/api/bot-status"),
        ("GET", "/api/order-lifecycle"),
        ("GET", "/api/order-lifecycle-metrics"),
        ("GET", "/api/errors"),
        ("GET", "/api/profitability"),
        ("GET", "/api/execution-quality"),
        ("GET", "/api/live-risk"),
        ("GET", "/api/live-pnl"),
        ("POST", "/api/backtest/import"),
        ("GET", "/api/backtest/compare"),
        ("GET", "/api/strategy-reason-trace"),
    ]

    for method, url in checks:
        if method == "GET":
            res = client.get(url)
        else:
            payload = {"dataset": "d", "candles": 10} if url == "/api/backtest/import" else None
            res = client.post(url, json=payload) if payload else client.post(url)
        assert res.status_code < 500, f"{method} {url} failed with {res.status_code}: {res.text[:300]}"


def test_manual_preflight_and_confirm_token_deterministic():
    payload = {
        "side": "BUY",
        "type": "LIMIT",
        "quantity": 300000,
        "price": 0.00004,
        "reduce_only": False,
    }

    p1 = manual_order_preflight(payload)
    p2 = manual_order_preflight(payload)

    assert p1["ok"] is True
    assert p1["confirm_required"] is True
    assert p1["confirm_token"] == p2["confirm_token"]

    expected = build_confirm_token("BUY", "LIMIT", 300000.0, 0.00004, False)
    assert p1["confirm_token"] == expected


def test_manual_order_invalid_payload_returns_error_message():
    res = client.post("/api/orders/manual", json={"side": "INVALID", "quantity": 0})
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is False
    assert body.get("error")


def test_builder_and_preflight_endpoints_payloads():
    pre = client.post(
        "/api/orders/preflight",
        json={"side": "BUY", "type": "LIMIT", "quantity": 1000, "price": 0.00004, "reduce_only": True},
    )
    assert pre.status_code == 200
    pre_j = pre.json()
    for key in ["estimated_notional_usdt", "estimated_fee_usdt", "min_qty", "min_notional_usdt"]:
        assert key in pre_j

    rule = client.post(
        "/api/automation-rules/builder",
        json={
            "name": "Rule test",
            "if": {"type": "spread", "operator": ">", "value": 1.2},
            "then": {"action": "notify"},
            "time_window": "always",
        },
    )
    assert rule.status_code == 200
    rule_j = rule.json()
    assert rule_j["ok"] is True
    assert rule_j["rule"]["if"]["type"] == "spread"


if __name__ == "__main__":
    test_dashboard_core_endpoints_no_500()
    test_manual_preflight_and_confirm_token_deterministic()
    test_manual_order_invalid_payload_returns_error_message()
    test_builder_and_preflight_endpoints_payloads()
    print("Dashboard global tests passed")


def test_open_orders_filter_excludes_closed_items():
    class StubApi:
        def get_open_orders(self, symbol):
            return {
                "orders": [
                    {"id": "1", "side": "BUY", "price": "0.1", "quantity": "10", "status": "FILLED", "executedQty": "10"},
                    {"id": "2", "side": "SELL", "price": "0.2", "quantity": "5", "status": "OPEN", "remaining": "5"},
                    {"id": "3", "side": "BUY", "price": "0.3", "quantity": "4", "status": "CANCELED", "remaining": "0"},
                ]
            }

    service = TradingService(api_client=StubApi(), data_store=None)
    rows = service.get_open_orders("MEWC_USDT")
    assert [r["id"] for r in rows] == ["2"]


def test_price_endpoint_parses_snake_case_payload(monkeypatch):
    from dashboard.web import app as app_mod

    class Resp:
        ok = True

        def json(self):
            return {
                "last_price": "0.123",
                "bid": "0.12",
                "ask": "0.13",
                "change_percent": "+1.5",
                "usd_volume_est": "99.5",
            }

    monkeypatch.setattr(app_mod.requests, "get", lambda *args, **kwargs: Resp())
    data = app_mod.get_price_data()

    assert data["last_price"] == 0.123
    assert data["volume"] == 99.5
