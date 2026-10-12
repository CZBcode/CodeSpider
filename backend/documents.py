from typing import Any, Dict

from code_intelligence.indexer import CodeIndexer
from backend.policy import WorkspacePolicy


def generate_workspace_document(workspace: Any, title: str = "工程说明") -> Dict[str, Any]:
    policy = WorkspacePolicy(workspace.root)
    # The cache may predate task patches or edits made outside CodeSpider.
    symbols = CodeIndexer(workspace.root, policy).build()
    lines = ["# %s" % title, "", "- 工程类型：`%s`" % workspace.project_type, "- 工程路径：`%s`" % workspace.root, "", "## 符号索引", ""]
    if not symbols:
        lines.append("当前没有可展示的类、方法、函数或组件符号。")
    else:
        for symbol in symbols[:500]:
            lines.append("- `%s` `%s`：`%s:%s`" % (symbol["kind"], symbol["name"], symbol["path"], symbol["line"]))
    content = "\n".join(lines) + "\n"
    with policy.open_file("CODESPIDER.md", "w") as handle:
        handle.write(content)
    return {"path": "CODESPIDER.md", "content": content}
