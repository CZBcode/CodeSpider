# 用户隔离与能力市场

2026-10-14。本次保留既有 Web / Agent / H2 / JSON 存储结构，新增租户边界和可信能力注册机制。

## 用户体验

点击右上角头像 → 设置 → 插件市场。Plugin、Skill、Function 可搜索、筛选、安装/卸载及启停；配置按当前用户保存。内置能力默认安装并启用。个人 Skill 可填写名称、关键词、说明和执行指导，保存后仅本人可见。

- Spring Boot、Vue、Python 的工程识别、生成指导、安装与验证命令由独立插件提供。
- 工程类型已确定时优先选择对应插件；空工程按中英文关键词匹配需求。多技术栈同分时提示明确选择；停用插件时明确拒绝，不静默绕过。
- 相关 Skill 与 Function 描述进入生成上下文，任务保存本次选择与版本快照，方案详情中可查看。
- Function 可在市场展开「在当前项目调用」，填写 JSON 参数后执行；只读操作无需确认；写入文件、生成文档和执行命令仍沿用项目审批策略。

## 隔离契约

| 资源 | 身份与边界 |
| --- | --- |
| 项目列表、设置、文件树、下载、文档 | 认证会话的用户 ID；不可伪造 owner_id |
| 新工程路径 | `~/.codespider/project/{user_id}/{project_name}`；普通用户不能指定该范围以外目录 |
| 管理员外部工程 | 可打开外部目录，但不得覆盖服务数据或与其他用户工程/历史任务目录重叠 |
| 任务、事件、批准、取消、工具 | 同时检查用户、task_id、workspace_id；任务快照锁定执行目录 |
| 自由对话 | 历史按用户读取；同用户历史构建串行，不同用户可以并发 |
| 工程生成 | 每次调用独立传入模型、上下文、用户、补丁；扣费归当前用户 |
| 市场安装、个人 Skill、记忆 | 用户分区；个人搜索不回退到共享 global 记忆 |
| 浏览器延迟响应 | 账户版本号失效检查，退出或换号后旧响应不得覆盖新用户页面 |

账号和对话仍保存在 H2；项目、任务、事件及市场偏好使用已有原子 JSON Store。`market_preferences.json`、`user_skills.json` 中的每条记录带用户 ID。重启或重新登录不清理这些数据。

旧项目迁移不移动文件：已有唯一任务用户的项目归该用户；无明确任务归属或多个任务用户时归首个管理员。迁移幂等，原有文件、任务和对话内容保持不变。无法明确归属的共享工程不会自动复制给所有用户。

## 插件扩展协议

`engineering_plugins/registry.py` 自动发现该包内受信任模块。新增插件需要：

1. `MANIFEST`：`api_version: "1.0"`、唯一 `id`、`kind: "plugin"`、名称、版本、说明、`project_types`、关键词、执行指导和默认验证命令。
2. `detect(root)`：判断当前工程是否适用。
3. `verification(root)`：返回 `verify_command`、`setup_commands`、`verification_commands` 和候选 `commands`。
4. 补充工程样例及行为测试，通过验证后随应用发布。无需在 TaskManager 增加技术栈分支。

插件为服务端可信 Python 代码，普通用户的「安装」是启用已发布能力，不会下载或执行任意第三方插件。当前没有公共投稿、第三方签名审核或云端付费市场。路由采用工程检测和关键词规则，不是通用语义模型分类器。

## 标准 Function API

所有 Function 通过现有版本化工具 API 分发，保留身份、任务绑定、审批、取消和错误格式：

```json
{
  "api_version": "1.0",
  "tool": "function",
  "action": "call",
  "workspace_id": "当前用户项目 ID",
  "arguments": {
    "function_id": "function.workspace.read",
    "input": {"path": "src/main.py"}
  },
  "approval": {"approved": true}
}
```

入口：`POST /api/tools/call`。能力目录：`GET /api/market`；配置：`POST /api/market/preferences`；个人 Skill：`POST /api/market/skills`。

首批 Function：文件读取、精确补丁、AST/符号索引、设计契约审查、执行验证命令、生成工程文档。输入按 schema 校验，禁止未知字段；未安装/停用拒绝调用。模型输出的 tool_calls 仍为计划，不能据此跳过审批或任意执行命令；受控任务流程负责实际应用补丁与运行插件验证。

## 服务器执行边界

生产 systemd 启用 `CODESPIDER_EXECUTION_SANDBOX=bubblewrap`。命令执行与常驻工程进程均进入 Linux namespace 沙箱：当前工程可写，系统运行时只读；临时目录和 HOME 私有，宿主机应用数据、其他工程、IPC 凭据、宿主进程不可见。Java HOME 显式指向沙箱临时目录。沙箱不可用则报错，不退回宿主机。

Ubuntu 的 userns AppArmor 限制通过专用于 `/usr/bin/bwrap` 的 profile 处理，没有全局关闭 AppArmor。依赖安装保留网络。此版本尚不提供网络租户隔离、端口代理鉴权、CPU/内存/磁盘配额；不能据此称为完整的不可信公网代码托管沙箱。非 Linux 开发环境未启用 bubblewrap 时只适合可信单用户本地使用。

## 验证与发布

- 本地完整后端回归 124 项通过，含真实 H2、并发 HTTP、工程生成执行及独立 Spring HTTP 行为验收；随后新增的迁移幂等测试和沙箱配置测试通过。
- 4 组前端回归通过，增加市场筛选、HTML 转义、换号后旧结果失效、审批时参数固定；真实 HTML DOM 的市场页控件测试通过。
- 服务器以 codespider 用户开启沙箱，11 项市场/用户隔离/真实 daemon 重启持久化测试通过。
- Linux 沙箱 3 项测试通过：拒绝回退、跨工程/数据库/环境隔离、Java 编译、Maven 测试、Vue 依赖安装与 Vite 构建。另在 systemd 的 NoNewPrivileges / PrivateTmp 配置下复验。
- Wheel 打包与独立环境安装通过，验证 3 个插件、Web/Agent 模块、前端资源和 H2 Java 桥接文件均随包安装；修复了原 package-data 中带点包名未加引号的问题。
- 并发模型测试使用受控 provider，检查两个请求确实同时进入、各自模型和上下文及扣费；本次未据此宣称真实付费大模型的生成质量提升。

复验：

```sh
python3 -m unittest discover -s tests -v
node tests/frontend_approval.mjs
node tests/frontend_task_binding.mjs
node tests/frontend_generation.mjs
node tests/frontend_p2_workflows.mjs
# Linux，需 bubblewrap / Java / Maven / Node / npm：
CODESPIDER_EXECUTION_SANDBOX=bubblewrap python3 -m unittest tests.test_execution_sandbox -v
```

发布目录：`/opt/codespider-releases/20261014-market`。数据保留在 `/var/lib/codespider/.codespider`。发布前确认无执行/生成任务，停服务后备份 H2 与 JSON 至 `/var/backups/codespider/market-20261014`；发布后比较账户、对话、计费、模型的摘要，核对每个项目归属和原目录，并检查 health、静态文件以及未登录 401。线上 4 个现有项目已迁移，以上摘要及任务、事件记录核对一致；域名 health 与 Agent 均正常。

回滚必须先停服务、保存当前数据，再恢复兼容的数据与程序及 systemd drop-in。旧程序不识别新增的 owner_id/capabilities 字段，不能只切换软链接。发布窗口内可恢复备份；产生新数据后，应先导出新增记录并设计兼容转换，避免直接恢复旧备份造成新数据丢失。原发布路径保存在备份的 `previous-release.txt`。

## 2026-10-14 只读操作免确认

安全模式中的文件读取、搜索、AST/符号索引、工程检测、设计审查、已保存文档读取，以及用户发起生成时的上下文读取，不再弹出确认框。用户归属、目录越界和符号链接检查仍执行。生成代码先展示补丁，批准后才写入；生成文档会写入/覆盖 `CODESPIDER.md`，仍需确认；任意命令仍受命令审批及白名单约束。

前后端同时移除只读确认分支，避免文件树/预览/产物页反复弹窗。HTTP 回归覆盖 10 种只读工具无需审批、其他用户访问仍为 403，以及写入、命令和目录越界继续被阻止。

只读策略版本发布至 `/opt/codespider-releases/20261014-readonly`，备份目录 `/var/backups/codespider/readonly-20261014`，数据结构不变。本地 129 项回归中 127 项通过、2 项 Linux 沙箱集成项在 macOS 跳过；服务器 13 项 HTTP/权限/生成/持久化专项及 4 组前端回归通过。
