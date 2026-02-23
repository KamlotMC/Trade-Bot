import subprocess
import time

import requests

BASE_URL = "http://127.0.0.1:8011"


def _start_server():
    proc = subprocess.Popen(
        ["python", "-m", "uvicorn", "dashboard.web.app:app", "--host", "127.0.0.1", "--port", "8011"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(30):
        try:
            requests.get(f"{BASE_URL}/", timeout=1)
            return proc
        except Exception:
            time.sleep(0.2)
    proc.terminate()
    raise RuntimeError("Server did not start")


def _stop_server(proc):
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def test_dashboard_endpoints_smoke():
    proc = _start_server()
    try:
        assert requests.get(f"{BASE_URL}/", timeout=5).status_code == 200

        rules = requests.get(f"{BASE_URL}/api/automation-rules", timeout=5)
        assert rules.status_code == 200
        assert isinstance(rules.json(), list)

        invalid_manual = requests.post(
            f"{BASE_URL}/api/orders/manual",
            json={"side": "INVALID", "quantity": 0},
            timeout=5,
        )
        assert invalid_manual.status_code == 200
        assert invalid_manual.json()["ok"] is False

        risk = requests.get(f"{BASE_URL}/api/risk-cockpit", timeout=10)
        assert risk.status_code == 200
        data = risk.json()
        for key in ["inventory_ratio", "target_ratio", "drawdown_pct", "risk_state"]:
            assert key in data

        journal = requests.get(f"{BASE_URL}/api/strategy-journal", timeout=5)
        assert journal.status_code == 200
        assert isinstance(journal.json(), list)
    finally:
        _stop_server(proc)


if __name__ == "__main__":
    test_dashboard_endpoints_smoke()
    print("Dashboard smoke test passed")
