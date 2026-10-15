import os
from engineering_plugins.support import project_files

MANIFEST = {
    'api_version': '1.0', 'id': 'plugin.python', 'kind': 'plugin', 'name': 'Python 工程', 'version': '1.0.0', 'priority': 10,
    'description': 'Python 模块生成、AST 理解、语法检查及单元测试。', 'project_types': ['python'],
    'keywords': ['python', 'pytest', 'unittest', 'fastapi', 'django', '数据分析', '爬虫'],
    'preferred_keywords': ['python', 'fastapi', 'django'],
    'intent_keywords': ['脚本', '自动化', '批处理', '数据处理', '统计', '抓取', '机器学习', '算法', 'script', 'automation'],
    'recommendation': '适合自动化、数据处理和独立算法服务。', 'recommendation_priority': 10,
    'verify_command': 'python3 -m compileall -q .',
    'instructions': 'Separate domain functions, services and I/O adapters. Preserve imports and public interfaces. Generate meaningful discoverable unittest tests. Run syntax checks and the available tests; never report zero tests as passed.',
}

def detect(root):
    return bool(set(os.listdir(root)) & {'pyproject.toml', 'requirements.txt', 'setup.py', 'manage.py'}) or any(p.endswith('.py') for p in project_files(root))

def verification(root):
    has_dir = os.path.isdir(os.path.join(root, 'tests'))
    has_tests = has_dir or any(p.startswith('test') and p.endswith('.py') for p in project_files(root))
    tests = ['python3 -m unittest discover -s tests -v' if has_dir else 'python3 -m unittest discover -v'] if has_tests else []
    return {'commands': [MANIFEST['verify_command'], 'pytest'], 'verify_command': MANIFEST['verify_command'], 'verification_commands': tests, 'setup_commands': []}
