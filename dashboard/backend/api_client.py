"""NonKYC API Client."""
import hashlib
import hmac
import json
import logging
import os
import time
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import requests
from dotenv import load_dotenv

from .paths import find_project_file

logger = logging.getLogger(__name__)

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
    
    def _sign(self, url: str, body: str = "") -> Dict[str, str]:
        """Generate HMAC-SHA256 signature zgodnie z NonKYC API v2.
        
        Format: HMAC(api_key + url_without_query + body + nonce)
        gdzie url_without_query to URL bez parametrów GET.
        Taki sam format jak w market_maker/exchange_client.py.
        """
        nonce = str(int(time.time() * 1000))
        # Wyciągnij tylko bazowy URL bez query string
        base_url = url.split("?")[0]
        data_to_sign = f"{self.api_key}{base_url}{body}{nonce}"
        sig = hmac.new(self.api_secret.encode(), data_to_sign.encode(), hashlib.sha256).hexdigest()
        return {"X-API-KEY": self.api_key, "X-API-NONCE": nonce, "X-API-SIGN": sig}
    
    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        signed: bool = False,
        as_json: bool = False,
    ) -> Dict[str, Any]:
        """Make API request with proper error handling."""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"

        query_params = params or {}
        body = ""
        request_kwargs = {"headers": {"Accept": "application/json"}, "timeout": 10}
        request_method = method.upper()

        if as_json and request_method in {"POST", "PUT", "PATCH", "DELETE"}:
            body = json.dumps(query_params, separators=(",", ":"), sort_keys=True)
            request_kwargs["data"] = body
            request_kwargs["headers"]["Content-Type"] = "application/json"
            full_url = url
        else:
            query_string = urlencode(sorted(query_params.items()))
            full_url = f"{url}?{query_string}" if query_string else url
            request_kwargs["params"] = query_params

        if signed:
            request_kwargs["headers"].update(self._sign(full_url, body=body))

        try:
            logger.debug("API request %s %s params=%s as_json=%s", request_method, url, query_params, as_json)
            r = self.session.request(request_method, url, **request_kwargs)
            logger.debug("API response %s %s", r.status_code, r.text[:200])

            if 200 <= r.status_code < 300:
                try:
                    return r.json()
                except ValueError:
                    return {"ok": True, "raw": r.text}
            return {"error": f"{r.status_code}: {r.text[:200]}"}
        except Exception as e:
            logger.exception("API request failed")
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
    
    def get_my_trades(self, symbol: str = "MEWC_USDT", limit: int = 200) -> Dict:
        """Get trade history via filled/closed orders.
        
        NonKYC API v2 nie udostępnia dedykowanego endpointu historii tradów.
        Historia transakcji to zlecenia ze statusem 'filled' lub 'closed'.
        """
        sym_slash = symbol.replace("_", "/")   # MEWC/USDT
        sym_under = symbol.replace("/", "_")   # MEWC_USDT

        # Próbuj oba formaty symbolu i oba statusy
        attempts = [
            ("account/orders", {"symbol": sym_slash, "status": "filled",  "limit": limit}),
            ("account/orders", {"symbol": sym_under, "status": "filled",  "limit": limit}),
            ("account/orders", {"symbol": sym_slash, "status": "closed",  "limit": limit}),
            ("account/orders", {"symbol": sym_under, "status": "closed",  "limit": limit}),
            # Fallback: wszystkie zlecenia bez filtra statusu
            ("account/orders", {"symbol": sym_slash, "limit": limit}),
            ("account/orders", {"symbol": sym_under, "limit": limit}),
        ]

        for endpoint, params in attempts:
            result = self._request("GET", endpoint, params=params, signed=True)
            if "error" in result:
                continue
            orders = result if isinstance(result, list) else result.get("data", result.get("orders", []))
            if not isinstance(orders, list):
                continue
            # Przefiltruj żeby zwrócić tylko faktycznie wypełnione
            filled = [
                o for o in orders
                if str(o.get("status", "")).lower() in ("filled", "closed", "partially_filled")
                or float(o.get("executedQty", o.get("filled_quantity", o.get("filledQuantity", 0))) or 0) > 0
            ]
            if filled or orders:
                logger.info(
                    "get_my_trades: endpoint=%s symbol=%s → %d orders (%d filled)",
                    endpoint, params["symbol"], len(orders), len(filled)
                )
                return {"trades": filled or orders}

        return {"error": "All trade endpoints failed — NonKYC API może nie udostępniać historii tradów publicznie"}
    
    def get_open_orders(self, symbol: str = "MEWC_USDT") -> Dict:
        # Try both symbol formats: MEWC/USDT and MEWC_USDT
        # Do NOT pass status=active — NonKYC returns active orders by default on this endpoint
        sym_slash = symbol.replace("_", "/")
        sym_under = symbol.replace("/", "_")
        for sym in (sym_slash, sym_under):
            result = self._request("GET", "account/orders", params={"symbol": sym}, signed=True)
            if "error" not in result:
                return result
        return {"error": f"Failed to get open orders for {symbol}"}

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
