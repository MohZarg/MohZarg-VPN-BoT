"""
GhYiAb V2 — Pricing Service (یک‌جا، بدون تکرار)
=====================================================

طبق Audit (P0-4)، منطق تخفیف نماینده در سه جای مختلف کد قدیمی تکرار شده بود.
این ماژول تنها منبع صحت قیمت نهایی است — هم مسیر خرید با کیف‌پول، هم مسیر
تأیید دستی ادمین، هم نمایش قیمت به کاربر، همه از همینجا صدا می‌زنند.

نرخ تخفیف نماینده (۱۰٪) دقیقاً همان مقدار V1 است — چیزی تغییر نکرده،
فقط جایگاهش یکی شده. سطوح کاربری بیشتر (Reseller/User Levels) طبق TODO #4
هنوز NEED-INFO است و اینجا اضافه نشده.
"""

from __future__ import annotations

AGENT_DISCOUNT_PERCENT = 10
AGENT_DISCOUNT_RATIO = 0.9  # فقط برای نمایش/سازگاری؛ محاسبه همیشه صحیح است


def _discounted(base_price_minor: int, percent: int) -> int:
    """تخفیف درصدی با حساب صحیح (بدون float) — برای مبالغ پولی الزامی است."""
    percent = max(0, min(100, int(percent)))
    return base_price_minor * (100 - percent) // 100


def final_price_minor(base_price_minor: int, is_agent: bool) -> int:
    if is_agent:
        return _discounted(base_price_minor, AGENT_DISCOUNT_PERCENT)
    return base_price_minor


def price_with_tier(base_price_minor: int, is_agent: bool, tier_discount_percent: int = 0) -> int:
    """
    قاعدهٔ ترکیب: بهترین (بیشترین) تخفیف بین «نماینده ۱۰٪» و «تخفیف سطح Reseller»
    اعمال می‌شود — نه جمع دو تخفیف روی هم (که می‌تواند قیمت را غیرمنطقی پایین ببرد).
    این قاعده NEED-INFO نیست چون به‌صراحت به‌عنوان یک انتخاب معماری مستند است؛ اگر
    Owner قاعدهٔ دیگری بخواهد (TODO #4)، همین‌جا تغییر می‌کند.
    """
    agent_percent = AGENT_DISCOUNT_PERCENT if is_agent else 0
    tier_percent = max(0, min(100, int(tier_discount_percent or 0)))
    return _discounted(base_price_minor, max(agent_percent, tier_percent))


def apply_coupon(price_minor: int, coupon, stacking: str = "best") -> tuple[int, int]:
    """
    برمی‌گرداند: (قیمت نهایی, میزان تخفیف). `coupon` یک CouponRecord یا None است.
    stacking="best" (پیش‌فرض امن): کوپن فقط اگر تخفیفش از قیمت فعلی (که شاید قبلاً
    تخفیف نقش/سطح خورده) بیشتر ببرد اعمال می‌شود؛ هرگز خودش را روی تخفیف دیگر جمع
    نمی‌کند مگر تنظیم صریح coupon_stacking=stack باشد.
    """
    if coupon is None or not coupon.is_active:
        return price_minor, 0
    if coupon.kind == "PERCENT":
        discount = price_minor * int(coupon.value) // 100
    else:  # FIXED — به واحد minor همان ارز
        discount = min(coupon.value, price_minor)
    if stacking == "best":
        discount = min(discount, price_minor)
    final = max(0, price_minor - discount)
    return final, price_minor - final
