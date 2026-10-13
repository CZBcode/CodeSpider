from typing import Protocol, runtime_checkable


@runtime_checkable
class Inventory(Protocol):
    """Port for retrieving unit prices by SKU."""

    def unit_price(self, sku: str) -> int:
        """Return the unit price in cents for the given SKU.

        Args:
            sku: Product identifier string.

        Returns:
            Unit price as a non-negative integer in cents.

        Raises:
            KeyError: If the SKU is not found in the inventory.
        """
        ...


@runtime_checkable
class Pricing(Protocol):
    """Port for calculating total price from unit price and quantity."""

    def total(self, unit_cents: int, quantity: int) -> int:
        """Calculate the total price in cents.

        Args:
            unit_cents: Price per unit in cents.
            quantity: Number of units (positive integer).

        Returns:
            Total price as an integer in cents.

        Raises:
            ValueError: If unit_cents is negative or quantity is not a positive integer.
            TypeError: If arguments are of incorrect types.
        """
        ...
