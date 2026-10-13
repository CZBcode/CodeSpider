import unittest
from cart import total_cents


class TestTotalCents(unittest.TestCase):
    def test_basic_sum(self):
        self.assertEqual(total_cents(["0.10", "0.20"]), 30)

    def test_round_half_up(self):
        self.assertEqual(total_cents(["1.005"]), 101)

    def test_discount(self):
        self.assertEqual(total_cents(["10"], "12.5"), 875)

    def test_zero_discount(self):
        self.assertEqual(total_cents(["5.555"], "0"), 556)

    def test_full_discount(self):
        self.assertEqual(total_cents(["10.00"], "100"), 0)

    def test_empty_prices(self):
        self.assertEqual(total_cents([]), 0)

    def test_negative_price_raises(self):
        with self.assertRaises(ValueError):
            total_cents(["-1.00"])

    def test_nan_price_raises(self):
        with self.assertRaises(ValueError):
            total_cents(["NaN"])

    def test_infinity_price_raises(self):
        with self.assertRaises(ValueError):
            total_cents(["Infinity"])

    def test_invalid_price_string_raises(self):
        with self.assertRaises(ValueError):
            total_cents(["abc"])

    def test_negative_discount_raises(self):
        with self.assertRaises(ValueError):
            total_cents(["1.00"], "-5")

    def test_discount_over_100_raises(self):
        with self.assertRaises(ValueError):
            total_cents(["1.00"], "101")

    def test_nan_discount_raises(self):
        with self.assertRaises(ValueError):
            total_cents(["1.00"], "NaN")

    def test_infinity_discount_raises(self):
        with self.assertRaises(ValueError):
            total_cents(["1.00"], "Infinity")

    def test_invalid_discount_string_raises(self):
        with self.assertRaises(ValueError):
            total_cents(["1.00"], "xyz")


if __name__ == "__main__":
    unittest.main()
