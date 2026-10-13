"""Executable acceptance contracts. Oracles are independent of generated tests."""
CART_ORACLE = '''import unittest
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
'''
REPAIR_SOURCE = '''"""Keep public API and this module documentation."""
from decimal import Decimal
LABEL = "total_cents is the public API"
def total_cents(prices, discount="0"):
    # Keep this comment: currency contract v1.
    return int(sum(float(p) for p in prices) * (1 - float(discount)/100) * 100)
'''
JAVA_ORACLE = '''package example;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.web.servlet.MockMvc;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;
@SpringBootTest(classes=Application.class)
@AutoConfigureMockMvc
class AcceptanceTest {
 @Autowired MockMvc mvc;
 @Test void defaultName() throws Exception { mvc.perform(get("/api/greet")).andExpect(status().isOk()).andExpect(jsonPath("$.message").value("Hello, world!")); }
 @Test void trimName() throws Exception { mvc.perform(get("/api/greet").param("name","  Ada  ")).andExpect(status().isOk()).andExpect(jsonPath("$.message").value("Hello, Ada!")); }
 @Test void blankName() throws Exception { mvc.perform(get("/api/greet").param("name","   ")).andExpect(status().isOk()).andExpect(jsonPath("$.message").value("Hello, world!")); }
 @Test void inputIsData() throws Exception { mvc.perform(get("/api/greet").param("name","<script>alert(1)</script>")).andExpect(status().isOk()).andExpect(content().contentTypeCompatibleWith("application/json")).andExpect(jsonPath("$.message").value("Hello, <script>alert(1)</script>!")); }
}
'''
VUE_ORACLE = '''import {describe,it,expect} from 'vitest';
import {mount} from '@vue/test-utils';
import App from './src/App.vue';
describe('independent acceptance', () => {
 it('increments, decrements, resets, and never goes negative', async () => {
  const w=mount(App); const value=()=>w.get('[data-testid="count"]').text();
  expect(value()).toBe('0');
  await w.get('[data-testid="decrement"]').trigger('click'); expect(value()).toBe('0');
  await w.get('[data-testid="increment"]').trigger('click');
  await w.get('[data-testid="increment"]').trigger('click'); expect(value()).toBe('2');
  await w.get('[data-testid="decrement"]').trigger('click'); expect(value()).toBe('1');
  await w.get('[data-testid="reset"]').trigger('click'); expect(value()).toBe('0'); w.unmount();
 });
});
'''
CART_GOAL = ('使用 Python 3.9 标准库实现 cart.py 的 total_cents(prices: list[str], discount: str="0") -> int。'
             '十进制单价求和、应用百分比折扣后，最终按 ROUND_HALF_UP 到分。拒绝负数、NaN、Infinity、非法数字和0..100以外折扣，统一抛 ValueError。'
             '生成 test_cart.py 的 unittest 回归测试。0.10+0.20=30分，1.005=101分，10元折扣12.5%=875分。')
CASES = [
 {"id":"python-cart", "description":"Python 3.9, decimal, unittest", "goal":"创建完整可运行工程。"+CART_GOAL,
  "oracle_path":"acceptance_cart.py", "oracle":CART_ORACLE, "command":["python3","acceptance_cart.py"]},
 {"id":"python-repair", "description":"已有 Python 3.9 工程，保持 public API", "goal":"修复现有 cart.py 的浮点精度错误。必须保留模块文档、LABEL 常量及 currency contract v1 注释。"+CART_GOAL,
  "seed":{"cart.py":REPAIR_SOURCE}, "oracle_path":"acceptance_cart.py", "oracle":CART_ORACLE, "command":["python3","acceptance_cart.py"]},
 {"id":"spring-greeting", "description":"Java 17, Maven, Spring Boot 3.4.4, JUnit 5", "goal":
  '生成最小可运行的 Spring Boot 3.4.4 Maven 工程，Java release 17，包 example，入口类 example.Application。'
  '提供 GET /api/greet?name=Ada，返回 JSON {"message":"Hello, Ada!"}。name 两边空格要trim，未传或全空白默认 world。'
  '输入含HTML字符也作为普通 JSON 字符串数据。用显式 @RequestParam(name="name",defaultValue="world")。'
  '必须含 pom.xml、入口和控制器以及 JUnit5 MockMvc 单测，可执行 mvn test。不使用数据库、Lombok。',
  "oracle_path":"src/test/java/example/AcceptanceTest.java", "oracle":JAVA_ORACLE, "command":["mvn","-q","-Dtest=AcceptanceTest","test"]},
 {"id":"vue-counter", "description":"Vue 3 + Vite 5 + Vitest 2 + jsdom, JavaScript", "goal":
  '生成完整可运行的 Vue 3 工程，使用 JavaScript/Vite5，不要TypeScript。入口 index.html、src/main.js、src/App.vue。'
  'App.vue 实现非负计数器，初始0，增加、减少、重置按钮，不能减到负数。'
  '计数值元素 data-testid=count，按钮分别 data-testid=increment/decrement/reset。'
  '依赖vue3、vite5、@vitejs/plugin-vue5、vitest2、@vue/test-utils2、jsdom25，使用兼容的确切版本号。'
  '提供vite.config.js，设置vitest environment为jsdom；package.json脚本build为vite build，test为vitest run。'
  '包含 Vitest 组件交互测试，可执行 npm run build 和 npm test。',
  "oracle_path":"acceptance.test.js", "oracle":VUE_ORACLE,
  "command":["npm","exec","--","vitest","run","acceptance.test.js"]},
]
