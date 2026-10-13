"""Keep public API and this module documentation."""
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

LABEL = "total_cents is the public API"


def total_cents(prices: list[str], discount: str = "0") -> int:
    # Keep this comment: currency contract v1.
    try:
        d_discount = Decimal(discount)
    except (InvalidOperation, ValueError):
        raise ValueError(f"Invalid discount: {discount}")
    if not d_discount.is_finite():
        raise ValueError("Discount must be finite")
    if d_discount < 0 or d_discount > 100:
        raise ValueError("Discount must be between 0 and 100")

    total = Decimal("0")
    for p in prices:
        try:
            d_price = Decimal(p)
        except (InvalidOperation, ValueError):
            raise ValueError(f"Invalid price: {p}")
        if not d_price.is_finite():
            raise ValueError("Price must be finite")
        if d_price < 0:
            raise ValueError("Price must not be negative")
        total += d_price

    result = total * (Decimal("1") - d_discount / Decimal("100"))
    cents = (result * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(cents)
