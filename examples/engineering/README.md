# 工程化生成示例

四个案例均使用 qwen3.8-max，通过 CodeSpider 的真实生成、审批、写文件和执行链路产生。实现与生成测试没有经过人工修改；独立验收由测试器编写。Spring 与 Vue 包含后续模型修复，不能把最终结果当成首轮通过率。

| 工程 | 生产结构 | 生成测试 | 独立验收 |
| --- | --- | --- | --- |
| python-checkout-design | 5 模块、6 类、10 函数/方法、4 条本地依赖 | 39 unittest | 4 项：策略替换、先校验后 IO、实例隔离、金额边界 |
| python-strategy-extension | 5 模块、7 类、12 函数/方法、4 条本地依赖 | 69 unittest | 4 项 + 5 个既有文件逐字不变：新增策略直接注入旧服务 |
| spring-mvc-design | 8 模块、8 类/接口、14 方法声明、10 条本地依赖 | 9 JUnit/MockMvc | 4 项：HTTP 契约、真实装配、协作者替换、校验顺序 |
| vue-catalog-design | 6 模块、2 组件、4 函数声明、4 条本地依赖 | 21 Vitest | 4 项：纯函数、实例隔离与重试、请求竞态、组件集成 |

结构指标只统计生产代码；Java/Vue 使用词法声明统计，不是完整类型分析。空 `__init__.py` 不计独立职责模块。每个目录中的 `design.json` 是合并后的初始/修复设计说明，`structure.json` 是源码实际检查结果，`design-contract.json` 是可版本管理的依赖规则。

Python（3.9+；新增策略案例使用相同命令，独立测试为 `tests.test_extension_acceptance`）：

```sh
cd examples/engineering/python-checkout-design
python3 -m unittest discover -s tests -v
python3 -m unittest tests.test_independent_acceptance -v
python3 main.py
```

Spring（JDK 17+、Maven）：

```sh
cd examples/engineering/spring-mvc-design
mvn test
mvn spring-boot:run
# GET http://localhost:8080/api/quote?sku=book&quantity=2
```

Vue（Node 20+、npm）：

```sh
cd examples/engineering/vue-catalog-design
npm ci --ignore-scripts --no-audit --no-fund
npm run build
npm test
npm exec -- vite --host 127.0.0.1
```

Java/Vue 的独立验收已经放在测试发现路径中，以上命令会一并执行。package-lock.json 是安装工具生成的锁文件，不是模型补丁。

重新生成与执行整套工程化需求：

```sh
# 私有 provider JSON 不得提交到版本库
python3 benchmarks/run_generation.py --suite engineering \
  --settings-file /path/to/private-provider.json --output /tmp/new-engineering-run --execute
```

可以加 `--case python-checkout-design` 等选择案例；`--replay /path/to/previous-run` 重放已保存的补丁或模型响应；`--repair-from /path/to/previous-run --feedback-file /path/to/reviewed-failure.txt` 复制原工程，进行真实的已有文件修复。所有输出目录必须是新目录。测试会运行模型生成代码，应使用专用可控执行环境。

规则与已知边界见 [设计契约文档](../../docs/design-contracts.md)，实测过程见 [工程化验证报告](../../docs/engineering-validation.md)。
