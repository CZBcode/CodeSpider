from shop.repository import MemoryInventory
from shop.pricing import RegularPricing, BulkPricing
from shop.service import CheckoutService


def main() -> None:
    """Composition root: wire dependencies and demonstrate quoting."""
    inventory = MemoryInventory()

    regular_service = CheckoutService(inventory, RegularPricing())
    bulk_service = CheckoutService(inventory, BulkPricing())

    sku = "book"
    quantity = 3

    regular_quote = regular_service.quote(sku, quantity)
    bulk_quote = bulk_service.quote(sku, quantity)

    print(f"SKU: {sku}, Quantity: {quantity}")
    print(f"Regular price: {regular_quote} cents")
    print(f"Bulk price:    {bulk_quote} cents")


if __name__ == "__main__":
    main()
