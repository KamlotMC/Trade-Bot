import asyncio
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from dashboard.backend.data_store import DataStore
from dashboard.web.app import app


client = TestClient(app)


def test_datastore_dedupe_key_and_unique_insert(tmp_path):
    ds = DataStore(db_path=tmp_path / "t.db")
    payload = dict(side="BUY", quantity=10.0, price=1.25, fee=0.1, order_id="ord-1", source_trade_id="tr-1", timestamp="2024-01-01T00:00:00")

    first = ds.add_trade(**payload)
    second = ds.add_trade(**payload)

    rows = ds.get_trades(limit=50, days=3650)
    assert first is True
    assert second is False
    assert len(rows) == 1
    assert rows[0]["dedupe_key"]


def test_parallel_writes_are_safely_deduplicated(tmp_path):
    ds = DataStore(db_path=tmp_path / "parallel.db")

    def writer():
        return ds.add_trade(
            side="SELL",
            quantity=5.0,
            price=2.0,
            fee=0.0,
            order_id="ord-par",
            source_trade_id="tr-par",
            timestamp="2024-01-01T10:00:00",
        )

    with ThreadPoolExecutor(max_workers=20) as ex:
        results = list(ex.map(lambda _: writer(), range(80)))

    rows = ds.get_trades(limit=500, days=3650)
    assert sum(1 for r in results if r) == 1
    assert len(rows) == 1


def test_heavy_endpoints_concurrent_load_no_500():
    endpoints = [
        ("GET", "/api/portfolio", None),
        ("GET", "/api/fills", None),
        ("POST", "/api/trades/sync-from-exchange", None),
    ]

    async def run_calls():
        async def one(method: str, url: str, body):
            return await asyncio.to_thread(
                client.post if method == "POST" else client.get,
                url,
                json=body,
            ) if method == "POST" else await asyncio.to_thread(client.get, url)

        tasks = [one(m, u, b) for _ in range(5) for (m, u, b) in endpoints]
        return await asyncio.gather(*tasks)

    responses = asyncio.run(run_calls())
    assert all(r.status_code < 500 for r in responses)
