import ast
import os
import re
from typing import Any, Dict, List

from backend.policy import PolicyError, WorkspacePolicy


class CodeIndexer:
    def __init__(self, root: str, policy: WorkspacePolicy):
        self.root = root
        self.policy = policy

    def build(self) -> List[Dict[str, Any]]:
        symbols: List[Dict[str, Any]] = []
        for current, dirs, files in os.walk(self.root):
            relative_dir = os.path.relpath(current, self.root)
            dirs[:] = [name for name in dirs if not self.policy.is_ignored(os.path.join(relative_dir, name))]
            for filename in files:
                relative = os.path.normpath(os.path.join(relative_dir, filename))
                if self.policy.is_ignored(relative):
                    continue
                path = os.path.join(current, filename)
                if filename.endswith(".py"):
                    symbols.extend(self._python(path, relative))
                elif filename.endswith(".java"):
                    symbols.extend(self._regex(path, relative, "java"))
                elif filename.endswith(".vue") or filename.endswith((".ts", ".js")):
                    symbols.extend(self._regex(path, relative, "vue"))
        self._save(symbols)
        return symbols

    def _python(self, path: str, relative: str) -> List[Dict[str, Any]]:
        try:
            with self.policy.open_file(relative, "r") as handle:
                tree = ast.parse(handle.read(), filename=path)
        except (OSError, SyntaxError, UnicodeDecodeError, PolicyError):
            return []
        result = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                result.append({"path": relative, "name": node.name, "kind": "class" if isinstance(node, ast.ClassDef) else "function", "line": node.lineno, "end_line": getattr(node, "end_lineno", node.lineno), "language": "python"})
        return result

    def _regex(self, path: str, relative: str, language: str) -> List[Dict[str, Any]]:
        try:
            with self.policy.open_file(relative, "r") as handle:
                lines = handle.readlines()
        except (OSError, UnicodeDecodeError, PolicyError):
            return []
        result = []
        patterns = [
            (r"\bclass\s+(\w+)", "class"),
            (r"\b(?:public|private|protected)?\s*(?:static\s+)?[\w<>\[\]]+\s+(\w+)\s*\(", "method"),
            (r"\b(?:function|const|let|var)\s+(\w+)", "function"),
            (r"\b(?:def)\s+(\w+)", "function"),
        ]
        for line_number, line in enumerate(lines, 1):
            for pattern, kind in patterns:
                for match in re.finditer(pattern, line):
                    result.append({"path": relative, "name": match.group(1), "kind": kind, "line": line_number, "end_line": line_number, "language": language})
        return result

    def _save(self, symbols: List[Dict[str, Any]]) -> None:
        with self.policy.open_file(".codespider/symbols.json", "w", create_parents=True) as handle:
            import json
            json.dump(symbols, handle, ensure_ascii=False, indent=2)
