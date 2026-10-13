# 工程化代码生成案例（2026-10-13）

本轮用已配置的 Qwen 3.8 Max，在隔离目录中生成代码、批准执行、安装依赖、运行项目测试，并用预先写好的独立验收测试检查结果。生成测试不能替代独立验收，验收文件也不会发送给模型或被模型修改。

| 案例 | 工程重点 | 首轮 | 修复反馈后 |
| --- | --- | --- | --- |
| `python-checkout-design` | Protocol、策略模式、构造注入、校验先于 IO | 通过 | 通过 |
| `python-strategy-extension` | 在已有工程新增策略，保护旧服务/端口/仓储 | 通过 | 通过 |
| `spring-mvc-design` | Spring MVC、服务/领域/仓储分层、MockMvc 错误契约 | 失败 | 通过 |
| `vue-catalog-design` | Vue composable、请求竞态、错误重试、组件职责 | 失败 | 通过 |

首轮 4 组通过 2 组。Spring 失败是生成测试使用了不存在的 `org.springframework.boot.test.mock.bean.MockBean` 包，并在切片测试中重复声明 Bean；Vue 失败是错误状态使用 `null` 且缺少验收要求的 `data-testid="error"`。给模型明确的独立验收反馈后，Spring 修复使用正确的 `org.springframework.boot.test.mock.mockito.MockBean`，Vue 修复了精确状态和选择器；最终 4/4 通过。

本轮将生成提示增加了逐项需求复核：文件路径、公开符号、包名/import、HTTP 状态、JSON 字段、`data-testid`、错误值、脚本和测试命令都必须逐项核对；并加入 Spring Boot 3.x 的真实 MockBean 包路径和 Vue `null` 与空字符串的区别。提示优化的目标是减少框架 API 猜测和可观察契约遗漏，不放宽补丁、设计契约或独立验收。

验证证据保存在本机 `.codespider/evaluations/engineering-run-20261013-1900` 和两个 repair 目录中，汇总见 [`engineering-2026-10-13-round2.json`](../benchmarks/reports/engineering-2026-10-13-round2.json)。这些目录包含模型输出和依赖构建产物，已被 Git 忽略，不提交仓库。
