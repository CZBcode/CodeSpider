"""Engineering tasks and independent behavior oracles, authored before generation."""
import json
from pathlib import Path


def policy(layers, exclude=None):
    result = {'schema':'codespider.design/v1','mode':'enforce','require_design':True,
              'require_layer_assignment':True,'layers':[
                  {'name':name,'paths':paths,'may_depend_on':deps} for name,paths,deps in layers]}
    if exclude is not None: result['exclude']=exclude
    return json.dumps(result,indent=2)

PYTHON_ORACLE = '''import unittest
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
'''
JAVA_ORACLE = '''package example;
import example.service.QuoteService;
import example.repository.ProductRepository;
import example.domain.BulkPricing;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.web.servlet.MockMvc;
import java.util.concurrent.atomic.AtomicInteger;
import static org.junit.jupiter.api.Assertions.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;
@SpringBootTest(classes=Application.class) @AutoConfigureMockMvc
class ArchitectureAcceptanceTest {
 @Autowired MockMvc mvc;
 @Test void httpContracts() throws Exception {
  mvc.perform(get("/api/quote").param("sku","book").param("quantity","2")).andExpect(status().isOk()).andExpect(jsonPath("$.totalCents").value(1800));
  mvc.perform(get("/api/quote").param("sku","missing").param("quantity","1")).andExpect(status().isNotFound());
  mvc.perform(get("/api/quote").param("sku","book").param("quantity","0")).andExpect(status().isBadRequest());
 }
 @Test void injectedCollaborators() {
  AtomicInteger reads=new AtomicInteger();
  ProductRepository repo=sku->{reads.incrementAndGet();return 1000;};
  assertEquals(1800,new QuoteService(repo,new BulkPricing()).quote("book",2));
  assertEquals(1,reads.get());
  assertEquals(7,new QuoteService(repo,(unit,qty)->7).quote("book",2));
 }
 @Test void validationBeforeIo() {
  AtomicInteger reads=new AtomicInteger();
  QuoteService service=new QuoteService(sku->{reads.incrementAndGet();return 1000;},new BulkPricing());
  assertThrows(IllegalArgumentException.class,()->service.quote("book",0));
  assertEquals(0,reads.get());
 }
 @Test void pricingBoundaries() {
  assertEquals(182,new BulkPricing().total(101,2));
  assertEquals(1000,new BulkPricing().total(1000,1));
  assertThrows(IllegalArgumentException.class,()->new BulkPricing().total(-1,2));
 }
}
'''
VUE_ORACLE = '''import {describe,it,expect,vi} from 'vitest';
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
'''
ROOT=Path(__file__).resolve().parent.parent
CASES=[{
'id':'python-checkout-design','description':'Python 3.9 standard library; business service with injected collaborators',
'seed':{'design-contract.json':policy([
 ('service',['shop/service.py'],['domain','ports']),('domain',['shop/pricing.py'],[]),
 ('ports',['shop/ports.py'],[]),('infrastructure',['shop/repository.py'],['ports']),
 ('composition',['shop/__init__.py','main.py'],['service','domain','ports','infrastructure'])])},
'goal':'''创建 Python 3.9 多模块报价工程，遵循 design-contract.json。shop/ports.py 定义 Inventory 和 Pricing Protocol。
shop/service.py CheckoutService(inventory, pricing)，quote(sku,quantity)->int；quantity 必须为正整数且拒绝 bool，先校验再访问仓储一次，未知 sku 透传 KeyError。
shop/pricing.py RegularPricing.total(unit_cents,quantity) 原价；BulkPricing 同接口，quantity>=2 打九折，整数分最终 HALF_UP；价格和数量类型严格校验，负价/非正数量抛 ValueError。
shop/repository.py MemoryInventory.unit_price(sku)，book 为1000分。main.py 是组合入口。
业务服务不能 import 具体仓储或策略、不能 isinstance 识别具体策略，构造注入并依赖 Protocol；定价函数不得 IO。支持新增策略而不改服务。
生成 unittest 测试覆盖协作者替换、边界和实例隔离。提供 design 模块职责、公开接口输入/输出/错误和模式适用理由。不要修改设计契约文件。''',
'oracle_path':'tests/test_independent_acceptance.py','oracle':PYTHON_ORACLE,'command':['python3','-m','unittest','tests.test_independent_acceptance']},
{
'id':'spring-mvc-design','description':'Java 17 Spring Boot 3.4.4 Maven; MVC and constructor injection',
'seed':{'pom.xml':(ROOT/'examples/generated/spring-greeting/pom.xml').read_text(),
'design-contract.json':policy([
 ('web',['src/main/java/example/web/*'],['service']),
 ('service',['src/main/java/example/service/*'],['domain','repository']),
 ('domain',['src/main/java/example/domain/*'],[]),
 ('repository',['src/main/java/example/repository/*'],[]),
 ('composition',['src/main/java/example/Application.java'],['web','service','domain','repository'])])},
'goal':'''补全现有 Maven Spring Boot 工程，Java release17，入口 example.Application。实现分层报价 API，遵守设计契约。
example.web.QuoteController GET /api/quote?sku=book&quantity=2 -> JSON {"totalCents":1800}。显式 @RequestParam(name=...)。
example.service.QuoteService(ProductRepository repository, PricingPolicy pricing)，public int quote(String sku,int quantity)，先检查 quantity>0，否则 IllegalArgumentException，再读取仓储并调用策略。
example.repository.ProductRepository 为单抽象方法接口 int unitPrice(String sku)，内存实现 book=1000，其余抛 NoSuchElementException。
example.domain.PricingPolicy 为单抽象方法接口 int total(int unitCents,int quantity)；BulkPricing 实现：两件以上九折，最终四舍五入到分，参数非法抛 IllegalArgumentException。
业务服务通过构造函数注入接口；domain 无 Spring 依赖。Application 用 @Bean 完成策略等必要装配。
控制器仅处理 HTTP 映射，错误统一由 web 包异常处理映射400/404，不得访问仓储，不得写定价规则。
必须含 JUnit 业务单测和 MockMvc HTTP 测试，测试错误码及策略可替换性。返回设计职责及接口契约说明，不修改设计契约。''',
'oracle_path':'src/test/java/example/ArchitectureAcceptanceTest.java','oracle':JAVA_ORACLE,
'command':['mvn','-q','-Dtest=ArchitectureAcceptanceTest','test']},
{
'id':'vue-catalog-design','description':'Vue 3 JavaScript Vite5 Vitest2 jsdom; components/composables/services/domain',
'seed':{'package.json':(ROOT/'examples/generated/vue-counter/package.json').read_text(),
'vite.config.js':(ROOT/'examples/generated/vue-counter/vite.config.js').read_text(),
'design-contract.json':policy([
 ('view',['src/App.vue','src/components/*'],['state']),
 ('state',['src/composables/*'],['domain','api']),
 ('domain',['src/domain/*'],[]),('api',['src/services/*'],[]),
 ('composition',['src/main.js'],['view','state','domain','api'])],
 ['*.spec.js','*.test.js','vite.config.js'])},
'goal':'''创建完整可运行 Vue3 目录浏览工程，使用已有 Vite/Vitest 配置和包版本。遵守设计契约，view 禁止直接依赖 services/domain。
src/domain/pricing.js 导出纯函数 totalCents(rows)，rows 每项 priceCents 非负整数、quantity 正整数，非法抛 Error，不修改输入；只使用整数分。
src/services/catalogApi.js 导出 async fetchProducts()，返回至少[{id:'book',priceCents:1000}]，本例可内存 Promise，无真实后端。
src/composables/useCatalog.js 导出 useCatalog(fetcher=fetchProducts)，返回 products/loading/error 三个 ref 和 async load()；错误转 error 字符串不向外抛；重试清除 error；实例隔离；并发 load 只接受最新调用结果及 loading/error 状态。
src/App.vue 调用 useCatalog() 和 load()，用 src/components/CatalogList.vue 展示产品。产品 data-testid=product-book，重试按钮 data-testid=retry 可触发 load。父组件处理状态编排，子组件通过 props/emits 通信，视图不直接调用 API。
index.html 和 src/main.js 完整入口。提供至少纯函数、composable、组件集成三类 Vitest 测试。输出设计职责、接口输入输出错误和选择模式的理由，不修改契约文件。''',
'oracle_path':'acceptance.test.js','oracle':VUE_ORACLE,'command':['npm','exec','--','vitest','run','acceptance.test.js']}
]

# An existing generated project is the fixture for an extension task. This tests
# class collaboration and API preservation, rather than another greenfield scaffold.
EXTENSION_ROOT = ROOT/'examples/engineering/python-checkout-design'
EXTENSION_SEED = {str(p.relative_to(EXTENSION_ROOT)):p.read_text() for p in EXTENSION_ROOT.rglob('*.py')
                  if p.name not in ('acceptance_design.py','test_independent_acceptance.py') and '__pycache__' not in p.parts}
EXTENSION_SEED['design-contract.json'] = (EXTENSION_ROOT/'design-contract.json').read_text() if EXTENSION_ROOT.exists() else CASES[0]['seed']['design-contract.json']
EXTENSION_ORACLE = '''import unittest
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
'''
CASES.append({
'id':'python-strategy-extension','description':'Existing Python multi-module checkout; extend one algorithm without touching service or repository',
'seed':EXTENSION_SEED,
'preserve_paths':['shop/service.py','shop/ports.py','shop/repository.py','main.py','tests/test_shop.py'],
'goal':'''在已有 Python 报价工程增加一种策略。只在 shop/pricing.py 新增 CappedPricing(cap_cents)，total(unit_cents,quantity) 返回正常整数总价与 cap 的较小值，不应用九折。
cap 必须为正整数且拒绝 bool，价格/数量沿用现有严格校验，零单价也不能绕过数量校验。实例不共享 cap。
现有 RegularPricing/BulkPricing 行为保持不变，复用已有校验函数；不修改 CheckoutService、ports、repository、main 或 tests/test_shop.py，也不要改变它们的空白或注释。
新增 tests/test_capped.py 覆盖新策略及通过既有服务注入使用。遵守设计契约，提供新增接口与职责说明。
使用 context.structure 理解已有函数与类关系，修改文件优先使用 context.file_hashes 对应的 base_sha256。''',
'oracle_path':'tests/test_extension_acceptance.py','oracle':EXTENSION_ORACLE,'command':['python3','-m','unittest','tests.test_extension_acceptance']})
