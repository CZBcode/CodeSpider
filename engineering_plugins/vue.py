import json
import os
from backend.policy import WorkspacePolicy

MANIFEST = {
    'api_version': '1.0', 'id': 'plugin.vue', 'kind': 'plugin', 'name': 'Vue 工程', 'version': '1.0.0', 'priority': 20,
    'description': 'Vue 组件、组合式 API、Vite 构建与前端测试。', 'project_types': ['vue'],
    'keywords': ['vue', 'vite', 'javascript', 'typescript', 'frontend', '前端', '组件'],
    'preferred_keywords': ['vue', 'vite'],
    'intent_keywords': ['页面', '界面', '可视化', '仪表盘', '网站', '网页', '交互', '看板', 'dashboard', 'ui', 'web page'],
    'recommendation': '适合网页交互、组件化界面和可视化应用。', 'recommendation_priority': 20,
    'verify_command': 'npm run build',
    'instructions': 'Separate components, composables, services and pure domain functions. Preserve all requested data-testid values and exact initial/error states including empty string versus null. Include meaningful component/domain tests and package scripts. Reconcile dependencies from the lockfile before build.',
}

def package(root):
    try:
        with WorkspacePolicy(root).open_file('package.json') as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}

def detect(root):
    if not os.path.isfile(os.path.join(root, 'package.json')):
        return False
    value = package(root)
    deps = {**value.get('dependencies', {}), **value.get('devDependencies', {})}
    return 'vue' in deps or any(name.endswith('.vue') for name in os.listdir(root))

def verification(root):
    install = 'npm ci' if os.path.isfile(os.path.join(root, 'package-lock.json')) else 'npm install'
    value = package(root)
    deps = {**value.get('dependencies', {}), **value.get('devDependencies', {})}
    preview = 'vite' in deps and bool(value.get('scripts', {}).get('build'))
    return {'commands': ['npm run build', 'npm run dev'], 'verify_command': 'npm run build', 'preview_supported': preview,
            'setup_commands': [install + ' --ignore-scripts --no-audit --no-fund'],
            'verification_commands': ['npm test -- --run'] if package(root).get('scripts', {}).get('test') else []}


def preview_build(root, token):
    if not verification(root)['preview_supported']:
        raise ValueError('当前预览支持使用 Vite 的 Vue 工程，请配置 vite 和 build 脚本')
    # Relative output is inside the workspace sandbox; the URL base is immutable.
    output = '.codespider-preview-' + token
    return {'command': 'npm run build -- --base=/preview/%s/ --outDir=%s' % (token, output), 'output': output}
