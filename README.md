# CodeSpider

项目功能、实现取舍、完成程度、后续优先级及 AI coding 费用口径见 [项目实现说明](docs/implementation-overview.md)。

CodeSpider 是一个面向代码工程的本地 Agent 工作台 MVP。当前实现提供：

- 本地工作区创建、文件树和文件内容读取
- Java Spring Boot、Python、Vue、HTML / JS / CSS 前端原型工程识别
- Python AST、Java/Vue 轻量符号索引
- 任务计划、审批、异步执行、事件流和取消
- 安全的文件读取、补丁写入和命令执行
- 短期上下文、项目记忆、个人偏好和 Skill JSON 存储
- 无前端构建依赖的浏览器工作台
- Codex 风格的首页、自由对话、项目工作台、工程结构、产物、终端和项目设置视图，支持侧栏折叠与聚焦模式
- 项目级安全执行模式与发散模式，支持命令白名单和操作确认
- 全局模型设置，支持供应商、模型、Base URL、生成参数和 API Key 脱敏管理

## 下载后启动

当前支持 macOS / Linux，要求 Python 3.9+。前端随安装包提供，不需要 Node、npm、数据库或单独的前端构建。当前未支持原生 Windows。

下载并解压源码后，进入项目目录：

```bash
python3 -m codespider start --open
```

CLI 启动后台 daemon，daemon 分别启动 Web 服务和 Agent 进程。就绪后打开 <http://127.0.0.1:8787>；关闭终端或浏览器不会停止服务。首页可以选择/创建工程或自由对话。

新建工程只需填写项目名称，默认自动创建 `~/.codespider/project/{项目名称}`。例如 `my-app` 对应 `~/.codespider/project/my-app`。也可填写已有工程路径；已有工程不会自动迁移。此默认项目位置不随 `--data-dir` 改变。

也可以先安装 CLI，随后在任意目录使用：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
codespider start --open
```

`--open` 可省略，默认端口为 8787，只监听本机 `127.0.0.1`。

## 管理服务

```bash
codespider status
codespider status --json
codespider logs --component daemon
codespider logs --component web --lines 100
codespider logs --component agent
codespider stop
codespider restart --open
```

未安装 CLI 时，将上面的 `codespider` 替换为 `python3 -m codespider`，在源码目录执行。

- 默认数据目录为 `~/.codespider`，也可以通过 `CODESPIDER_DATA_DIR` 或每条命令的 `--data-dir /absolute/path` 指定。
- 项目列表、任务、记忆和模型设置会持久保存；停止/重启不会删除配置或工程文件。工程索引和工程运行日志保存在对应工程的 `.codespider/` 下。
- daemon、Web、Agent 日志保存在数据目录的 `logs/` 下。
- 重复启动同一实例会返回已有地址；端口被其他程序占用时启动失败，并提示日志位置，不会结束其他程序。
- 切换端口使用 `codespider restart --port 8788`。自定义端口的后续 start/restart 命令也需传入 `--port`。服务器需要通过公网地址访问时使用 `codespider start --host 0.0.0.0`；本地默认仍只监听 `127.0.0.1`。
- `stop` 停止 Web、Agent 及 Agent 启动的工程进程；执行中的命令会被终止。正在执行的任务不会自动恢复或重放。
- 子服务退出后，daemon 清理另一子服务并报告失败，可通过日志诊断后手动重启。

已有旧版工程内数据时，可以继续使用该目录，所有管理命令使用同一个 `--data-dir`：

```bash
python3 -m codespider start --data-dir /path/to/CodeSpider/.codespider
```

## 开发模式

单进程前台调试仍可使用（请先停止占用同一端口的 daemon）：

```bash
python3 -m backend.app --workspace /path/to/your/project --port 8787 --data-dir /path/to/dev-data
```

此前台模式使用嵌入式 Agent，按 Ctrl+C 停止。安装交付以 daemon 模式为准。

## 运行测试

```bash
python3 -m unittest discover -s tests -v
```

前端审批交互回归测试（需要 Node，仅用于测试）：

```bash
node tests/frontend_approval.mjs
node tests/frontend_task_binding.mjs
node tests/frontend_p2_workflows.mjs
```

任务验证命令退出码非零时标记为失败。取消执行中的任务会先进入 `cancelling`，待 Agent 终止命令、完成在途文件操作并阻止后续调用后，才标记为 `cancelled`；已完成的文件写入不会自动回滚。Agent 失联时保留 `cancelling`，可重试取消。已成功或失败的任务不能被取消覆盖。

每张审批卡片绑定自己的任务，并显示执行目录。任务创建时保存工程配置快照；此后修改项目设置只影响新任务，原任务的文件操作和验证仍使用快照目录。旧版未保存快照的待审批任务会在批准时保存当前配置。

同一浏览器页面内，各工程分别保存对话、当前任务、输入草稿和命令草稿；切换工程会清空文件预览、文档预览及终端结果，避免展示其他工程的内容。迟到的任务响应仍归属于原工程，后台任务的事件会继续同步。会话展示状态暂存在页面内存中，刷新页面后不会自动恢复。

任务轮询在读取到最终事件并显示结果后才停止；状态先完成、事件稍后到达时继续同步，网络异常时自动退避重试，不重复显示已处理事件。

符号查询和文档生成会重新扫描当前代码，覆盖任务、文件工具及外部编辑器产生的变更；任务完成补丁写入后也会刷新索引。当前采用全量扫描，大工程会增加读取耗时。工程创建仅在首次索引成功后登记，失败重试不会留下多余记录，也不会删除已有工程文件。

文件工具通过文件锁串行化同一文件的修改，补丁在锁内检查旧内容并写入；竞争同一旧版本的补丁只允许一个成功，其余返回冲突。此协调范围是 CodeSpider 文件工具，外部编辑器或任意用户命令不受该锁协议约束。

任务生成代码后会重新识别工程类型，再选择 Python、Java 或 Vue 的验证命令。未能识别生成工程时会报告“未执行验证”并将任务标记失败，保留已写文件供补充配置后检查。

## 目录

```text
backend/          控制面 HTTP 服务、任务状态机和持久化
codespider/       CLI、daemon 生命周期与本机 IPC
agent_client/     本地 Agent Client、文件与命令工具
code_intelligence/AST/符号索引与工程类型识别
memory/           分层记忆和 Skill 存储
frontend/         静态工作台
tests/            标准库单元测试
docs/             需求与技术设计文档
```

任务执行器使用可审查的本地计划和工具协议；配置 OpenAI 兼容服务后，`backend/model_gateway.py` 会对模型输出执行结构化解析、契约校验、重试和补丁安全检查。未配置远端模型时仍使用本地确定性计划，便于离线开发和回滚。

## 账户、模型与积分

生产 daemon 默认开启账户认证（`CODESPIDER_AUTH_REQUIRED=1`）。打开页面后先注册或登录；数据库使用本地 H2 文件库，位于数据目录的 `h2/`。首个注册账户自动获得 `ADMIN` 角色，后续账户为普通用户。密码使用 PBKDF2-SHA256 哈希保存，服务端不保存明文密码。

H2 运行需要 H2 JDBC jar。开发环境可设置 `CODESPIDER_H2_JAR=/absolute/path/h2.jar`；systemd 部署默认读取 `/opt/codespider-lib/h2.jar`。管理员可以在“全局设置”添加多个模型、启用/停用模型、给用户分配模型并充值积分。普通用户只能选择管理员分配的启用模型，并可查看自己的调用记录和余额。每次创建一个需要模型的任务扣除 1 积分；请求携带相同 `request_id` 重试时不会重复扣费。

主要账户 API：`POST /api/auth/register`、`POST /api/auth/login`、`POST /api/auth/logout`、`GET /api/auth/me`；普通用户使用 `GET /api/models`、`POST /api/models/select`、`GET /api/usage`；管理员使用 `/api/admin/models`、`/api/admin/users` 及用户充值和模型分配接口。

## 模型兼容接口与对抗测试

模型网关支持 OpenAI 兼容的 `/chat/completions` 接口。服务器当前配置为通义千问兼容服务，实际可用模型标识为 `qwen3.8-max`（服务端模型 ID 区分大小写）；页面显示名称为“通义千问 Qwen3.8 MAX”。API Key 只保存在服务器的管理员配置和 H2 模型记录中，接口只返回是否设置及脱敏预览。

仓库提供 20 个 Java、Python、Vue 安全与并发经典场景，覆盖 SQL 注入、路径穿越、XSS、竞态、幂等、SSRF、反序列化、重试、死锁、时区、异步竞态、缓存击穿、分页、上传、越权、资源泄漏、原型污染、金额精度、命令注入和 AST 重构。使用环境变量运行：

```bash
export CODESPIDER_MODEL_API_KEY='your-key'
python3 benchmarks/run_adversarial.py \
  --base-url https://maas.qianwenaiapi.com/compatible-mode/v1 \
  --model qwen3.8-max --max-tokens 2048 --concurrency 2 --retries 1 \
  --output /tmp/codespider-adversarial.json
```

runner 默认关闭供应商隐藏思考以提高批测吞吐，但仍强制检查 `thinking[]`、步骤、工具调用和补丁结构；需要测试开启隐藏思考时增加 `--enable-thinking`。每个用例独立超时，报告会区分超时、上游错误、JSON 契约失败和安全语义缺失。

## 实际工程生成验证

可运行示例见 [examples/README.md](examples/README.md)，包括 Python 金额计算、已有代码修复、Spring Boot JSON 接口和 Vue 计数器。四例均经过真实模型生成、审批写入、构建/测试及独立验收；首轮依赖环境失败及补丁重放结果见 [实测报告](docs/generation-validation.md)。

远端生成任务会先收集受控文件上下文和符号，安全模式先询问读取授权。已有文件使用完整 expected 校验，新文件使用独占创建；审批卡展示修改内容。生成契约恢复必须保留非空代码补丁，不能通过仅返回计划宣告生成成功。Python 执行 unittest、Java 执行 Maven test、Vue 校准依赖并执行构建和 test 脚本。未发现 Python 测试时会说明只检查语法。

使用 `python3 benchmarks/run_generation.py --output /tmp/codespider-generation-new --execute` 进行端到端实测（模型环境变量同上）；支持 `--case` 单例和 `--replay` 重放。此 runner 会执行生成代码，应使用受控的一次性环境。

## 设计契约与工程化生成

生成任务支持模块职责、公开接口与模式适用理由，并根据源码检查依赖方向、循环、类与函数结构。工程根目录的 `design-contract.json` 可选择建议或强制模式；前端“工程结构 → 结构审查”可查看独立报告。

- [设计契约与使用方式](docs/design-contracts.md)
- [多模块工程及策略扩展示例](examples/engineering/README.md)
- [真实生成、失败修复与独立验收报告](docs/engineering-validation.md)
