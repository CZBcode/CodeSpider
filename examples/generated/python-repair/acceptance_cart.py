import unittest
from cart import total_cents
class Acceptance(unittest.TestCase):
    def test_decimal(self):
        self.assertEqual(total_cents(['0.10','0.20']), 30)
        self.assertEqual(total_cents(['1.005']), 101)
        self.assertEqual(total_cents(['1.00'], '100'), 0)
        self.assertEqual(total_cents(['10.00'], '12.5'), 875)
    def test_invalid(self):
        for prices, discount in [(['-1'],'0'), (['1'],'-1'), (['1'],'101'), (['NaN'],'0'), (['Infinity'],'0'), (['1'],'NaN')]:
            with self.subTest(prices=prices,discount=discount):
                with self.assertRaises(ValueError): total_cents(prices,discount)
if __name__ == '__main__': unittest.main()
