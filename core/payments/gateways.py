"""
GhYiAb V2 — Payment Gateways
=============================

پشتیبانی از درگاه‌های پرداخت مختلف:
- زرین‌پال (Zarinpal)
- زرین‌پی (Zarinpey)
- آقای پرداخت (AqayePardakht)
- پلیسیو (Plisio) - کریپتو
- ناو پیمنتس (NowPayments) - کریپتو
- استارز تلگرام (Telegram Stars)

همه درگاه‌ها یک اینترفیس مشترک دارند.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

import requests

logger = logging.getLogger("ghyiab.payments.gateways")


# =============================================================================
# Base Classes
# =============================================================================

@dataclass(frozen=True)
class PaymentRequest:
    """Request to initiate a payment."""
    amount_minor: int           # Amount in minor units (rials/IRT)
    currency: str               # "IRT", "IRR", "USDT", "TON", "TRX"
    order_id: int               # Internal order ID
    description: str
    callback_url: str
    mobile: Optional[str] = None
    email: Optional[str] = None
    metadata: Optional[dict] = None


@dataclass(frozen=True)
class PaymentResponse:
    """Response from payment gateway initiation."""
    success: bool
    payment_url: Optional[str] = None
    authority: Optional[str] = None  # Gateway transaction ID
    reference_id: Optional[str] = None
    error: Optional[str] = None
    raw_response: Optional[dict] = None


@dataclass(frozen=True)
class VerificationResult:
    """Result of payment verification."""
    success: bool
    verified: bool
    amount_minor: Optional[int] = None
    reference_id: Optional[str] = None
    card_pan: Optional[str] = None
    error: Optional[str] = None
    raw_response: Optional[dict] = None


class PaymentGateway(ABC):
    """Abstract base class for payment gateways."""

    name: str = "base"

    def __init__(self, config: dict):
        self.config = config

    @abstractmethod
    def create_payment(self, request: PaymentRequest) -> PaymentResponse:
        """Create a payment request and return payment URL."""
        pass

    @abstractmethod
    def verify_payment(self, authority: str, amount_minor: int) -> VerificationResult:
        """Verify a payment after user returns from gateway."""
        pass

    @abstractmethod
    def is_configured(self) -> bool:
        """Check if gateway is properly configured."""
        pass

    def _build_callback_url(self, base_url: str, gateway_name: str) -> str:
        """Build callback URL for this gateway."""
        return f"{base_url.rstrip('/')}/payment/callback/{gateway_name}"


# =============================================================================
# Zarinpal Gateway
# =============================================================================

class ZarinpalGateway(PaymentGateway):
    """Zarinpal payment gateway (Iran)."""
    name = "zarinpal"

    def __init__(self, config: dict):
        super().__init__(config)
        self.merchant_id = config.get("merchant_id", "").strip()
        self.sandbox = config.get("sandbox", False)
        self.base_url = "https://sandbox.zarinpal.com/pg/v4" if self.sandbox else "https://api.zarinpal.com/pg/v4"

    def is_configured(self) -> bool:
        return bool(self.merchant_id)

    def create_payment(self, request: PaymentRequest) -> PaymentResponse:
        if not self.is_configured():
            return PaymentResponse(success=False, error="Zarinpal not configured")

        url = f"{self.base_url}/payment/request.json"
        data = {
            "merchant_id": self.merchant_id,
            "amount": request.amount_minor,
            "description": request.description,
            "callback_url": request.callback_url,
            "metadata": request.metadata or {"order_id": request.order_id},
        }

        if request.mobile:
            data["mobile"] = request.mobile
        if request.email:
            data["email"] = request.email

        try:
            resp = requests.post(url, json=data, timeout=30)
            resp.raise_for_status()
            result = resp.json()

            if result.get("data", {}).get("code") == 100:
                authority = result["data"]["authority"]
                payment_url = f"https://{'sandbox.' if self.sandbox else ''}zarinpal.com/pg/StartPay/{authority}"
                return PaymentResponse(
                    success=True,
                    payment_url=payment_url,
                    authority=authority,
                    reference_id=authority,
                    raw_response=result
                )
            else:
                error_msg = result.get("errors", {}).get("message", "Unknown error")
                return PaymentResponse(success=False, error=error_msg, raw_response=result)

        except Exception as e:
            logger.exception("Zarinpal create_payment failed: %s", e)
            return PaymentResponse(success=False, error=str(e))

    def verify_payment(self, authority: str, amount_minor: int) -> VerificationResult:
        if not self.is_configured():
            return VerificationResult(success=False, verified=False, error="Zarinpal not configured")

        url = f"{self.base_url}/payment/verify.json"
        data = {
            "merchant_id": self.merchant_id,
            "authority": authority,
            "amount": amount_minor,
        }

        try:
            resp = requests.post(url, json=data, timeout=30)
            resp.raise_for_status()
            result = resp.json()

            if result.get("data", {}).get("code") == 100:
                ref_id = result["data"].get("ref_id")
                return VerificationResult(
                    success=True,
                    verified=True,
                    amount_minor=amount_minor,
                    reference_id=str(ref_id) if ref_id else authority,
                    raw_response=result
                )
            else:
                error_msg = result.get("errors", {}).get("message", "Verification failed")
                return VerificationResult(success=True, verified=False, error=error_msg, raw_response=result)

        except Exception as e:
            logger.exception("Zarinpal verify_payment failed: %s", e)
            return VerificationResult(success=False, verified=False, error=str(e))


# =============================================================================
# Zarinpey Gateway
# =============================================================================

class ZarinpeyGateway(PaymentGateway):
    """Zarinpey payment gateway (Iran)."""
    name = "zarinpey"

    def __init__(self, config: dict):
        super().__init__(config)
        self.merchant_id = config.get("merchant_id", "").strip()
        self.api_key = config.get("api_key", "").strip()
        self.sandbox = config.get("sandbox", False)
        self.base_url = "https://sandbox.zarinpey.com/api/v1" if self.sandbox else "https://api.zarinpey.com/api/v1"

    def is_configured(self) -> bool:
        return bool(self.merchant_id and self.api_key)

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def create_payment(self, request: PaymentRequest) -> PaymentResponse:
        if not self.is_configured():
            return PaymentResponse(success=False, error="Zarinpey not configured")

        url = f"{self.base_url}/payment/request"
        data = {
            "merchant_id": self.merchant_id,
            "amount": request.amount_minor,
            "description": request.description,
            "callback_url": request.callback_url,
            "order_id": str(request.order_id),
        }

        if request.mobile:
            data["mobile"] = request.mobile
        if request.email:
            data["email"] = request.email

        try:
            resp = requests.post(url, json=data, headers=self._headers(), timeout=30)
            resp.raise_for_status()
            result = resp.json()

            if result.get("status") == "success":
                authority = result["data"]["token"]
                payment_url = f"https://{'sandbox.' if self.sandbox else ''}zarinpey.com/pay/{authority}"
                return PaymentResponse(
                    success=True,
                    payment_url=payment_url,
                    authority=authority,
                    reference_id=authority,
                    raw_response=result
                )
            else:
                return PaymentResponse(success=False, error=result.get("message", "Unknown error"), raw_response=result)

        except Exception as e:
            logger.exception("Zarinpey create_payment failed: %s", e)
            return PaymentResponse(success=False, error=str(e))

    def verify_payment(self, authority: str, amount_minor: int) -> VerificationResult:
        if not self.is_configured():
            return VerificationResult(success=False, verified=False, error="Zarinpey not configured")

        url = f"{self.base_url}/payment/verify"
        data = {
            "merchant_id": self.merchant_id,
            "token": authority,
            "amount": amount_minor,
        }

        try:
            resp = requests.post(url, json=data, headers=self._headers(), timeout=30)
            resp.raise_for_status()
            result = resp.json()

            if result.get("status") == "success":
                ref_id = result["data"].get("ref_id")
                return VerificationResult(
                    success=True,
                    verified=True,
                    amount_minor=amount_minor,
                    reference_id=str(ref_id) if ref_id else authority,
                    raw_response=result
                )
            else:
                return VerificationResult(success=True, verified=False, error=result.get("message", "Verification failed"), raw_response=result)

        except Exception as e:
            logger.exception("Zarinpey verify_payment failed: %s", e)
            return VerificationResult(success=False, verified=False, error=str(e))


# =============================================================================
# AqayePardakht Gateway
# =============================================================================

class AqayePardakhtGateway(PaymentGateway):
    """AqayePardakht payment gateway (Iran)."""
    name = "aqayepardakht"

    def __init__(self, config: dict):
        super().__init__(config)
        self.merchant_id = config.get("merchant_id", "").strip()
        self.terminal_id = config.get("terminal_id", "").strip()
        self.password = config.get("password", "").strip()
        self.sandbox = config.get("sandbox", False)
        self.base_url = "https://sandbox.aqayepardakht.ir/api/v1" if self.sandbox else "https://api.aqayepardakht.ir/api/v1"

    def is_configured(self) -> bool:
        return bool(self.merchant_id and self.terminal_id and self.password)

    def create_payment(self, request: PaymentRequest) -> PaymentResponse:
        if not self.is_configured():
            return PaymentResponse(success=False, error="AqayePardakht not configured")

        url = f"{self.base_url}/request"
        data = {
            "merchant_id": self.merchant_id,
            "terminal_id": self.terminal_id,
            "password": self.password,
            "amount": request.amount_minor,
            "description": request.description,
            "callback_url": request.callback_url,
            "order_id": str(request.order_id),
        }

        try:
            resp = requests.post(url, json=data, timeout=30)
            resp.raise_for_status()
            result = resp.json()

            if result.get("status") == 1:
                token = result["token"]
                payment_url = f"https://{'sandbox.' if self.sandbox else ''}aqayepardakht.ir/startpay/{token}"
                return PaymentResponse(
                    success=True,
                    payment_url=payment_url,
                    authority=token,
                    reference_id=token,
                    raw_response=result
                )
            else:
                return PaymentResponse(success=False, error=result.get("message", "Unknown error"), raw_response=result)

        except Exception as e:
            logger.exception("AqayePardakht create_payment failed: %s", e)
            return PaymentResponse(success=False, error=str(e))

    def verify_payment(self, authority: str, amount_minor: int) -> VerificationResult:
        if not self.is_configured():
            return VerificationResult(success=False, verified=False, error="AqayePardakht not configured")

        url = f"{self.base_url}/verify"
        data = {
            "merchant_id": self.merchant_id,
            "terminal_id": self.terminal_id,
            "password": self.password,
            "token": authority,
            "amount": amount_minor,
        }

        try:
            resp = requests.post(url, json=data, timeout=30)
            resp.raise_for_status()
            result = resp.json()

            if result.get("status") == 1:
                ref_id = result.get("ref_id")
                return VerificationResult(
                    success=True,
                    verified=True,
                    amount_minor=amount_minor,
                    reference_id=str(ref_id) if ref_id else authority,
                    raw_response=result
                )
            else:
                return VerificationResult(success=True, verified=False, error=result.get("message", "Verification failed"), raw_response=result)

        except Exception as e:
            logger.exception("AqayePardakht verify_payment failed: %s", e)
            return VerificationResult(success=False, verified=False, error=str(e))


# =============================================================================
# Plisio Gateway (Crypto)
# =============================================================================

class PlisioGateway(PaymentGateway):
    """Plisio cryptocurrency payment gateway."""
    name = "plisio"

    def __init__(self, config: dict):
        super().__init__(config)
        self.api_key = config.get("api_key", "").strip()
        self.base_url = "https://api.plisio.net/api/v1"

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def create_payment(self, request: PaymentRequest) -> PaymentResponse:
        if not self.is_configured():
            return PaymentResponse(success=False, error="Plisio not configured")

        url = f"{self.base_url}/operations/invoice/new"
        data = {
            "source_currency": "IRT" if request.currency == "IRT" else "USD",
            "source_amount": request.amount_minor / 10 if request.currency == "IRT" else request.amount_minor / 100,
            "currency": request.currency if request.currency in ("USDT", "BTC", "ETH", "LTC", "TRX", "TON") else "USDT",
            "order_number": str(request.order_id),
            "order_name": request.description,
            "callback_url": request.callback_url,
            "success_url": request.callback_url.replace("/callback/", "/success/"),
            "cancel_url": request.callback_url.replace("/callback/", "/cancel/"),
        }

        params = {"api_key": self.api_key}

        try:
            resp = requests.post(url, json=data, params=params, timeout=30)
            resp.raise_for_status()
            result = resp.json()

            if result.get("status") == "success":
                txn_id = result["data"]["txn_id"]
                payment_url = result["data"]["invoice_url"]
                return PaymentResponse(
                    success=True,
                    payment_url=payment_url,
                    authority=txn_id,
                    reference_id=txn_id,
                    raw_response=result
                )
            else:
                return PaymentResponse(success=False, error=result.get("message", "Unknown error"), raw_response=result)

        except Exception as e:
            logger.exception("Plisio create_payment failed: %s", e)
            return PaymentResponse(success=False, error=str(e))

    def verify_payment(self, authority: str, amount_minor: int) -> VerificationResult:
        if not self.is_configured():
            return VerificationResult(success=False, verified=False, error="Plisio not configured")

        url = f"{self.base_url}/operations/invoice/info"
        params = {"api_key": self.api_key, "txn_id": authority}

        try:
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            result = resp.json()

            if result.get("status") == "success":
                data = result["data"]
                status = data.get("status", "")
                if status in ("completed", "confirmed"):
                    return VerificationResult(
                        success=True,
                        verified=True,
                        amount_minor=amount_minor,
                        reference_id=authority,
                        raw_response=result
                    )
                else:
                    return VerificationResult(success=True, verified=False, error=f"Payment status: {status}", raw_response=result)
            else:
                return VerificationResult(success=True, verified=False, error=result.get("message", "Verification failed"), raw_response=result)

        except Exception as e:
            logger.exception("Plisio verify_payment failed: %s", e)
            return VerificationResult(success=False, verified=False, error=str(e))


# =============================================================================
# NowPayments Gateway (Crypto)
# =============================================================================

class NowPaymentsGateway(PaymentGateway):
    """NOWPayments cryptocurrency payment gateway."""
    name = "nowpayments"

    def __init__(self, config: dict):
        super().__init__(config)
        self.api_key = config.get("api_key", "").strip()
        self.ipn_secret = config.get("ipn_secret", "").strip()
        self.base_url = "https://api.nowpayments.io/v1"

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> dict:
        return {
            "x-api-key": self.api_key,
            "Content-Type": "application/json",
        }

    def create_payment(self, request: PaymentRequest) -> PaymentResponse:
        if not self.is_configured():
            return PaymentResponse(success=False, error="NOWPayments not configured")

        # Convert IRT to USD for crypto payments
        amount_usd = request.amount_minor / 10 / 42000  # Approximate USD conversion

        url = f"{self.base_url}/payment"
        data = {
            "price_amount": round(amount_usd, 2),
            "price_currency": "usd",
            "pay_currency": request.currency if request.currency in ("usdt", "btc", "eth", "trx", "ton") else "usdt",
            "order_id": str(request.order_id),
            "order_description": request.description,
            "ipn_callback_url": request.callback_url,
            "success_url": request.callback_url.replace("/callback/", "/success/"),
            "cancel_url": request.callback_url.replace("/callback/", "/cancel/"),
        }

        try:
            resp = requests.post(url, json=data, headers=self._headers(), timeout=30)
            resp.raise_for_status()
            result = resp.json()

            if result.get("payment_status") in ("waiting", "confirming"):
                payment_id = result["payment_id"]
                payment_url = result["invoice_url"]
                return PaymentResponse(
                    success=True,
                    payment_url=payment_url,
                    authority=payment_id,
                    reference_id=payment_id,
                    raw_response=result
                )
            else:
                return PaymentResponse(success=False, error="Failed to create payment", raw_response=result)

        except Exception as e:
            logger.exception("NOWPayments create_payment failed: %s", e)
            return PaymentResponse(success=False, error=str(e))

    def verify_payment(self, authority: str, amount_minor: int) -> VerificationResult:
        if not self.is_configured():
            return VerificationResult(success=False, verified=False, error="NOWPayments not configured")

        url = f"{self.base_url}/payment/{authority}"

        try:
            resp = requests.get(url, headers=self._headers(), timeout=30)
            resp.raise_for_status()
            result = resp.json()

            status = result.get("payment_status", "")
            if status in ("finished", "confirmed"):
                return VerificationResult(
                    success=True,
                    verified=True,
                    amount_minor=amount_minor,
                    reference_id=authority,
                    raw_response=result
                )
            else:
                return VerificationResult(success=True, verified=False, error=f"Payment status: {status}", raw_response=result)

        except Exception as e:
            logger.exception("NOWPayments verify_payment failed: %s", e)
            return VerificationResult(success=False, verified=False, error=str(e))

    def verify_ipn(self, payload: dict, signature: str) -> bool:
        """Verify IPN callback signature."""
        if not self.ipn_secret:
            return False
        expected = hmac.new(
            self.ipn_secret.encode(),
            json.dumps(payload, separators=(',', ':')).encode(),
            hashlib.sha512
        ).hexdigest()
        return hmac.compare_digest(expected, signature)


# =============================================================================
# Telegram Stars Gateway
# =============================================================================

class TelegramStarsGateway(PaymentGateway):
    """Telegram Stars payment gateway (Telegram Bot API)."""
    name = "telegram_stars"

    def __init__(self, config: dict):
        super().__init__(config)
        self.bot_token = config.get("bot_token", "").strip()
        self.base_url = "https://api.telegram.org/bot"

    def is_configured(self) -> bool:
        return bool(self.bot_token)

    def create_payment(self, request: PaymentRequest) -> PaymentResponse:
        if not self.is_configured():
            return PaymentResponse(success=False, error="Telegram Stars not configured")

        # Telegram Stars uses invoice creation via Bot API
        # This creates an invoice that can be sent via sendInvoice
        url = f"{self.base_url}{self.bot_token}/createInvoiceLink"

        # Convert IRT to Stars (1 Star ≈ 0.013 USD, approximate)
        # This is a simplified conversion - in production, use actual rates
        stars_amount = max(1, int(request.amount_minor / 10 / 42000 / 0.013))

        data = {
            "title": "خرید سرویس VPN",
            "description": request.description[:255],
            "payload": json.dumps({"order_id": request.order_id, "amount_minor": request.amount_minor}),
            "currency": "XTR",  # Telegram Stars currency code
            "prices": [{"label": "سرویس", "amount": stars_amount}],
        }

        try:
            resp = requests.post(url, json=data, timeout=30)
            resp.raise_for_status()
            result = resp.json()

            if result.get("ok"):
                invoice_link = result["result"]
                return PaymentResponse(
                    success=True,
                    payment_url=invoice_link,
                    authority=invoice_link,  # Use link as authority
                    reference_id=str(request.order_id),
                    raw_response=result
                )
            else:
                return PaymentResponse(success=False, error=result.get("description", "Failed to create invoice"), raw_response=result)

        except Exception as e:
            logger.exception("Telegram Stars create_payment failed: %s", e)
            return PaymentResponse(success=False, error=str(e))

    def verify_payment(self, authority: str, amount_minor: int) -> VerificationResult:
        # For Telegram Stars, verification is done via pre_checkout_query and successful_payment
        # This is handled in the bot handler, not here
        return VerificationResult(
            success=True,
            verified=True,
            amount_minor=amount_minor,
            reference_id=authority,
            raw_response={"method": "handled_via_bot"}
        )


# =============================================================================
# Gateway Factory
# =============================================================================

_GATEWAY_CLASSES = {
    "zarinpal": ZarinpalGateway,
    "zarinpey": ZarinpeyGateway,
    "aqayepardakht": AqayePardakhtGateway,
    "plisio": PlisioGateway,
    "nowpayments": NowPaymentsGateway,
    "telegram_stars": TelegramStarsGateway,
}


def get_gateway(name: str, config: Optional[dict] = None) -> PaymentGateway:
    """Get payment gateway instance by name."""
    name = name.lower()
    if name not in _GATEWAY_CLASSES:
        raise ValueError(f"Unknown payment gateway: {name}")

    gateway_config = config or {}
    # Load from environment if not provided
    if not gateway_config:
        prefix = name.upper() + "_"
        for key, value in os.environ.items():
            if key.startswith(prefix):
                gateway_config[key[len(prefix):].lower()] = value

    return _GATEWAY_CLASSES[name](gateway_config)


def list_available_gateways() -> list[str]:
    """List all available payment gateways."""
    return list(_GATEWAY_CLASSES.keys())


def create_payment_request(
    gateway_name: str,
    amount_minor: int,
    currency: str,
    order_id: int,
    description: str,
    callback_url: str,
    **kwargs
) -> PaymentResponse:
    """Convenience function to create a payment."""
    gateway = get_gateway(gateway_name)
    request = PaymentRequest(
        amount_minor=amount_minor,
        currency=currency,
        order_id=order_id,
        description=description,
        callback_url=callback_url,
        **kwargs
    )
    return gateway.create_payment(request)


def verify_payment(
    gateway_name: str,
    authority: str,
    amount_minor: int
) -> VerificationResult:
    """Convenience function to verify a payment."""
    gateway = get_gateway(gateway_name)
    return gateway.verify_payment(authority, amount_minor)