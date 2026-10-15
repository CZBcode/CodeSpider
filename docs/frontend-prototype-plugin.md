# 前端原型插件

`plugin.prototype` 是独立于 Vue、Spring Boot、Python 的工程插件，项目类型为 `html-prototype`。新工程提出“前端原型”“HTML/JS/CSS”“静态页面”“Element UI”等需求会优先推荐此插件；既有项目继续使用其已有技术栈。明确同时提到不同技术栈时仍提供选择。插件支持按用户安装、启用/停用。

## 生成约定

默认生成 `index.html`、`styles.css`、`app.js` 和 README，可以拆分本地 JavaScript 模块、资源与多个 HTML 页面。无需 package.json、npm 安装、Vite 或 Vue 单文件组件。界面、状态和业务校验分开实现，使用明确的模拟数据与可操作按钮，不为简单原型引入无用的 MVC 层。

原型识别要求根目录有 index.html 且无 package.json；优先级低于已有框架插件，避免把 Spring 模板或 Python 项目误判为原型。纯 HTML/CSS 无需 Node；有 JavaScript 时由 Agent 环境中的 Node 做语法检查，不执行用户脚本来“验证”它。

### 视觉设计约定（1.1.0）

生成前先确定符合业务的页面构图，默认追求克制、清晰、有层级的完成度。用户提供品牌、参考或已有样式时优先沿用；后台、品牌网站、小工具、任务看板不强行套用同一个模板，也不为装饰增加无关指标和无效导航。

- CSS 使用一套颜色、间距、圆角变量；统一字体层级、对齐、留白、边框和阴影。默认本地系统字体，包含中文回退字体。
- Element UI 需要同步定制按钮、输入框、表格、空态和弹窗的正常/悬停/焦点/禁用状态，不能仅依赖默认组件皮肤。
- 提供三种可调整的设计起点：沉静灰绿的数据工作区、纸色与陶土色的杂志式品牌页面、低对比泳道与白色任务卡的个人看板；用户风格优先，不强制模板。
- 1440、768、390 像素宽度下保持主要操作可见；表格可以在自身容器内滚动，页面不能整体横向溢出；移动端弹窗保留取消与提交按钮。
- 明确表单标签、键盘焦点和错误提示；以文字或图标辅助状态颜色，动效尊重减少动画设置。对比度以 WCAG AA 为设计目标，但未经测量不能声称通过无障碍认证。
- 表格真实滚动容器可通过键盘聚焦；弹窗打开时聚焦首个字段，支持 Tab、Escape 和关闭后焦点恢复。既有文件更新优先使用原文件哈希，避免回显旧文件浪费输出长度。
- README 记录简短视觉说明和人工验收步骤。分文件生成时，页面类名、设计变量、DOM ID 和交互状态写入文件契约，降低样式与结构脱节风险。

这些要求通过插件提供给模型，不向用户工程强行注入固定样式，也不改变编译检查的含义。静态编译成功不代表视觉和交互验收通过。

插件通过 `staged_initial_generation` 声明新建原型采用分文件生成：后台生成先规划文件，再逐个生成 HTML、CSS、JavaScript 和 README，即使原始需求很短也不把完整页面塞进一次响应。沿用既有的进度、断点续生成和审批流程；已有工程的小修改仍按需求规模选择快速或分批路径。每次实际模型请求仍按现行规则计费，因此四个文件通常需要一次规划加四次文件请求，重试另计。

真实模型验收场景保存在 `tests/prototype_visual_cases.json`。将生成目录按 `members/`、`studio/`、`board/` 保存后，可通过 `python3 -m tests.prototype_visual_fixture /path/to/cases` 使用真实原型构建与预览链路；第一行输出本机预览地址。验收需分别检查首屏、完整页面、窄屏、空态、非法输入、成功提交和键盘操作。测试使用独立临时状态，不写入生产账户或聊天记录。

可重复浏览器验收：

```sh
VISUAL_CASES_DIR=/path/to/cases \
VISUAL_OUTPUT_DIR=/tmp/prototype-report \
VISUAL_BEHAVIORS=1 \
PLAYWRIGHT_MODULE=/path/to/playwright \
CHROME_PATH=/path/to/chrome \
AXE_SOURCE=/path/to/axe-core/axe.min.js \
node tests/frontend_prototype_visual.cjs
```

输出每个场景的 1440/768/390 像素截图和 report.json。`AXE_SOURCE` 可选（本次使用 axe-core 4.10.3），未提供时不会执行可访问性扫描；扫描也不替代人工视觉评审。`VISUAL_CASES=members,studio` 可选择部分场景。交互脚本针对此次保留的生成结果 DOM；重跑模型如果更换 DOM，需对应更新选择器，不能因此跳过行为断言。

## Element UI

Element UI 2 基于 Vue 2。它在这里作为普通页面脚本依赖使用，不会把原型升级成 Vue 工程。

```html
<link rel="stylesheet" href="vendor/codespider/element-ui.css">
<link rel="stylesheet" href="styles.css">
<div id="app"><el-button @click="count++">{{ count }}</el-button></div>
<script src="vendor/codespider/vue.min.js"></script>
<script src="vendor/codespider/element-ui.js"></script>
<script src="app.js"></script>
```

```javascript
new Vue({el: '#app', data() { return {count: 0}; }});
```

固定依赖为 Vue 2.7.16 和 Element UI 2.15.14。资源、字体和 MIT 许可证随 CodeSpider 分发，npm 包下载时验证完整性；每次准备工程依赖时再次验证 SHA-256。构建按需将库文件写入 `vendor/codespider/`，同名文件如果被修改则报错，不覆盖用户内容。模型只引用这些路径，不生成第三方源码。

构建后的工程下载包包含依赖，可以离线使用；使用 ES 模块时通过本地静态 HTTP 服务打开。第三方库目录不加入工程代码理解上下文。原型不依赖外部 CDN；CSS 字体及图片采用本地相对路径。完整可运行用法见 [Element UI 成员管理示例](../examples/prototypes/element-admin/README.md)。

## 验证与预览

沿用 `preview.build/status/deploy/cancel` 和 Function 市场。审批后的代码修改自动触发：结构检查 → JavaScript 语法/HTML、CSS 资源引用检查 → 打包静态文件 → 原子发布。生成期间不写入文件或准备依赖，仍必须先批准任务。

验证会检查入口、缺失资源、JS 语法、静态模块引用、越界路径、符号链接及产物大小。错误显示在折叠的构建日志中，已有成功预览不变。语法与资源检查不等价于行为测试；README 应列出具体的交互验收步骤。

预览继续使用不开放 `allow-same-origin` 的沙箱，账户、工作台接口、浏览器存储和外部资源仍被隔离。仅原型插件的发布记录允许 `unsafe-eval`，用于 Vue 2 HTML 模板编译；Vue/Vite 插件的策略不变。静态资源权限与已有预览相同：完整随机能力链接可读取当前版本的资源，新版本发布或项目删除后旧链接失效。

沙箱允许原生表单校验和 JavaScript submit 事件；CSP `form-action 'none'` 阻止表单实际发送网络请求。浏览器回归同时验证本地提交成功和无处理器的网络提交被拦截。

## 测试与回滚

- `tests/test_prototype.py`：语义选择、既有工程检测、用户级开关、依赖完整性/冲突、资源/语法错误、自动发布和失败回退。
- `tests/frontend_prototype.cjs`：真实 Element UI 表格筛选、空态、弹窗、表单校验/保存、依赖下载、自动更新、移动端及原生 JS，无 CDN 请求。
- 既有 Vue 构建和账户隔离回归继续执行。

无需账户或会话迁移。新增插件可从市场停用，已有预览工具保持兼容；部署回滚通过切换旧代码版本完成，不恢复旧数据覆盖用户新操作。

### 2026-10-15 验收记录

使用当前配置的 qwen3.8-max 实际生成并执行两组需求，每组均生成 index.html、styles.css、app.js、README.md，没有 package.json 或 .vue 文件：原生 JS 待办列表（生成至发布约 53 秒）、Element UI 成员管理（约 40 秒）。两组均在服务器 bubblewrap 沙箱中通过原型检查并发布预览；随后独立浏览器验证待办空白拦截/新增/清空/删除，以及成员筛选/弹窗/必填校验/保存。

固定示例额外验证了离线组件字体、ZIP 下载、任务更新自动发布、失败保留旧预览、移动端布局和父页面隔离。预览文本响应显式使用 UTF-8，简短 HTML 未写 meta charset 也可显示中文。

### 视觉精修验收

保留的可运行源码见 [三个视觉验收案例](../examples/prototypes/visual-cases/README.md)。真实模型生成成员管理、留白工作室和任务看板，浏览器反馈后再由模型修改键盘行为或样式；最后人工移除了看板次要按钮的 0.7 透明度，修复实测文字对比度不足，并把规则反馈到插件。

最终三个案例在 1440、768、390 像素下全部通过资源加载、无横向页面溢出、无 JavaScript 错误、无外部资源请求和既定交互测试；axe-core 4.10.3 的 WCAG A/AA 扫描在这九个初始页面状态中没有发现违规，截图也进行了人工检查。这不等于全状态无障碍认证，也不保证任意模型输出一次达标。

系统回归共 166 项：163 通过、3 项环境条件跳过。真实 Vue 构建预览回归和原型的本地表单处理/网络提交拦截回归均通过。

本次实测同时修复了两类生成误报：JavaScript 对象函数属性/简写方法未进入符号证据，以及无参数接口以空字符串描述输入被拒绝。符号存在性、必需输出描述、依赖边界和执行审批仍保留。新建原型分文件生成解决整页同次响应过长的问题；已有文件优先用哈希引用旧内容并精简重复 CSS。模型输出限制依然有效，复杂单文件仍可能需要缩小修改范围。
