class MemoryInventory:
    """In-memory inventory adapter implementing the Inventory protocol."""

    def __init__(self) -> None:
        self._catalog: dict[str, int] = {
            "book": 1000,
        }

    def unit_price(self, sku: str) -> int:
        """Look up the unit price for a SKU.

        Args:
            sku: Product identifier string.

        Returns:
            Unit price in cents.

        Raises:
            KeyError: If the SKU does not exist in the catalog.
        """
        if sku not in self._catalog:
            raise KeyError(sku)
        return self._catalog[sku]
