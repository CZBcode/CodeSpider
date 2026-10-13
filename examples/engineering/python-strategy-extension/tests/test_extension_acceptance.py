import unittest
from shop.service import CheckoutService
from shop.pricing import CappedPricing, RegularPricing, BulkPricing
class Repository:
 def unit_price(self,sku): return 1000
class ExtensionAcceptance(unittest.TestCase):
 def test_new_strategy_plugs_into_unchanged_service(self):
  self.assertEqual(CheckoutService(Repository(),CappedPricing(1500)).quote('book',2),1500)
  self.assertEqual(CheckoutService(Repository(),CappedPricing(2500)).quote('book',2),2000)
 def test_existing_strategies_keep_contract(self):
  self.assertEqual(CheckoutService(Repository(),RegularPricing()).quote('book',2),2000)
  self.assertEqual(CheckoutService(Repository(),BulkPricing()).quote('book',2),1800)
 def test_validation_and_no_bypass_for_zero_price(self):
  for cap in (0,-1,True,1.5):
   with self.assertRaises((ValueError,TypeError)): CappedPricing(cap)
  for qty in (0,-1,True,1.5):
   with self.assertRaises((ValueError,TypeError)): CappedPricing(100).total(0,qty)
 def test_instances_do_not_share_cap(self):
  a,b=CappedPricing(100),CappedPricing(200)
  self.assertEqual(a.total(1000,1),100);self.assertEqual(b.total(1000,1),200)
if __name__=='__main__':unittest.main()
