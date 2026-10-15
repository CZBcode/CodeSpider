"""Reusable functions exposed through the same permission-checked tool API."""
from copy import deepcopy


def entry(identifier, name, description, tool, action, fields=None, keywords=None):
    fields = fields or {}
    return {'id': identifier, 'kind': 'function', 'name': name, 'version': '1.0.0',
            'description': description, 'tool': tool, 'action': action, 'keywords': keywords or [],
            'input_schema': {'type': 'object', 'properties': {key: {'type': value} for key, value in fields.items()},
                             'required': list(fields), 'additionalProperties': False}}


FUNCTIONS = [
    entry('function.preview.build', '构建并预览前端', '按插件检查并构建 HTML 原型或 Vue/Vite 工程，成功后更新隔离预览；失败保留上次版本。', 'preview', 'build', keywords=['预览','build','vue','原型','html','部署']),
    entry('function.preview.status', '查看前端构建状态', '读取构建状态、日志和当前预览链接。', 'preview', 'status', keywords=['预览','构建状态']),
    entry('function.preview.deploy', '发布已构建预览', '发布已验证且源码未变化的构建版本。', 'preview', 'deploy', {'build_id':'string'}, ['发布','预览']),
    entry('function.workspace.read', '读取工程文件', '读取当前用户工程文件，无需额外确认。', 'workspace', 'read_file', {'path':'string'}, ['读取','read','文件']),
    entry('function.workspace.patch', '应用代码补丁', '核对原文件全文后应用补丁；必须审批。', 'workspace', 'apply_patch', {'path':'string','expected':'string','replacement':'string'}, ['修改','patch','重构']),
    entry('function.code.ast', 'AST / 符号索引', '提取工程函数、类和组件符号。', 'code', 'symbols', keywords=['结构','ast','函数','类','模块']),
    entry('function.code.review', '设计契约审查', '检查工程职责边界、依赖和设计契约。', 'code', 'design_review', keywords=['设计','架构','职责','review']),
    entry('function.process.verify', '执行验证命令', '在项目安全策略下执行构建或测试命令。', 'process', 'run', {'command':'string'}, ['测试','test','验证','构建','build']),
    entry('function.document.generate', '生成工程文档', '根据符号索引生成 CODESPIDER.md。', 'document', 'generate', keywords=['文档','document','说明']),
]


def descriptors():
    return deepcopy(FUNCTIONS)


def validate_input(item, arguments):
    if not isinstance(arguments, dict):
        raise ValueError('function input must be an object')
    schema = item['input_schema']
    if set(arguments) - set(schema['properties']):
        raise ValueError('function input contains unknown fields')
    for key in schema['required']:
        if key not in arguments or not isinstance(arguments[key], str):
            raise ValueError('function input requires string: ' + key)
