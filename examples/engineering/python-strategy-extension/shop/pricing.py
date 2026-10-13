from decimal import Decimal, ROUND_HALF_UP


def _validate_inputs(unit_cents: int, quantity: int) -> None:
    """Validate pricing inputs strictly.

    Args:
        unit_cents: Must be an int (not bool) and >= 0.
        quantity: Must be an int (not bool) and > 0.

    Raises:
        TypeError: If types are wrong or if bool is passed.
        ValueError: If values are out of allowed range.
    """
    if isinstance(unit_cents, bool) or not isinstance(unit_cents, int):
        raise TypeError("unit_cents must be an int")
    if isinstance(quantity, bool) or not isinstance(quantity, int):
        raise TypeError("quantity must be an int")
    if unit_cents < 0:
        raise ValueError("unit_cents must be non-negative")
    if quantity <= 0:
        raise ValueError("quantity must be a positive integer")


class RegularPricing:
    """Standard pricing strategy: total = unit_cents * quantity."""

    def total(self, unit_cents: int, quantity: int) -> int:
        """Calculate regular total price.

        Args:
            unit_cents: Non-negative integer price per unit in cents.
            quantity: Positive integer number of units.

        Returns:
            Total price in cents as an integer.

        Raises:
            TypeError: If inputs are not int or are bool.
            ValueError: If unit_cents < 0 or quantity <= 0.
        """
        _validate_inputs(unit_cents, quantity)
        return unit_cents * quantity


class BulkPricing:
    """Bulk pricing strategy: 10% discount when quantity >= 2, rounded HALF_UP."""

    def total(self, unit_cents: int, quantity: int) -> int:
        """Calculate bulk-discounted total price.

        Args:
            unit_cents: Non-negative integer price per unit in cents.
            quantity: Positive integer number of units.

        Returns:
            Total price in cents as an integer, with 10% discount applied
            and rounded using HALF_UP when quantity >= 2.

        Raises:
            TypeError: If inputs are not int or are bool.
            ValueError: If unit_cents < 0 or quantity <= 0.
        """
        _validate_inputs(unit_cents, quantity)
        raw = unit_cents * quantity
        if quantity >= 2:
            discounted = Decimal(raw) * Decimal("0.9")
            return int(discounted.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        return raw


class CappedPricing:
    """Capped pricing strategy: total = min(unit_cents * quantity, cap_cents).

    No discount is applied. The cap limits the maximum chargeable amount.
    """

    def __init__(self, cap_cents: int) -> None:
        """Initialize with a positive integer cap.

        Args:
            cap_cents: Maximum total price in cents. Must be a positive int,
                not a bool.

        Raises:
            TypeError: If cap_cents is not an int or is a bool.
            ValueError: If cap_cents is not positive.
        """
        if isinstance(cap_cents, bool) or not isinstance(cap_cents, int):
            raise TypeError("cap_cents must be an int")
        if cap_cents <= 0:
            raise ValueError("cap_cents must be a positive integer")
        self._cap_cents = cap_cents

    def total(self, unit_cents: int, quantity: int) -> int:
        """Calculate capped total price.

        Args:
            unit_cents: Non-negative integer price per unit in cents.
            quantity: Positive integer number of units.

        Returns:
            The lesser of unit_cents * quantity and the configured cap,
            as an integer in cents.

        Raises:
            TypeError: If inputs are not int or are bool.
            ValueError: If unit_cents < 0 or quantity <= 0.
        """
        _validate_inputs(unit_cents, quantity)
        raw = unit_cents * quantity
        return min(raw, self._cap_cents)
