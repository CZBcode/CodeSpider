# 网页内弹窗（2026-10-14）

统一使用 HTML dialog 与应用内异步确认接口，替换所有 window.confirm/window.prompt。覆盖命令执行、服务启动、文档写入、Function 调用、模型分配和清除密钥；只读结构审查保持免确认。

弹窗采用深色圆角卡片、背景遮罩、操作内容预览、明确的确认与取消按钮，危险操作使用红色强调。移动端宽度自适应；支持 Esc、遮罩关闭、焦点循环与关闭后焦点恢复。输入校验错误直接显示在弹窗内。动态内容使用 textContent，不解析用户 HTML。

异步审批保留原命令、工程、Function 参数和账号版本；确认前再次核对目标，切换账号、工程或页面时取消待处理弹窗。并发确认排队处理，取消不会重试工具或显示额外错误。

验证：4 组现有前端回归；tests/frontend_dialogs.cjs 在真实 Chromium 中验证桌面与 390px 手机布局、焦点、Esc/遮罩/关闭、审批命令固定、队列、输入校验、危险操作取消、账号与工程切换；断言没有浏览器原生 dialog 事件。

浏览器复验需要 Playwright，可通过 PLAYWRIGHT_MODULE 指定已有模块路径、CHROME_PATH 指定 Chrome 可执行文件。截图输出 /tmp/codespider-dialog-desktop.png 和 /tmp/codespider-dialog-mobile.png。

发布目录：`/opt/codespider-releases/20261014-dialogs`；备份：`/var/backups/codespider/dialogs-20261014`。确认生成请求结束后切换版本，核对账号、对话、积分、任务和工程数据未改变，Web/Agent 健康检查通过。浏览器还针对线上静态资源执行同一套测试（API 全部拦截模拟，不操作真实用户数据）。
