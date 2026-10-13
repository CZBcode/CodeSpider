from .ports import Inventory, Pricing


class CheckoutService:
    """Application service that coordinates inventory lookup and pricing.

    Depends only on Protocol abstractions; never imports concrete
    implementations or uses isinstance to detect specific strategies.
    """

    def __init__(self, inventory: Inventory, pricing: Pricing) -> None:
        """Initialize with injected collaborators.

        Args:
            inventory: An object satisfying the Inventory protocol.
            pricing: An object satisfying the Pricing protocol.
        """
        self._inventory = inventory
        self._pricing = pricing

    def quote(self, sku: str, quantity: int) -> int:
        """Produce a price quote for a SKU and quantity.

        Validates quantity first (must be a positive int, bool rejected),
        then accesses the inventory exactly once. Unknown SKUs propagate
        KeyError from the inventory port.

        Args:
            sku: Product identifier string.
            quantity: Desired number of units.

        Returns:
            Total price in cents as an integer.

        Raises:
            TypeError: If quantity is not an int or is a bool.
            ValueError: If quantity is not positive.
            KeyError: If the SKU is unknown to the inventory.
        """
        if isinstance(quantity, bool) or not isinstance(quantity, int):
            raise TypeError("quantity must be an int")
        if quantity <= 0:
            raise ValueError("quantity must be a positive integer")

        unit_cents = self._inventory.unit_price(sku)
        return self._pricing.total(unit_cents, quantity)
