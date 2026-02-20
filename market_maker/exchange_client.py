"""
NonKYC Exchange REST API client for the Meowcoin Market Maker.

Implements HMAC-SHA256 signed requests per the NonKYC API v2 specification.
All private endpoints use the X-API-KEY, X-API-NONCE, X-API-SIGN headers.
"""

import hashlib
import hmac
import json
import logging
import re
import time
import uuid
from decimal import Decimal, ROUND_DOWN
from typing import Any, Dict, List, Optional

import requests

from market_maker.config import ExchangeConfig

logger = logging.getLogger("mewc_mm.exchange")


class NonKYCClient:
    """REST client for the NonKYC exchange."""

    def __init__(self, config: ExchangeConfig):
        self.base_url = config.base_url.rstrip("/")
        self.api_key = self._sanitize_credential(config.api_key)
        self.api_secret = self._sanitize_credential(config.api_secret)
        self.symbol = config.symbol
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

        # Market metadata cache
        self._price_decimals: Optional[int] = None
        self._quantity_decimals: Optional[int] = None

        # Log masked key for debugging
        if self.api_key:
            masked = self.api_key[:4] + "****" + self.api_key[-4:]
            logger.info(
                "API key loaded: %s  (length %d)", masked, len(self.api_key)
            )

    # -------------------------------------------------------------------------
    # Credential sanitisation
    # -------------------------------------------------------------------------

    @staticmethod
    def _sanitize_credential(value: str) -> str:
        """Strip whitespace, quotes, and invisible characters from a credential.

        Users frequently copy-paste API keys with trailing newlines, spaces,
        smart-quotes, or zero-width characters.  This normalises the value
        so the HMAC signature is computed on the correct bytes.
        """
        if not value:
            return ""
        # Strip leading/trailing whitespace (including \r\n)
        value = value.strip()
        # Remove surrounding quotes (single or double, straight or smart)
        for q in ('"', "'", "\u201c", "\u201d", "\u2018", "\u2019"):
            if value.startswith(q) and value.endswith(q):
                value = value[len(q):-len(q)]
        # Remove common invisible / zero-width characters
        value = re.sub(r"[\u200b\u200c\u200d\ufeff\u00a0]", "", value)
        return value.strip()

    # -------------------------------------------------------------------------
    # Authentication helpers
    # -------------------------------------------------------------------------

    def _sign_get(self, url: str) -> Dict[str, str]:
        """Build signed headers for a GET request."""
        nonce = str(int(time.time() * 1e3))
        data_to_sign = f"{self.api_key}{url}{nonce}"
        signature = hmac.new(
            self.api_secret.encode(),
            data_to_sign.encode(),
            hashlib.sha256,
        ).hexdigest()
        return {
            "X-API-KEY": self.api_key,
            "X-API-NONCE": nonce,
            "X-API-SIGN": signature,
        }

    def _sign_post(self, url: str, body_str: str) -> Dict[str, str]:
        """Build signed headers for a POST request."""
        nonce = str(int(time.time() * 1e3))
        data_to_sign = f"{self.api_key}{url}{body_str}{nonce}"
        signature = hmac.new(
            self.api_secret.encode(),
            data_to_sign.encode(),
            hashlib.sha256,
        ).hexdigest()
        return {
            "X-API-KEY": self.api_key,
            "X-API-NONCE": nonce,
            "X-API-SIGN": signature,
        }

    # -------------------------------------------------------------------------
    # HTTP helpers
    # -------------------------------------------------------------------------

    def _get(self, path: str, params: Optional[Dict] = None, signed: bool = False) -> Any:
        """Execute a GET request."""
        url = f"{self.base_url}/{path.lstrip('/')}"
        if params:
            query = "&".join(f"{k}={v}" for k, v in params.items())
            full_url = f"{url}?{query}"
        else:
            full_url = url

        headers = {}
        if signed:
            headers = self._sign_get(full_url)

        resp = self.session.get(full_url, headers=headers, timeout=15)
        self._check_response(resp)
        return resp.json()

    def _post(self, path: str, body: Dict, signed: bool = True) -> Any:
        """Execute a POST request."""
        url = f"{self.base_url}/{path.lstrip('/')}"
        body_str = json.dumps(body, separators=(",", ":"))

        headers = {}
        if signed:
            headers = self._sign_post(url, body_str)

        resp = self.session.post(url, data=body_str, headers=headers, timeout=15)
        self._check_response(resp)
        return resp.json()

    @staticmethod
    def _check_response(resp: requests.Response) -> None:
        """Check response and raise with a clear error message."""
        try:
            resp.raise_for_status()
        except requests.HTTPError:
            # Provide specific guidance for authentication errors
            if resp.status_code in (401, 403):
                body = resp.text[:200]
                raise RuntimeError(
                    f"Authentication failed ({resp.status_code}): {body}\n\n"
                    "Possible causes:\n"
                    "  1. API key or secret is incorrect — double-check "
                    "them on nonkyc.io under Account > API Keys.\n"
                    "  2. Copy-paste error — make sure there are no extra "
                    "spaces, quotes, or invisible characters.\n"
                    "  3. The API key does not have trading permissions "
                    "enabled on the exchange.\n"
                    "  4. The API key may have been revoked or expired.\n"
                    "  5. Your system clock may be significantly out of "
                    "sync (the exchange rejects stale nonces)."
                ) from None

            # Try to extract the exchange's error message
            try:
                data = resp.json()
                err = data.get("error", {})
                msg = err.get("message", resp.text)
                desc = err.get("description", "")
                raise RuntimeError(
                    f"API error {resp.status_code}: {msg}"
                    + (f" — {desc}" if desc else "")
                ) from None
            except (ValueError, KeyError):
                raise RuntimeError(
                    f"API error {resp.status_code}: {resp.text[:200]}"
                ) from None

        # Also check for JSON-level errors (some endpoints return 200 with error body)
        try:
            data = resp.json()
            if isinstance(data, dict) and "error" in data:
                err = data["error"]
                msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
                raise RuntimeError(f"Exchange error: {msg}")
        except (ValueError, AttributeError):
            pass

    # -------------------------------------------------------------------------
    # Public endpoints
    # -------------------------------------------------------------------------

    def get_server_time(self) -> int:
        """Get exchange server time (Unix ms)."""
        data = self._get("time")
        return data.get("serverTime", int(time.time() * 1000))

    def test_connection(self) -> Dict[str, Any]:
        """Test API connectivity and authentication.

        Returns a dict with:
          - ok (bool): True if everything works
          - public (bool): True if the public API is reachable
          - authenticated (bool): True if the signed request succeeded
          - server_time_delta_ms (int): local minus server clock (ms)
          - error (str): Error description when ok is False
        """
        result: Dict[str, Any] = {
            "ok": False,
            "public": False,
            "authenticated": False,
            "server_time_delta_ms": 0,
            "error": "",
        }

        # 1. Public API check
        try:
            server_time = self.get_server_time()
            result["public"] = True
            local_time = int(time.time() * 1000)
            result["server_time_delta_ms"] = local_time - server_time
            logger.info(
                "Public API OK.  Server-time delta: %+d ms",
                result["server_time_delta_ms"],
            )
        except Exception as exc:
            result["error"] = f"Cannot reach public API: {exc}"
            logger.error(result["error"])
            return result

        # 2. Warn on excessive clock skew (> 30 s)
        if abs(result["server_time_delta_ms"]) > 30_000:
            logger.warning(
                "Large clock skew detected (%+d ms). "
                "This may cause authentication failures.  "
                "Please synchronise your system clock.",
                result["server_time_delta_ms"],
            )

        # 3. Authenticated check — lightweight balance call
        if not self.api_key or not self.api_secret:
            result["error"] = "API key or secret is empty."
            logger.error(result["error"])
            return result

        try:
            self.get_balances()
            result["authenticated"] = True
            result["ok"] = True
            logger.info("Authentication OK — credentials are valid.")
        except Exception as exc:
            result["error"] = str(exc)
            logger.error("Authentication FAILED: %s", exc)

        return result

    def get_market_info(self, symbol: Optional[str] = None) -> Dict:
        """Get market metadata (price decimals, quantity decimals, etc.)."""
        sym = symbol or self.symbol
        return self._get("market/info", params={"symbol": sym})

    def get_orderbook(self, symbol: Optional[str] = None, limit: int = 20) -> Dict:
        """
        Get the current order book.

        Returns: {"bids": [{"price": str, "quantity": str}, ...],
                  "asks": [...], "symbol": str}
        """
        sym = symbol or self.symbol
        return self._get("market/orderbook", params={"symbol": sym, "limit": limit})

    def get_ticker(self, symbol: Optional[str] = None) -> Dict:
        """Get 24h ticker data for the symbol."""
        sym = (symbol or self.symbol).replace("/", "_")
        return self._get(f"ticker/{sym}")

    def get_trades(self, symbol: Optional[str] = None, limit: int = 50) -> List[Dict]:
        """Get recent public trades."""
        sym = symbol or self.symbol
        return self._get("market/trades", params={"symbol": sym, "limit": limit})

    # -------------------------------------------------------------------------
    # Private endpoints
    # -------------------------------------------------------------------------

    def get_balances(self) -> List[Dict]:
        """
        Get all account balances.

        Returns: [{"asset": "MEWC", "available": "1000", "held": "0"}, ...]
        """
        return self._get("balances", signed=True)

    def get_balance(self, asset: str) -> Dict:
        """Get balance for a specific asset."""
        balances = self.get_balances()
        for b in balances:
            if b.get("asset", "").upper() == asset.upper():
                return b
        return {"asset": asset, "available": "0", "held": "0"}

    def get_active_orders(self, symbol: Optional[str] = None) -> List[Dict]:
        """Get all active/open orders, optionally filtered by symbol."""
        params = {"status": "active"}
        if symbol:
            params["symbol"] = symbol
        return self._get("account/orders", params=params, signed=True)

    def get_order(self, order_id: str) -> Dict:
        """Get an order by ID."""
        return self._get(f"getorder/{order_id}", signed=True)

    def create_order(
        self,
        side: str,
        quantity: str,
        price: str,
        symbol: Optional[str] = None,
        order_type: str = "limit",
        user_provided_id: Optional[str] = None,
    ) -> Dict:
        """
        Place a new limit order.

        Args:
            side: "buy" or "sell"
            quantity: Order quantity as a string
            price: Order price as a string
            symbol: Trading pair (default: configured symbol)
            order_type: "limit" or "market"
            user_provided_id: Optional client order ID

        Returns: Order object from exchange
        """
        body: Dict[str, Any] = {
            "symbol": symbol or self.symbol,
            "side": side,
            "type": order_type,
            "quantity": quantity,
            "price": price,
        }
        if user_provided_id:
            body["userProvidedId"] = user_provided_id
        else:
            body["userProvidedId"] = str(uuid.uuid4()).replace("-", "")

        logger.info(
            "CREATE ORDER  side=%s price=%s qty=%s symbol=%s",
            side, price, quantity, body["symbol"],
        )
        return self._post("createorder", body)

    def cancel_order(self, order_id: str) -> Dict:
        """Cancel an open order by its exchange-assigned ID."""
        logger.info("CANCEL ORDER  id=%s", order_id)
        return self._post("cancelorder", {"id": order_id})

    def cancel_all_orders(self, symbol: Optional[str] = None, side: str = "all") -> Dict:
        """Cancel all open orders for a symbol."""
        body: Dict[str, str] = {"side": side}
        if symbol:
            body["symbol"] = symbol
        else:
            body["symbol"] = self.symbol
        logger.info("CANCEL ALL ORDERS  symbol=%s side=%s", body["symbol"], side)
        return self._post("cancelallorders", body)

    # -------------------------------------------------------------------------
    # Market metadata helpers
    # -------------------------------------------------------------------------

    def load_market_metadata(self) -> None:
        """Fetch and cache price/quantity decimal precision from the market."""
        info = self.get_market_info()
        self._price_decimals = info.get("priceDecimals", 8)
        self._quantity_decimals = info.get("quantityDecimals", 2)
        logger.info(
            "Market metadata loaded: priceDecimals=%d quantityDecimals=%d",
            self._price_decimals, self._quantity_decimals,
        )

    @property
    def price_decimals(self) -> int:
        if self._price_decimals is None:
            self.load_market_metadata()
        return self._price_decimals  # type: ignore

    @property
    def quantity_decimals(self) -> int:
        if self._quantity_decimals is None:
            self.load_market_metadata()
        return self._quantity_decimals  # type: ignore

    def format_price(self, price: float) -> str:
        """Round and format a price to the exchange's required decimal places."""
        d = Decimal(str(price)).quantize(
            Decimal(10) ** -self.price_decimals, rounding=ROUND_DOWN
        )
        return str(d)

    def format_quantity(self, qty: float) -> str:
        """Round and format a quantity to the exchange's required decimal places."""
        d = Decimal(str(qty)).quantize(
            Decimal(10) ** -self.quantity_decimals, rounding=ROUND_DOWN
        )
        return str(d)
