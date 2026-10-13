import unittest
from unittest.mock import MagicMock

from shop.ports import Inventory, Pricing
from shop.service import CheckoutService
from shop.pricing import RegularPricing, BulkPricing
from shop.repository import MemoryInventory


class TestCheckoutServiceValidation(unittest.TestCase):
    """Test input validation in CheckoutService.quote before inventory access."""

    def setUp(self) -> None:
        self.inventory = MagicMock(spec=Inventory)
        self.pricing = MagicMock(spec=Pricing)
        self.service = CheckoutService(self.inventory, self.pricing)

    def test_rejects_bool_quantity(self) -> None:
        with self.assertRaises(TypeError):
            self.service.quote("book", True)  # type: ignore[arg-type]
        self.inventory.unit_price.assert_not_called()

    def test_rejects_zero_quantity(self) -> None:
        with self.assertRaises(ValueError):
            self.service.quote("book", 0)
        self.inventory.unit_price.assert_not_called()

    def test_rejects_negative_quantity(self) -> None:
        with self.assertRaises(ValueError):
            self.service.quote("book", -1)
        self.inventory.unit_price.assert_not_called()

    def test_rejects_float_quantity(self) -> None:
        with self.assertRaises(TypeError):
            self.service.quote("book", 2.5)  # type: ignore[arg-type]
        self.inventory.unit_price.assert_not_called()

    def test_rejects_string_quantity(self) -> None:
        with self.assertRaises(TypeError):
            self.service.quote("book", "two")  # type: ignore[arg-type]
        self.inventory.unit_price.assert_not_called()


class TestCheckoutServiceCollaboration(unittest.TestCase):
    """Test that CheckoutService correctly delegates to collaborators."""

    def setUp(self) -> None:
        self.inventory = MagicMock(spec=Inventory)
        self.pricing = MagicMock(spec=Pricing)
        self.service = CheckoutService(self.inventory, self.pricing)

    def test_accesses_inventory_exactly_once(self) -> None:
        self.inventory.unit_price.return_value = 1000
        self.pricing.total.return_value = 3000
        self.service.quote("book", 3)
        self.inventory.unit_price.assert_called_once_with("book")

    def test_passes_unit_price_and_quantity_to_pricing(self) -> None:
        self.inventory.unit_price.return_value = 500
        self.pricing.total.return_value = 1500
        self.service.quote("item", 3)
        self.pricing.total.assert_called_once_with(500, 3)

    def test_returns_pricing_result(self) -> None:
        self.inventory.unit_price.return_value = 100
        self.pricing.total.return_value = 200
        result = self.service.quote("x", 2)
        self.assertEqual(result, 200)

    def test_propagates_key_error_for_unknown_sku(self) -> None:
        self.inventory.unit_price.side_effect = KeyError("unknown")
        with self.assertRaises(KeyError):
            self.service.quote("unknown", 1)


class TestCheckoutServiceInstanceIsolation(unittest.TestCase):
    """Verify that separate service instances do not share state."""

    def test_instances_are_isolated(self) -> None:
        inv1 = MagicMock(spec=Inventory)
        inv1.unit_price.return_value = 100
        prc1 = MagicMock(spec=Pricing)
        prc1.total.return_value = 100

        inv2 = MagicMock(spec=Inventory)
        inv2.unit_price.return_value = 999
        prc2 = MagicMock(spec=Pricing)
        prc2.total.return_value = 999

        svc1 = CheckoutService(inv1, prc1)
        svc2 = CheckoutService(inv2, prc2)

        self.assertEqual(svc1.quote("a", 1), 100)
        self.assertEqual(svc2.quote("b", 1), 999)
        inv1.unit_price.assert_called_once_with("a")
        inv2.unit_price.assert_called_once_with("b")


class TestRegularPricing(unittest.TestCase):
    """Test RegularPricing domain logic."""

    def setUp(self) -> None:
        self.pricing = RegularPricing()

    def test_basic_calculation(self) -> None:
        self.assertEqual(self.pricing.total(1000, 3), 3000)

    def test_single_unit(self) -> None:
        self.assertEqual(self.pricing.total(500, 1), 500)

    def test_zero_unit_price(self) -> None:
        self.assertEqual(self.pricing.total(0, 5), 0)

    def test_rejects_negative_unit_price(self) -> None:
        with self.assertRaises(ValueError):
            self.pricing.total(-1, 1)

    def test_rejects_zero_quantity(self) -> None:
        with self.assertRaises(ValueError):
            self.pricing.total(100, 0)

    def test_rejects_bool_unit_price(self) -> None:
        with self.assertRaises(TypeError):
            self.pricing.total(True, 1)  # type: ignore[arg-type]

    def test_rejects_bool_quantity(self) -> None:
        with self.assertRaises(TypeError):
            self.pricing.total(100, False)  # type: ignore[arg-type]

    def test_rejects_float_unit_price(self) -> None:
        with self.assertRaises(TypeError):
            self.pricing.total(10.5, 1)  # type: ignore[arg-type]

    def test_rejects_string_quantity(self) -> None:
        with self.assertRaises(TypeError):
            self.pricing.total(100, "2")  # type: ignore[arg-type]


class TestBulkPricing(unittest.TestCase):
    """Test BulkPricing domain logic including discount and rounding."""

    def setUp(self) -> None:
        self.pricing = BulkPricing()

    def test_no_discount_for_single_unit(self) -> None:
        self.assertEqual(self.pricing.total(1000, 1), 1000)

    def test_discount_applied_at_quantity_two(self) -> None:
        # 1000 * 2 = 2000, 2000 * 0.9 = 1800
        self.assertEqual(self.pricing.total(1000, 2), 1800)

    def test_discount_applied_for_larger_quantity(self) -> None:
        # 1000 * 3 = 3000, 3000 * 0.9 = 2700
        self.assertEqual(self.pricing.total(1000, 3), 2700)

    def test_half_up_rounding(self) -> None:
        # 15 * 3 = 45, 45 * 0.9 = 40.5 -> rounds to 41 with HALF_UP
        self.assertEqual(self.pricing.total(15, 3), 41)

    def test_half_up_rounding_down(self) -> None:
        # 11 * 3 = 33, 33 * 0.9 = 29.7 -> rounds to 30
        self.assertEqual(self.pricing.total(11, 3), 30)

    def test_exact_integer_after_discount(self) -> None:
        # 10 * 2 = 20, 20 * 0.9 = 18.0 -> 18
        self.assertEqual(self.pricing.total(10, 2), 18)

    def test_rejects_negative_unit_price(self) -> None:
        with self.assertRaises(ValueError):
            self.pricing.total(-100, 2)

    def test_rejects_negative_quantity(self) -> None:
        with self.assertRaises(ValueError):
            self.pricing.total(100, -1)

    def test_rejects_bool_quantity(self) -> None:
        with self.assertRaises(TypeError):
            self.pricing.total(100, True)  # type: ignore[arg-type]

    def test_boundary_quantity_one_no_discount(self) -> None:
        self.assertEqual(self.pricing.total(100, 1), 100)

    def test_boundary_quantity_two_with_discount(self) -> None:
        self.assertEqual(self.pricing.total(100, 2), 180)


class TestMemoryInventory(unittest.TestCase):
    """Test the infrastructure adapter."""

    def setUp(self) -> None:
        self.repo = MemoryInventory()

    def test_book_price(self) -> None:
        self.assertEqual(self.repo.unit_price("book"), 1000)

    def test_unknown_sku_raises_key_error(self) -> None:
        with self.assertRaises(KeyError):
            self.repo.unit_price("nonexistent")


class TestProtocolConformance(unittest.TestCase):
    """Verify concrete classes satisfy Protocol definitions."""

    def test_memory_inventory_is_inventory(self) -> None:
        self.assertTrue(isinstance(MemoryInventory(), Inventory))

    def test_regular_pricing_is_pricing(self) -> None:
        self.assertTrue(isinstance(RegularPricing(), Pricing))

    def test_bulk_pricing_is_pricing(self) -> None:
        self.assertTrue(isinstance(BulkPricing(), Pricing))


class TestIntegrationWithRealCollaborators(unittest.TestCase):
    """End-to-end tests wiring real implementations together."""

    def test_regular_checkout_flow(self) -> None:
        service = CheckoutService(MemoryInventory(), RegularPricing())
        self.assertEqual(service.quote("book", 3), 3000)

    def test_bulk_checkout_flow(self) -> None:
        service = CheckoutService(MemoryInventory(), BulkPricing())
        # 1000 * 3 = 3000, * 0.9 = 2700
        self.assertEqual(service.quote("book", 3), 2700)

    def test_bulk_single_item_no_discount(self) -> None:
        service = CheckoutService(MemoryInventory(), BulkPricing())
        self.assertEqual(service.quote("book", 1), 1000)

    def test_unknown_sku_in_integration(self) -> None:
        service = CheckoutService(MemoryInventory(), RegularPricing())
        with self.assertRaises(KeyError):
            service.quote("pen", 1)


if __name__ == "__main__":
    unittest.main()
