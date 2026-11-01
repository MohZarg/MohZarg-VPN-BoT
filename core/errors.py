"""
GhYiAb V2 — Domain Errors
===========================

خطاهای هستهٔ کسب‌وکار، مستقل از هر Adapter (تلگرام/HTTP/...). Adapterها این
خطاها را می‌گیرند و به پیام مناسب همان کانال ترجمه می‌کنند.
"""


class DomainError(Exception):
    """پایهٔ همهٔ خطاهای core."""


class InsufficientBalanceError(DomainError):
    pass


class OutOfStockError(DomainError):
    pass


class ProductNotFoundError(DomainError):
    pass


class AlreadyClaimedTestError(DomainError):
    pass


class DailyTestLimitError(DomainError):
    pass


class DiceCooldownError(DomainError):
    def __init__(self, remaining_seconds: int):
        super().__init__(f"کول‌داون گردونه هنوز {remaining_seconds} ثانیه باقی‌مانده")
        self.remaining_seconds = remaining_seconds


class RequestAlreadyResolvedError(DomainError):
    pass


class NotAuthorizedError(DomainError):
    pass


class ValidationError(DomainError):
    """ورودی نامعتبر (فرمت/بازه/طول)."""


class NotFoundError(DomainError):
    pass


class ConflictError(DomainError):
    """عملیات تکراری/ناسازگار با وضعیت فعلی (مثلاً بازپرداخت دوباره)."""


class ConfirmationInvalidError(DomainError):
    """توکن تأیید نامعتبر/منقضی/مصرف‌شده."""


class CouponError(DomainError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


class DuplicateReceiptError(DomainError):
    pass


class ProviderNotReadyError(DomainError):
    """Provider پیکربندی/آماده نیست (NOT_CONFIGURED/BLOCKED) — هیچ چیز شبیه‌سازی نمی‌شود."""


class ProvisioningFailedError(DomainError):
    pass


class ProvisioningPendingError(DomainError):
    """نتیجهٔ Provisioning نامعلوم است؛ سفارش برای بررسی دستی PROVISIONING می‌ماند."""


class DiceDisabledError(DomainError):
    pass


class DiceBudgetExceededError(DomainError):
    pass
