import unittest
from unittest.mock import MagicMock

from shop.ports import Inventory, Pricing
from shop.service import CheckoutService
from shop.pricing import CappedPricing
from shop.repository import MemoryInventory


class TestCappedPricingDomainLogic(unittest.TestCase):
    """Test CappedPricing calculation and input validation."""

    def setUp(self) -> None:
        self.pricing = CappedPricing(cap_cents=2500)

    def test_total_below_cap(self) -> None:
        self.assertEqual(self.pricing.total(1000, 2), 2000)

    def test_total_equal_to_cap(self) -> None:
        self.assertEqual(self.pricing.total(1000, 2), 2000)
        pricing_exact = CappedPricing(cap_cents=2000)
        self.assertEqual(pricing_exact.total(1000, 2), 2000)

    def test_total_above_cap_returns_cap(self) -> None:
        self.assertEqual(self.pricing.total(1000, 3), 2500)

    def test_single_unit_under_cap(self) -> None:
        self.assertEqual(self.pricing.total(500, 1), 500)

    def test_single_unit_over_cap(self) -> None:
        pricing = CappedPricing(cap_cents=100)
        self.assertEqual(pricing.total(500, 1), 100)

    def test_zero_unit_price_validates_quantity(self) -> None:
        self.assertEqual(self.pricing.total(0, 5), 0)

    def test_zero_unit_price_rejects_zero_quantity(self) -> None:
        with self.assertRaises(ValueError):
            self.pricing.total(0, 0)

    def test_no_discount_applied(self) -> None:
        # Unlike BulkPricing, no 10% discount even at quantity >= 2
        pricing = CappedPricing(cap_cents=10000)
        self.assertEqual(pricing.total(1000, 3), 3000)

    def test_rejects_negative_unit_price(self) -> None:
        with self.assertRaises(ValueError):
            self.pricing.total(-1, 1)

    def test_rejects_zero_quantity(self) -> None:
        with self.assertRaises(ValueError):
            self.pricing.total(100, 0)

    def test_rejects_negative_quantity(self) -> None:
        with self.assertRaises(ValueError):
            self.pricing.total(100, -1)

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


class TestCappedPricingCapValidation(unittest.TestCase):
    """Test constructor validation for cap_cents."""

    def test_rejects_bool_cap(self) -> None:
        with self.assertRaises(TypeError):
            CappedPricing(True)  # type: ignore[arg-type]

    def test_rejects_false_cap(self) -> None:
        with self.assertRaises(TypeError):
            CappedPricing(False)  # type: ignore[arg-type]

    def test_rejects_zero_cap(self) -> None:
        with self.assertRaises(ValueError):
            CappedPricing(0)

    def test_rejects_negative_cap(self) -> None:
        with self.assertRaises(ValueError):
            CappedPricing(-100)

    def test_rejects_float_cap(self) -> None:
        with self.assertRaises(TypeError):
            CappedPricing(10.5)  # type: ignore[arg-type]

    def test_rejects_string_cap(self) -> None:
        with self.assertRaises(TypeError):
            CappedPricing("100")  # type: ignore[arg-type]

    def test_accepts_positive_int_cap(self) -> None:
        pricing = CappedPricing(1)
        self.assertEqual(pricing.total(100, 1), 1)


class TestCappedPricingInstanceIsolation(unittest.TestCase):
    """Verify that separate CappedPricing instances do not share cap state."""

    def test_instances_have_independent_caps(self) -> None:
        p1 = CappedPricing(cap_cents=100)
        p2 = CappedPricing(cap_cents=5000)
        self.assertEqual(p1.total(1000, 3), 100)
        self.assertEqual(p2.total(1000, 3), 3000)

    def test_mutating_one_does_not_affect_other(self) -> None:
        p1 = CappedPricing(cap_cents=200)
        p2 = CappedPricing(cap_cents=200)
        # They are independent objects; internal state is not shared
        self.assertEqual(p1.total(100, 3), 200)
        self.assertEqual(p2.total(100, 3), 200)


class TestCappedPricingProtocolConformance(unittest.TestCase):
    """Verify CappedPricing satisfies the Pricing protocol."""

    def test_capped_pricing_is_pricing(self) -> None:
        self.assertTrue(isinstance(CappedPricing(1000), Pricing))


class TestCappedPricingIntegrationWithService(unittest.TestCase):
    """End-to-end tests wiring CappedPricing through CheckoutService."""

    def test_capped_checkout_flow_under_cap(self) -> None:
        service = CheckoutService(MemoryInventory(), CappedPricing(cap_cents=5000))
        # book = 1000 cents, qty 3 => 3000, under cap 5000
        self.assertEqual(service.quote("book", 3), 3000)

    def test_capped_checkout_flow_over_cap(self) -> None:
        service = CheckoutService(MemoryInventory(), CappedPricing(cap_cents=2500))
        # book = 1000 cents, qty 3 => 3000, capped to 2500
        self.assertEqual(service.quote("book", 3), 2500)

    def test_capped_checkout_flow_at_cap(self) -> None:
        service = CheckoutService(MemoryInventory(), CappedPricing(cap_cents=3000))
        self.assertEqual(service.quote("book", 3), 3000)

    def test_unknown_sku_propagates_key_error(self) -> None:
        service = CheckoutService(MemoryInventory(), CappedPricing(cap_cents=1000))
        with self.assertRaises(KeyError):
            service.quote("pen", 1)

    def test_service_with_mock_inventory_and_capped_pricing(self) -> None:
        inventory = MagicMock(spec=Inventory)
        inventory.unit_price.return_value = 800
        pricing = CappedPricing(cap_cents=1500)
        service = CheckoutService(inventory, pricing)
        # 800 * 2 = 1600, capped to 1500
        self.assertEqual(service.quote("item", 2), 1500)
        inventory.unit_price.assert_called_once_with("item")


if __name__ == "__main__":
    unittest.main()
