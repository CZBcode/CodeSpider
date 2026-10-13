import {describe,it,expect,vi} from 'vitest';
import {mount,flushPromises} from '@vue/test-utils';
import {useCatalog} from './src/composables/useCatalog.js';
import {totalCents} from './src/domain/pricing.js';
vi.mock('./src/services/catalogApi.js',()=>({fetchProducts:vi.fn().mockResolvedValue([{id:'book',priceCents:1000}])}));
import App from './src/App.vue';
import {fetchProducts} from './src/services/catalogApi.js';
describe('independent engineering acceptance',()=>{
 it('validates pure functions without mutating inputs',()=>{
  const rows=Object.freeze([Object.freeze({priceCents:101,quantity:2})]);
  expect(totalCents(rows)).toBe(202); expect(totalCents([])).toBe(0);
  for(const row of [{priceCents:-1,quantity:1},{priceCents:1,quantity:0},{priceCents:1.1,quantity:1}]) expect(()=>totalCents([row])).toThrow();
 });
 it('isolates instances and supports error then retry',async()=>{
  const api=vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce([{id:'book',priceCents:1000}]);
  const a=useCatalog(api), b=useCatalog(async()=>[]);
  await a.load(); expect(a.error.value).toBeTruthy(); expect(a.loading.value).toBe(false);
  await a.load(); expect(a.error.value).toBe(''); expect(a.products.value).toHaveLength(1);
  expect(b.products.value).toEqual([]);expect(api).toHaveBeenCalledTimes(2);
 });
 it('ignores stale request completion',async()=>{
  let first;const api=vi.fn().mockImplementationOnce(()=>new Promise(r=>first=r)).mockResolvedValueOnce([{id:'new',priceCents:100}]);
  const c=useCatalog(api);const pending=c.load();await c.load();first([{id:'old',priceCents:1}]);await pending;
  expect(c.products.value[0].id).toBe('new');expect(c.loading.value).toBe(false);
 });
 it('wires view and composable',async()=>{
  fetchProducts.mockRejectedValueOnce(new Error('offline'));
  const w=mount(App);await flushPromises();expect(w.get('[data-testid=error]').text()).toContain('offline');
  await w.get('[data-testid=retry]').trigger('click');await flushPromises();
  expect(w.get('[data-testid=product-book]').text()).toContain('book');expect(fetchProducts).toHaveBeenCalledTimes(2);w.unmount();
 });
});
