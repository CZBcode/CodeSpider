# 前端构建与预览

插件声明 `preview_supported` 能力。目前支持有 `vite` 依赖、`build` 脚本的 Vue/Vite 静态工程，以及独立的 [HTML/JS/CSS 前端原型](frontend-prototype-plugin.md)；Spring Boot、Python 和其他构建器仍沿用原有验证流程。

## 使用方式

- 项目 → **预览** → **构建并预览**：按插件准备依赖、检查并构建，成功后发布；安全模式下按命令白名单或用户确认执行。前端原型无需 npm 构建。
- 批准对话任务后，若任务修改了支持预览的工程，依次执行依赖准备、测试、设计契约检查、前端构建、预览发布。不会重复执行普通 build。
- 当前预览页轮询最新版本并自动刷新；聊天结论提供“查看预览”入口。构建日志在完成或失败时折叠。
- 构建状态、日志和成功产物持久化在服务数据目录，刷新、重新登录后可恢复。关闭浏览器不会停止手动构建；可在预览页取消。

## 标准工具 API

统一调用 `POST /api/tools/call`，使用 `api_version: "1.0"`、当前 `workspace_id`、`tool: "preview"`。用户身份由服务端注入，沿用现有审批字段。

| action | arguments | 结果 |
| --- | --- | --- |
| `build` | `{}` | 立即返回 `job.id`，异步构建。独立调用自动发布；会话任务由执行器在检查成功后调用 deploy。 |
| `status` | `{}` | `supported`、`job`（状态/日志/错误）、`current`（版本/链接/发布时间）。读取无需确认。 |
| `deploy` | `{"build_id":"..."}` | 仅发布当前工程最近一次成功且源码未改变的版本。 |
| `cancel` | `{"build_id":"..."}` | 取消当前工程的指定构建，不影响其他工程。 |

Function 市场新增 `function.preview.build`、`function.preview.status`、`function.preview.deploy`。编排器根据插件能力决定调用，不判断框架名称。

## 版本与失败处理

构建使用唯一输出目录和 URL base，不覆盖正在使用的版本。安装最多 300 秒，编译最多 180 秒；异步工具不占用长时间的浏览器请求。最多同时运行 4 个构建，同一工程只能构建一个版本。

发布前检查源码指纹（忽略依赖、构建输出和索引目录），拒绝构建期间或发布前被修改的源码。构建失败、取消、Agent 重启均保留上一次成功预览；重启中断的构建需要重新执行。更换项目根目录后需重新构建。删除项目立即使其预览失效。

每次发布保留当前和上一份磁盘产物，新构建清理已废弃的待发布产物；Agent 启动清理无记录的产物目录。单份源码检查和静态产物限制为 64 MB / 4000 文件。只复制普通文件，拒绝符号链接，排除隐藏产物与 source map。发布记录原子更新。

## 浏览器隔离边界

预览只暴露已发布的静态产物，不暴露源码或启动任意公开端口。页面通过 `sandbox="allow-scripts allow-forms"` iframe 和服务端 CSP 双重隔离；不开放 `allow-same-origin`。`allow-forms` 仅使原生校验和 JavaScript submit 回调可用，CSP `form-action 'none'` 继续禁止实际表单网络提交。预览脚本不能读取工作台 DOM、Cookie、localStorage，也不能调用工作台 API；跨站和 opaque-origin 的写请求在 API 层拒绝。

静态模块通过 192 bit 随机能力链接及仅针对预览的 CORS 加载；**持有完整预览链接即可读取该版本的静态资源**，链接不作为公开分享功能提供。新版本发布或项目删除后旧链接失效。不得将服务端密钥或私密数据打包进前端。

当前是静态 UI 预览，不包含后端 API 联调、浏览器持久化、外部资源、弹窗或服务端渲染。资源路径应使用 Vite 导入或 `import.meta.env.BASE_URL`；支持版本路径下的 SPA HTML 回退，不回退不存在的 JS/CSS。需要完整后端联调时仍使用项目终端/运行服务功能。

## 验证与部署

`tests/test_previews.py` 覆盖审批、用户隔离、恢复、自动发布、只读任务、失败保留旧版、取消、源码变化、符号链接、路径穿越、项目删除及空 Origin 请求。

`tests/frontend_preview.cjs` 使用真实 Vue SFC、npm、Vite、HTTP API 和浏览器，检查交互、自动更新、失败回退、刷新恢复、项目/账户切换和 sandbox。需要 PATH 中有可运行原生构建依赖的 Node/npm，以及 Playwright/Chrome；可用 `CODESPIDER_TEST_NPM_REGISTRY` 指定测试依赖仓库。

部署无需迁移已有账户/会话数据；新增 `previews.json` 和 `previews/`。部署前检查无活动任务、生成和构建，备份数据后切换代码版本。回滚只切换代码，不覆盖用户数据；旧版本忽略新增预览记录。
