"""
GhYiAb V2 — Payments Module
============================

ماژول پرداخت با پشتیبانی از درگاه‌های مختلف:
- زرین‌پال (Zarinpal)
- زرین‌پی (Zarinpey)
- آقای پرداخت (AqayePardakht)
- پلیسیو (Plisio) - کریپتو
- ناو پیمنتس (NowPayments) - کریپتو
- استارز تلگرام (Telegram Stars)
"""

from __future__ import annotations

from core.payments.gateways import (
    PaymentGateway,
    PaymentRequest,
    PaymentResponse,
    VerificationResult,
    ZarinpalGateway,
    ZarinpeyGateway,
    AqayePardakhtGateway,
    PlisioGateway,
    NowPaymentsGateway,
    TelegramStarsGateway,
    get_gateway,
    list_available_gateways,
    create_payment_request,
    verify_payment,
)

__all__ = [
    "PaymentGateway",
    "PaymentRequest",
    "PaymentResponse",
    "VerificationResult",
    "ZarinpalGateway",
    "ZarinpeyGateway",
    "AqayePardakhtGateway",
    "PlisioGateway",
    "NowPaymentsGateway",
    "TelegramStarsGateway",
    "get_gateway",
    "list_available_gateways",
    "create_payment_request",
    "verify_payment",
]