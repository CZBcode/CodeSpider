from decimal import Decimal, ROUND_HALF_UP, InvalidOperation


def total_cents(prices: list[str], discount: str = "0") -> int:
    """Sum decimal prices, apply percentage discount, round half-up to cents.

    Raises ValueError for negative numbers, NaN, Infinity, invalid numeric
    strings, or discount outside 0..100.
    """
    try:
        disc = Decimal(discount)
    except (InvalidOperation, ValueError):
        raise ValueError(f"Invalid discount: {discount!r}")

    if not disc.is_finite():
        raise ValueError("Discount must be finite")
    if disc < 0 or disc > 100:
        raise ValueError("Discount must be between 0 and 100 inclusive")

    total = Decimal("0")
    for p in prices:
        try:
            d = Decimal(p)
        except (InvalidOperation, ValueError):
            raise ValueError(f"Invalid price: {p!r}")
        if not d.is_finite():
            raise ValueError("Price must be finite")
        if d < 0:
            raise ValueError("Price must not be negative")
        total += d

    result = total * (Decimal("1") - disc / Decimal("100"))
    cents = result.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int(cents * 100)
