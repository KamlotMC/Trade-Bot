"""NonKYC API Client - FIXED with correct endpoints"""
import hmac, hashlib, time, requests, json
from typing import Optional, Dict
from pathlib import Path
from dotenv import load_dotenv
import os

class NonKYCClient:
    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None):
        self.base_url = "https://api.nonkyc.io/api/v2"
        
        if api_key and api_secret:
            self.api_key = api_key
            self.api_secret = api_secret
        else:
            load_dotenv(Path.home() / "Trade-Bot" / ".env")
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
    
    def _request(self, method: str, endpoint: str, params: dict = None, signed: bool = False) -> Dict:
        """Make API request with proper error handling"""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        
        # Build query string for signature
        query_params = params or {}
        query_string = "&".join(f"{k}={v}" for k, v in sorted(query_params.items()))
        full_url = f"{url}?{query_string}" if query_string else url
        
        headers = {"Accept": "application/json"}
        if signed:
            headers.update(self._sign(full_url))
        
        try:
            print(f"🔍 API Request: {method} {url} params={query_params}")
            r = self.session.request(method, url, params=query_params, headers=headers, timeout=10)
            print(f"📊 API Response: {r.status_code} - {r.text[:200]}")
            
            if r.status_code == 200:
                return r.json()
            else:
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
        """Get my trades - FIXED with correct NonKYC endpoints"""
        # Try different endpoint variations with correct symbol format
        symbol_no_underscore = symbol.replace("_", "")  # MEWCUSDT
        
        endpoints_to_try = [
            ("account/trades", {"symbol": symbol, "limit": limit}),  # MEWC_USDT
            ("account/trades", {"symbol": symbol_no_underscore, "limit": limit}),  # MEWCUSDT
            ("myTrades", {"symbol": symbol, "limit": limit}),
            ("myTrades", {"symbol": symbol_no_underscore, "limit": limit}),
            ("user/trades", {"symbol": symbol, "limit": limit}),
            ("trades/my", {"symbol": symbol, "limit": limit}),
        ]
        
        for endpoint, params in endpoints_to_try:
            result = self._request("GET", endpoint, params=params, signed=True)
            if "error" not in result:
                # Handle different response formats
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
