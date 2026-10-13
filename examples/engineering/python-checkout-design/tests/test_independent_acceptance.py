import unittest
from shop.service import CheckoutService
from shop.pricing import RegularPricing, BulkPricing
class FakeInventory:
 def __init__(self): self.calls=[]
 def unit_price(self,sku):
  self.calls.append(sku)
  if sku!='book': raise KeyError(sku)
  return 1000
class CustomPricing:
 def total(self,unit_cents,quantity): return 7
class Acceptance(unittest.TestCase):
 def test_collaborators_are_injected(self):
  repo=FakeInventory()
  self.assertEqual(CheckoutService(repo,RegularPricing()).quote('book',2),2000)
  self.assertEqual(repo.calls,['book'])
  self.assertEqual(CheckoutService(repo,BulkPricing()).quote('book',2),1800)
  self.assertEqual(CheckoutService(repo,CustomPricing()).quote('book',2),7)
 def test_invalid_quantity_does_not_access_repository(self):
  repo=FakeInventory(); service=CheckoutService(repo,RegularPricing())
  for qty in (0,-1,1.5,True):
   with self.assertRaises((ValueError,TypeError)): service.quote('book',qty)
  self.assertEqual(repo.calls,[])
 def test_unknown_item_and_instances(self):
  a,b=FakeInventory(),FakeInventory()
  with self.assertRaises(KeyError): CheckoutService(a,RegularPricing()).quote('missing',1)
  self.assertEqual(b.calls,[])
 def test_strategies_round_once_and_validate(self):
  self.assertEqual(BulkPricing().total(101,2),182)
  self.assertEqual(BulkPricing().total(1000,1),1000)
  for cls in (RegularPricing,BulkPricing):
   for unit,qty in ((-1,1),(True,1),(1.1,2),(1,True),(1,0)):
    with self.assertRaises((ValueError,TypeError)): cls().total(unit,qty)
if __name__=='__main__': unittest.main()
