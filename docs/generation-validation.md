# 代码生成实测与修复（2026-10-13）

## 测试方式与结果

使用已配置的 `qwen3.8-max`，通过 `TaskManager.create → approve → Agent ToolService` 实际写入独立工作区，运行构建和测试，再执行测试器预先编写的验收代码。没有按响应中的安全关键词计分，没有手动修改模型生成的示例实现，也没有把空补丁视为代码生成成功。

| 场景 | 首轮 | 最终重放 |
| --- | --- | --- |
| Python Decimal 购物车 | 通过 | 通过 |
| Python 已有文件精度修复 | 通过 | 通过 |
| Spring Boot JSON 接口 | Maven 依赖下载 180 秒超时 | 通过（独立 Maven Central 配置） |
| Vue 计数器 | npm 依赖安装 180 秒超时 | 通过（测试环境使用 npm mirror） |

首轮 2/4，环境调整后原始补丁重放 4/4。真实首次生成请求、生成任务、事件、命令输出、独立验收日志保存在工作区的 `.codespider/evaluations/`；该目录被 Git 忽略。可分享源码在 `examples/generated/`，不含账号配置、模型密钥、依赖目录或编译产物。仓库报告只包含目标、状态、耗时和文件摘要。

## 实测推动的系统修复

1. **生成时缺少原文**：新增标准工具 `code.context`，返回工程说明、文件全文和符号。安全模式下先确认读取并发送源码到所选模型，再调用模型。默认最多 24 个文件、96 KB 总量、64 KB 单文件，跳过隐藏文件、常见凭据文件名、依赖和编译目录。超出预算的文件列为 skipped，不截断后冒充完整原文。Python 使用 AST，Java/Vue 仍沿用已有轻量符号解析。
2. **截断恢复丢失代码**：生成任务重试保留代码输出预算和非空补丁要求，不能通过清空 patches 伪装恢复。未显式配置时生成预算 8192 tokens，显式配置仍被保留；最多三次请求，失败明确返回。仅计划请求保留原有最小响应恢复。
3. **补丁内容被静默截短**：超限或非字符串补丁直接拒绝。已有文件必须携带完整且匹配上下文的 expected；新文件统一 create，并在 Agent 层使用 O_EXCL 防止覆盖并发创建的文件。重复路径、路径穿越和 Windows 盘符路径被拒绝。
4. **计划被截为三个步骤**：保留模型完整计划；审批界面展示文件原文/新内容，输出经 HTML 转义。
5. **只编译不运行测试**：Python 在语法检查后运行已发现的 unittest；零测试明确失败。Java Maven 从跳过测试编译改为 `mvn test`。Vue 执行依赖校准、构建和项目 test 脚本。编译通过、断言失败会标记任务失败；仅 Python 语法检查时明确说明没有行为测试。
6. **依赖安装中断留下假就绪目录**：Vue 每次依据 manifest/lock 执行 install/ci，不再仅根据 node_modules 存在判定。安装禁用生命周期脚本，最多 300 秒；验证命令最多 180 秒。超时错误保留末尾输出以便诊断，失败不会静默成功。
7. **不可重复验证**：增加 `benchmarks/run_generation.py`，支持保存每例产物和报告，并通过 `--replay` 在新目录重放同一份模型补丁，无需重复付费请求模型。

## 复现

先准备受控的一次性执行环境以及 Python 3.9+、JDK 17+、Maven、Node 20+。此测试会运行模型生成代码；`--execute` 明确表示允许在测试工作区写文件、安装依赖、运行构建和测试。

```sh
export CODESPIDER_MODEL_BASE_URL=https://maas.qianwenaiapi.com/compatible-mode/v1
export CODESPIDER_MODEL=qwen3.8-max
# 通过环境注入 CODESPIDER_MODEL_API_KEY，不放入源码或报告
python3 benchmarks/run_generation.py --output /tmp/codespider-generation-new --execute
python3 benchmarks/run_generation.py --output /tmp/codespider-generation-replay \
  --replay /tmp/codespider-generation-new --execute
```

`--case python-cart` 等可选择单例。也可通过 `--settings-file` 读取私有 provider JSON（不进入报告）。输出目录必须不存在，避免覆盖先前证据。重放报告明确标注 `saved_model_patches`，不冒充新一轮模型生成通过率。

## 系统回归

变更后：77 项 Python 单元/集成/独立 daemon 回归全部通过；4 组前端脚本回归通过（审批、任务绑定、工程会话、生成上下文确认与补丁预览）。新覆盖包括安全模式未批准不调用模型、真实 HTTP 生成链路、远端 Agent 的 context/create_file 工具、源码与 AST 上下文、业务断言失败、零测试、部分依赖目录、创建冲突和截断恢复保留代码。

## 当前边界

这四个例子证明小型工程和精确已有文件修改链路可以执行，不等于复杂工程或商用成熟度认证。Python 默认测试发现目前支持 unittest，未配置的 pytest 工程会明确失败或需另行运行 pytest；Java 示例是 Maven 工程，Gradle 尚未纳入本次验证；Java/Vue 仍不是真正完整 AST。上下文是有预算的文件选择，凭据排除基于路径名称，不能保证源码内硬编码密钥自动识别。测试失败不会自动回滚已经写入的文件或自主改写测试；错误日志用于用户审查后发起下一轮修复。
