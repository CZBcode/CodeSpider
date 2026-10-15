# 原型视觉与交互验收案例

这些页面由 qwen3.8-max 通过 CodeSpider 原型插件实际生成，并根据浏览器验收反馈做过后续精修。需求见 `tests/prototype_visual_cases.json`。

| 目录 | 视觉方向 | 验收内容 |
| --- | --- | --- |
| members | 灰绿数据工作区、统一 Element UI 配色 | 筛选、空态、必填/邮箱校验、新增、窄屏表格滚动与弹窗焦点 |
| studio | 温暖纸色、陶土强调色、杂志式分割与留白 | 案例分类、联系表单错误/成功状态 |
| board | 低对比泳道、白色任务卡、克制的操作按钮 | 新建、优先级、搜索、跨列移动、统计更新、标题按文本渲染 |

直接把任一目录作为 CodeSpider 原型工程打开并构建预览即可。成员页的 Vue 2 / Element UI 资源由插件自动提供，不提交重复第三方库到此目录。品牌页与看板可用本地静态 HTTP 服务打开。

复跑验收（在仓库根目录，需 Node、Python、Playwright 与 Chrome）：

```sh
VISUAL_CASES_DIR=examples/prototypes/visual-cases \
VISUAL_BEHAVIORS=1 \
PLAYWRIGHT_MODULE=/path/to/playwright \
CHROME_PATH=/path/to/chrome \
AXE_SOURCE=/path/to/axe.min.js \
node tests/frontend_prototype_visual.cjs
```

浏览器在 1440、768、390 像素宽度下检查并截图，所有构建在临时副本里运行，不修改示例源码。可访问性工具只能发现部分问题，截图仍需人工审阅。

保留的来源与修正：成员页面原始草稿在修正无参数设计契约、对象方法索引后原样通过结构检查；键盘操作由模型后续修正。品牌页和看板由模型仅修改 CSS 精修。最后人工去掉看板移动按钮的 0.7 透明度，以修复实际测得的文字对比度不足；相同教训已反馈到插件规则。示例使用内存数据，表单成功状态是模拟反馈，不会发送邮件或保存业务数据。
