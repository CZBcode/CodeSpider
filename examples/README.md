# 实际生成工程示例

这里的四个工程由 `qwen3.8-max` 经 CodeSpider 任务链路生成：模型响应 → 契约校验 → 审批 → Agent 写文件 → 编译和测试。示例源码未经过人工修补；`acceptance_cart.py`、`AcceptanceTest.java`、`acceptance.test.js` 是测试器随后加入的独立验收测试，不是模型产物。

| 目录 | 场景 | 验证 |
| --- | --- | --- |
| generated/python-cart | 从零创建 Decimal 金额计算工程 | unittest + 独立金额/非法输入验收 |
| generated/python-repair | 修复已有浮点实现，保留 API、常量和指定注释 | unittest + 独立验收 + 原有内容保留检查 |
| generated/spring-greeting | Spring Boot 3.4.4 JSON 问候接口 | Maven/JUnit + 4 项独立 MockMvc 接口验收 |
| generated/vue-counter | Vue 3 非负计数器 | Vite 构建 + 5 项组件测试 + 独立交互验收 |

Python（Python 3.9+，无第三方依赖）：

```sh
cd examples/generated/python-cart
python3 -m unittest discover -v
python3 acceptance_cart.py
```

`python-repair` 使用相同命令。修复前源码保存在 `benchmarks/generation_cases.py` 的 `REPAIR_SOURCE`。

Spring Boot（JDK 17+、Maven）：

```sh
cd examples/generated/spring-greeting
mvn test
mvn spring-boot:run
# 另开终端：curl 'http://localhost:8080/api/greet?name=Ada'
```

Vue（Node 20+、npm）：

```sh
cd examples/generated/vue-counter
npm ci --ignore-scripts --no-audit --no-fund
npm run build
npm test
npm exec -- vite --host 127.0.0.1
```

测试当日：Python 3.9、OpenJDK 26（编译目标 17）、Maven 3.9.16、Node 22.14.0。Java 首次使用本机私有仓库超时；Vue 首次依赖安装超时。调整测试环境后，重放同一份模型补丁，最终四例均通过。未将首次失败改写为首次成功。详情见 `docs/generation-validation.md` 与 `benchmarks/reports/generation-2026-10-13.json`。
