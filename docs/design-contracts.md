# 生成代码的设计契约与结构验收

## 实现范围

CodeSpider 本身沿用控制面（backend）与执行面（agent_client）分离、code_intelligence 提供代码分析的既有结构。本次没有将系统强行改造成 Clean Architecture，也不要求所有生成工程都采用同一种目录。

生成链路现在包含：读取工程契约与源码 → 模型提出职责、接口和变更 → 对变更后的源码做静态预检 → 用户审批 → 再检查当前源码和契约 → 写入文件 → 构建/行为测试 → 再次结构审查。

| 设计思想 | 生成约束 | 可验证证据 |
| --- | --- | --- |
| 单一职责、职责分离 | 模块声明职责；HTTP、业务规则、数据访问分开 | 模块到层的映射、禁止越层导入；职责语义仍需评审 |
| 高内聚、低耦合 | 相关行为聚合；避免循环依赖、全局服务定位器 | 导入图、入度/出度、循环检测；不是语义内聚评分 |
| MVC | Spring Controller 处理协议，Service 编排，Repository 访问数据 | Controller→Service 等允许依赖；真实 MockMvc 集成测试 |
| Vue 分工 | Component 展示，Composable 管状态，Service 访问 API，纯函数处理规则 | 本地导入图、组件交互、实例隔离与竞态测试 |
| 依赖倒置、依赖注入 | 真实协作边界使用接口/Protocol，通过构造函数或参数注入 | 替换仓储/算法的独立行为测试；不以出现 interface 关键词判定成功 |
| 里氏替换、接口隔离 | 小而明确的能力接口；替换实现保持输入/输出/错误契约 | 通过同一业务服务测试不同实现与边界输入 |
| 开闭原则、策略模式 | 已有算法变化点采用 Strategy；新增策略无需改业务服务 | 注入第三种测试策略，保持服务实现不变 |
| Adapter、Repository | 用在真实外部接口/持久化边界，说明理由 | 职责声明、依赖方向和替身测试；不强制每层增加接口 |
| 函数契约 | 明确输入、输出、错误、副作用顺序，保持公开 API | Python AST 参数/返回注解/调用记录，独立边界与调用顺序测试 |
| KISS、避免过度设计 | 尊重既有工程；不生成空壳层、无需求工厂 | 空包标记不计职责模块；函数长度/参数数等给出建议 |

设计说明是简短可审查的工程产物，不要求或展示模型私有思维过程。

## 配置方式

没有配置文件时采用 `advisory`：生成仍会收到设计原则，报告显示问题但不会因结构建议中止既有工作流。

要强制执行，在工程根目录保存 `design-contract.json`。可从 `examples/design-contracts/` 的 Python、Spring MVC、Vue 模板开始，按真实工程路径修改：

```json
{
  "schema": "codespider.design/v1",
  "mode": "enforce",
  "require_design": true,
  "require_layer_assignment": true,
  "layers": [
    {"name": "web", "paths": ["src/main/java/example/web/*"], "may_depend_on": ["service"]},
    {"name": "service", "paths": ["src/main/java/example/service/*"], "may_depend_on": ["domain"]},
    {"name": "domain", "paths": ["src/main/java/example/domain/*"], "may_depend_on": []},
    {"name": "composition", "paths": ["src/main/java/example/Application.java"], "may_depend_on": ["web", "service", "domain"]}
  ],
  "forbidden_imports": {"domain": ["org.springframework", "java.sql"]},
  "exclude": ["src/test/*"],
  "limits": {"function_lines": 60, "parameters": 6, "class_methods": 15, "module_fan_out": 8}
}
```

- 路径使用相对路径和 Python `fnmatch` 模式；`*` 可跨目录。多个层匹配同一文件属于错误。
- 同层依赖允许；跨层依赖必须出现在 `may_depend_on`。本地依赖方向、循环、解析错误、未分层文件与不完整分析在 enforce 模式下阻止执行。
- `forbidden_imports` 按层禁止指定包及其子包导入，可限制框架或具体实现依赖。
- 指标阈值始终是建议，不把长函数自动认定为职责错误。函数长度/参数数/类方法数目前仅 Python AST 提供。
- `require_design` 检查模型生成变更的职责覆盖、声明的路径和接口符号是否存在。接口的输入/输出/错误支持文本、对象、数组；错误数组可以为空。手动指定补丁不强制编写模型设计说明，但仍执行源码结构检查。
- 模型生成任务不能创建或修改这个契约文件以绕过检查。调整契约应作为显式项目配置操作进行；生成后、审批前发生变化会要求重新生成。

## 标准工具与前端

结构检查使用已有工具 API，不新增私有执行接口：

```json
{
  "api_version": "1.0",
  "tool": "code",
  "action": "design_review",
  "workspace_id": "当前工程ID",
  "arguments": {},
  "approval": {"approved": true, "source": "user_confirmation"}
}
```

发送至 `POST /api/tools/call`，沿用登录鉴权、工程授权和安全模式审批。安全模式未经确认返回审批要求。

工程结构页面增加“结构审查”。生成审批卡和执行事件也有折叠的“设计与结构审查”：查看模块职责、接口说明、模式理由、类/函数/组件、Python 调用记录、本地模块依赖、发现的问题和分析限制。所有内容按文本转义。

`Task.design` 保存模型设计，`Task.design_contract` 保存生成时的规则快照，`Task.design_review` 保存实际源码报告；`design.reviewed` 事件区分写入前与测试后。新增字段均有默认值，兼容历史任务。

## 对旧文件的精确修改

代码上下文增加 `structure` 与 `file_hashes`。`structure` 提供既有函数/类、调用和依赖证据；模型上下文中的符号与调用各最多 120 条，截断会单独标记。模型可以输出：

```json
{"path":"src/service.py","operation":"apply_patch","base_sha256":"上下文提供的64位哈希","replacement":"完整新文件内容"}
```

网关核对哈希后从已读取的源码填入完整 `expected`。审批预览及 Agent 实际写入仍使用原文精确匹配，因此生成后文件被修改仍会被拒绝。不会 trim、忽略空白或把哈希失败降级为覆盖写入。该格式用于模型响应；原有 `workspace.apply_patch` 工具的执行契约保持 expected/replacement。

补丁格式与路径校验抽到独立 `backend/patch_contract.py`，模型网关与 Agent 共享规则，结构分析不依赖模型传输模块。

## 分析能力边界

Python 使用标准库 AST，提取函数/类、参数、返回注解、基类、函数所属关系、静态调用文本和导入边。支持相对导入及常见 src 布局。调用记录不等于运行时调用图，不解析动态分派或所有包重导出。

Java/JavaScript/Vue 使用去除注释后的词法证据：Java 导入、同包类型引用、类与方法声明；JS 相对导入和函数声明；Vue script 与组件名。它们尚不是完整 AST/类型解析，别名、反射、动态导入和复杂语法可能漏检，报告明确标注这一点。架构图只覆盖识别到的本地源码导入，不宣称“所有耦合已经检查”。

生成上下文最多 24 文件/96 KB，独立结构审查最多 120 文件/512 KB，单文件 64 KB，目录枚举上限 1000 项。遗漏生产源码会标记不完整；enforce 模式不能因此获得通过。依赖目录、构建产物和配置的测试文件不计入生产结构指标。

结构规则不能证明业务语义正确；必须结合构建、生成测试、独立验收和人工评审。测试后发现违规会将任务标为失败，但不会自动回滚已经写入的文件。
