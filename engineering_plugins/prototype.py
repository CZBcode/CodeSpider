"""Plain browser prototypes, independent of framework build projects."""
import hashlib
import json
import os
from pathlib import Path
import shlex

MANIFEST = {
    'api_version': '1.0', 'id': 'plugin.prototype', 'kind': 'plugin', 'name': '前端原型（HTML / JS / CSS）',
    'version': '1.1.0', 'priority': 5, 'project_types': ['html-prototype'],
    'description': '独立的静态页面与交互原型，支持本地 Element UI 组件、资源检查和自动预览，无需 Vue/Vite 工程。',
    'keywords': ['原型', 'prototype', 'html', 'html5', 'css', '静态页面', '静态网站', 'element ui', 'element-ui', 'elementui'],
    'preferred_keywords': ['原型', 'prototype', 'html', 'html5', '静态页面', 'element ui', 'element-ui', 'elementui'],
    'intent_keywords': ['线框图', '高保真', '交互稿', 'mockup', 'wireframe'],
    'recommendation': '适合无需构建框架的 HTML / CSS / JavaScript 页面和交互原型，可使用 Element UI。',
    'recommendation_priority': 15,
    'staged_initial_generation': True,
    'instructions': '''Build an independent HTML/CSS/JavaScript prototype, not a Vue/Vite/npm or backend project.
Create index.html, styles.css, app.js (or small JS modules), README.md and optionally local assets/multiple HTML pages.
Do not generate package.json, .vue files, Python/Java build scripts, or copy/minify third-party libraries.
Use relative asset URLs (styles.css, ./app.js, assets/logo.svg), never root-absolute paths or external CDN resources.
Keep markup, styling and behavior separate; define named functions for filtering, validation and state transitions.
For design.interfaces, list only actual named JavaScript function/class declarations in app.js or JS modules.
Declare reusable functions with function name(...) and have Vue methods delegate to them where appropriate.
Do not invent symbols such as Vue.data, Vue.methods.save or DOM/CSS selectors: these are not declared source symbols.
Describe reactive properties, template bindings and CSS selectors in file contracts, not design.interfaces.
Use [] for an interface with no inputs or errors; still describe its output or side effect explicitly.
Make all requested buttons/forms/tables work with explicit mock data, empty/error states and responsive layout.
VISUAL DESIGN CONTRACT (apply to initial generation and preserve it in later edits):
Respect the user's reference, brand, requested density and existing styles first. Otherwise choose a coherent,
restrained visual direction suited to the actual content; a polished prototype must not look like an unstyled demo.
Choose the page composition BEFORE writing files: e.g. a focused workspace for a small tool, a clear data workspace
for administration, an editorial hero/sections for a landing page, or lanes for a board. Do not force every page
into a dashboard; avoid invented KPIs, decorative sidebars, dead navigation and features outside the requested scope.
Record a concise visual brief in README (layout, palette, type hierarchy, spacing, responsive behavior).
When planning files separately, carry shared layout classes, CSS token names, DOM IDs and interaction states in
the HTML/CSS/JS file contracts so independently generated files form one consistent interface.
In styles.css define a small :root token palette for canvas, surface, text, muted text, border, accent and states,
plus a consistent spacing/radius scale. Prefer one accent with quiet neutral surfaces, subtle borders and limited
shadows. Use intentional whitespace and alignment, not oversized blank areas, repeated floating cards or arbitrary
gradients. Light/dark/warm/editorial styles are all valid when suited to the request; do not always choose blue.
Useful starting directions (adapt them, do not copy a universal template):
- Data workspace: a 1080-1200px centered content width, a 28-32px page title with one short context line,
  a distinct toolbar and a calm table surface with horizontal separators rather than heavy nested borders.
  Consider ink #23312e, muted #53655f, accent #285a52, canvas #f4f7f5, white surfaces and small status pills.
- Editorial brand: warm paper #f7f4eb, ink #292721, muted #655f55, terracotta #90462f; expressive serif titles
  paired with system sans body. Use an asymmetric typographic hero with a meaningful self-contained CSS/inline-SVG
  composition when appropriate, section rules and numbered services rather than identical white card grids.
  A text-only hero must not consume 80-100vh with dead whitespace; keep content rhythm and first-screen information useful.
- Personal board: a centered bounded workspace, clear header hierarchy, quiet tinted lanes with white task surfaces,
  compact counts near lane titles and subtle priority badges. Avoid a redundant full-width statistics strip and
  empty oversized containers; keep movement actions secondary to the task title.
Palette examples are starting pairs, not measured guarantees for every combination; recheck muted/accent/status text
against the actual background, especially selected filters, placeholders and validation errors.
Keep CSS concise and reusable: group related selectors, avoid repetitive declarations and long explanatory comments.
When editing existing files use context.file_hashes[path] as base_sha256 and omit expected to avoid repeating the old
file in the response; include only changed files and their complete replacement, with brief summaries.
Use a local system font stack with Chinese fallbacks, a clear heading/body/label hierarchy, comfortable line height,
readable body text (normally 14-16px), secondary text normally >=12px, and tabular numbers for aligned data.
Use realistic concise content; provide one obvious primary action per section and clear secondary actions.
All visible interactive controls must work, show an explicit disabled/unavailable state, or be omitted.
Use semantic headings, explicit form labels and accessible names (including icon-only buttons). Preserve keyboard
navigation and visible :focus-visible outlines; distinguish states with text/icons as well as color. Target WCAG AA
contrast (4.5:1 normal text, 3:1 large text/UI); avoid pale gray labels on white. Do not claim measured compliance.
Secondary actions are still enabled actions: soften their background/border rather than lowering text opacity or
using disabled-looking light gray. For example use muted #53655f on white, not pale #87938f for a small action label.
Use flex/grid with min-width:0, wrapping toolbars and practical breakpoints. At 1440px, 768px and 390px avoid page-wide
horizontal overflow and clipped actions; give dense tables their own horizontal scroll container or a mobile list.
Scrollable table regions must be keyboard-focusable (tabindex=0 plus an accessible label). For Element UI, apply this
to the actual .el-table__body-wrapper after mount, not only a non-scrolling outer wrapper.
Dialogs must fit narrow screens (e.g. width:min(480px,calc(100vw - 32px))), scroll vertically when needed and retain
visible cancel/submit controls. Do not hide essential actions on mobile. Aim for 44px touch controls.
On dialog open move focus to the first field after rendering, contain Tab navigation, support Escape, and restore
focus to the opener on close; do not assume every component library/version handles all of these automatically.
Provide subtle hover/active/disabled states and short purposeful transitions; honor prefers-reduced-motion.
Use local CSS/inline SVG or available component icons; never use emoji as the main visual design system or fetch
remote fonts/images. Avoid unsafe interpolation of user-entered text into HTML.
Element UI is supported, OPTIONAL unless requested. It needs Vue 2; this is a script dependency, not a Vue project.
When using Element UI, load vendor/codespider/vue.min.js, then vendor/codespider/element-ui.js, then app.js as classic
scripts (without async); link vendor/codespider/element-ui.css before your styles. Use Vue 2 new Vue({el:'#app',data(){...},
methods:{...}}), Element UI 2 components such as el-table/el-dialog/el-form and :visible.sync. Do NOT use Vue 3 createApp,
Element Plus, setup or v-model:visible. CodeSpider supplies these pinned local library files automatically at build time;
reference them but never generate patches or design contracts for vendor/codespider files. Plain JS prototypes need no Vue.
When using Element UI, deliberately style its buttons, inputs, table headers/rows/empty states and dialogs with your
tokens in styles.css after the library stylesheet; default component styling alone is not a finished page design.
Keep hover/focus/disabled colors consistent. Element UI dialogs can be appended outside #app, so use a custom-class
with an appropriate global selector rather than only #app descendants. Use v-cloak to avoid raw template flashes.
The default Element UI bright blue (#409eff), light placeholder gray and pastel status colors are not adequate for
normal text contrast on white. Choose a darker accent for white button labels and readable muted/status/error text;
override input placeholders and table headers too. Give the surrounding page its own typography, spacing and visual
identity, not just a shadow around a default table. Use an accessible label for the filter field, not only placeholder.
Avoid localStorage, cookies, external API calls and backend dependencies in the isolated preview; use in-memory state.
Document manual behavior acceptance steps in README. Static verification checks JavaScript syntax and local asset links,
not user behavior or visual quality; include desktop/tablet/mobile, keyboard focus, empty/invalid/success states in
manual acceptance steps, and do not claim browser tests, contrast measurements or build ran unless actually observed.
Small prototypes need no speculative class/MVC hierarchy.''',
}


def detect(root):
    # Higher-priority framework plugins retain ownership of existing projects.
    return os.path.isfile(os.path.join(root, 'index.html')) and not os.path.isfile(os.path.join(root, 'package.json'))


def _command(output=''):
    source = Path(__file__).with_name('_prototype_build.py').read_text(encoding='utf-8')
    return 'python3 -c ' + shlex.quote(source) + (' ' + shlex.quote(output) if output else '')


def verification(root):
    command = _command()
    return {'commands': [], 'verify_command': command, 'setup_commands': [], 'verification_commands': [],
            'preview_supported': True}


def preview_build(root, token):
    output = '.codespider-preview-' + token
    return {'command': _command(output), 'output': output, 'label': '检查并打包 HTML / CSS / JavaScript',
            'runtime_eval': True, 'prepare': prepare_assets}


def prepare_assets(policy):
    """Install only trusted bundled files; never overwrite user modifications."""
    needs_element = False
    for current, dirs, files in os.walk(policy.root, followlinks=False):
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('vendor', 'node_modules', 'dist')
                   and not os.path.islink(os.path.join(current, d))]
        for name in files:
            if name.endswith(('.html', '.js')):
                with policy.open_file(os.path.relpath(os.path.join(current, name), policy.root)) as handle:
                    source = handle.read(2_000_000)
                needs_element |= any(marker in source for marker in ('vendor/codespider/', '<el-', 'new Vue('))
    if not needs_element:
        return
    bundle = Path(__file__).parent / 'assets' / 'prototype'
    manifest = json.loads((bundle / 'manifest.json').read_text())
    for name, entry in manifest.items():
        content = (bundle / name).read_bytes()
        if hashlib.sha256(content).hexdigest() != entry['sha256']:
            raise ValueError('原型组件资源完整性检查失败：' + name)
        relative = 'vendor/codespider/' + name
        try:
            with policy.open_file(relative, 'rb') as handle:
                existing = handle.read(len(content) + 1)
            if existing != content:
                raise ValueError('组件库保留路径已被修改，请移走自定义文件后重试：' + relative)
        except FileNotFoundError:
            with policy.open_file(relative, 'x', create_parents=True) as handle:
                handle.buffer.write(content)
