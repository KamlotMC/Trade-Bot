"""NonKYC API Client."""
import hmac, hashlib, time, requests, json
from typing import Optional, Dict
from pathlib import Path
from dotenv import load_dotenv
import os

from .paths import find_project_file

class NonKYCClient:
    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None):
        self.base_url = "https://api.nonkyc.io/api/v2"
        
        if api_key and api_secret:
            self.api_key = api_key
            self.api_secret = api_secret
        else:
            load_dotenv(find_project_file(".env"))
            self.api_key = os.getenv("NONKYC_API_KEY", "")
            self.api_secret = os.getenv("NONKYC_API_SECRET", "")
        
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})
    
    def _sign(self, full_url: str, body: str = "") -> Dict:
        """Generate signature: api_key + full_url + body + nonce"""
        nonce = str(int(time.time() * 1000))
        data = f"{self.api_key}{full_url}{body}{nonce}"
        sig = hmac.new(self.api_secret.encode(), data.encode(), hashlib.sha256).hexdigest()
        return {"X-API-KEY": self.api_key, "X-API-NONCE": nonce, "X-API-SIGN": sig}
    
    def _request(self, method: str, endpoint: str, params: dict = None, signed: bool = False, as_json: bool = False) -> Dict:
        """Make API request with proper error handling."""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"

        query_params = params or {}
        body = ""
        request_kwargs = {"headers": {"Accept": "application/json"}, "timeout": 10}

        if as_json and method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
            body = json.dumps(query_params, separators=(",", ":"), sort_keys=True)
            request_kwargs["json"] = query_params
            full_url = url
        else:
            query_string = "&".join(f"{k}={v}" for k, v in sorted(query_params.items()))
            full_url = f"{url}?{query_string}" if query_string else url
            request_kwargs["params"] = query_params

        if signed:
            request_kwargs["headers"].update(self._sign(full_url, body=body))

        try:
            print(f"🔍 API Request: {method} {url} params={query_params} as_json={as_json}")
            r = self.session.request(method, url, **request_kwargs)
            print(f"📊 API Response: {r.status_code} - {r.text[:200]}")

            if r.status_code == 200:
                return r.json()
            return {"error": f"{r.status_code}: {r.text[:200]}"}
        except Exception as e:
            print(f"❌ API Exception: {e}")
            return {"error": str(e)}
    
    def get_ticker(self, symbol: str = "MEWC_USDT") -> Dict:
        """Get ticker - this one works"""
        return self._request("GET", f"ticker/{symbol}")
    
    def get_balances(self) -> Dict:
        """Get balances - try multiple endpoints"""
        for ep in ["balances", "account/balances", "wallet"]:
            result = self._request("GET", ep, signed=True)
            if "error" not in result:
                if isinstance(result, list):
                    return {"balances": result}
                return result
        return {"error": "All balance endpoints failed"}
    
    def get_my_trades(self, symbol: str = "MEWC_USDT", limit: int = 50) -> Dict:
        """Get my trades."""
        symbol_no_underscore = symbol.replace("_", "")
        
        endpoints_to_try = [
            ("account/trades", {"symbol": symbol, "limit": limit}),
            ("account/trades", {"symbol": symbol_no_underscore, "limit": limit}),
            ("myTrades", {"symbol": symbol, "limit": limit}),
            ("myTrades", {"symbol": symbol_no_underscore, "limit": limit}),
            ("user/trades", {"symbol": symbol, "limit": limit}),
            ("trades/my", {"symbol": symbol, "limit": limit}),
        ]
        
        for endpoint, params in endpoints_to_try:
            result = self._request("GET", endpoint, params=params, signed=True)
            if "error" not in result:
                if isinstance(result, list):
                    return {"trades": result}
                elif isinstance(result, dict) and "trades" in result:
                    return result
                elif isinstance(result, dict) and "data" in result:
                    if isinstance(result["data"], list):
                        return {"trades": result["data"]}
                    return result
                return {"trades": result}
        
        return {"error": "All trade endpoints failed"}
    
    def get_open_orders(self, symbol: str = "MEWC_USDT") -> Dict:
        return self._request("GET", "account/orders", params={"symbol": symbol.replace("_", "")}, signed=True)

    def get_orderbook(self, symbol: str = "MEWC_USDT", limit: int = 20) -> Dict:
        symbol_no_underscore = symbol.replace("_", "")
        for params in ({"symbol": symbol_no_underscore, "limit": limit}, {"symbol": symbol, "limit": limit}):
            result = self._request("GET", "market/orderbook", params=params, signed=False)
            if "error" not in result:
                return result
        return {"error": "Orderbook endpoint failed"}

    def cancel_order(self, order_id: str) -> Dict:
        endpoints_to_try = [
            ("POST", "cancelorder", {"id": order_id}),
            ("POST", "cancelOrder", {"id": order_id}),
            ("DELETE", f"account/orders/{order_id}", None),
        ]
        for method, endpoint, params in endpoints_to_try:
            result = self._request(method, endpoint, params=params, signed=True, as_json=(method != "GET"))
            if "error" not in result:
                return result
        return {"error": f"Failed to cancel order {order_id}"}

    def create_market_order(self, side: str, quantity: float, symbol: str = "MEWC_USDT") -> Dict:
        normalized_side = side.upper()
        symbol_no_underscore = symbol.replace("_", "")
        payloads = [
            {"symbol": symbol_no_underscore, "side": normalized_side, "type": "market", "quantity": quantity},
            {"symbol": symbol_no_underscore, "side": normalized_side, "type": "MARKET", "qty": quantity},
            {"symbol": symbol, "side": normalized_side, "type": "market", "quantity": quantity},
        ]
        for payload in payloads:
            result = self._request("POST", "createorder", params=payload, signed=True, as_json=True)
            if "error" not in result:
                return result
        return {"error": "Failed to create market order"}


    def create_limit_order(self, side: str, quantity: float, price: float, symbol: str = "MEWC_USDT") -> Dict:
        normalized_side = side.upper()
        symbol_no_underscore = symbol.replace("_", "")
        payloads = [
            {"symbol": symbol_no_underscore, "side": normalized_side, "type": "limit", "quantity": quantity, "price": price},
            {"symbol": symbol_no_underscore, "side": normalized_side, "type": "LIMIT", "qty": quantity, "rate": price},
            {"symbol": symbol, "side": normalized_side, "type": "limit", "quantity": quantity, "price": price},
        ]
        for payload in payloads:
            result = self._request("POST", "createorder", params=payload, signed=True, as_json=True)
            if "error" not in result:
                return result
        return {"error": "Failed to create limit order"}

    def cancel_all_orders(self, symbol: str = "MEWC_USDT") -> Dict:
        symbol_no_underscore = symbol.replace("_", "")
        for payload in ({"symbol": symbol_no_underscore}, {"symbol": symbol}):
            result = self._request("POST", "cancelallorders", params=payload, signed=True, as_json=True)
            if "error" not in result:
                return result
        return {"error": "Failed to cancel all orders"}
