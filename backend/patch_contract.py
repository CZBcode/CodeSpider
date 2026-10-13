"""Shared patch wire contract; independent of model transport and Agent execution."""
import json
import re
from pathlib import PureWindowsPath
from typing import Any, Dict, List

MAX_ITEM_CHARS = 64_000


class PatchContractError(ValueError):
    pass


class PatchContract:
    @staticmethod
    def _string(value, limit):
        if value is None: return ""
        if not isinstance(value, str):
            value = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
        return value[:limit]

    @classmethod
    def _patches(cls, items: Any) -> List[Dict[str, Any]]:
        if isinstance(items, dict): items = [items]
        if not isinstance(items, list):
            raise PatchContractError("patches must be an array")
        result = []
        for item in items:
            if not isinstance(item, dict):
                raise PatchContractError("patch must be an object")
            path = item.get("path", item.get("file", item.get("filename", "")))
            if not isinstance(path, str):
                raise PatchContractError("patch path must be a string")
            operation = item.get("operation", item.get("op", ""))
            replacement = item.get("replacement", item.get("new", None))
            expected = item.get("expected", item.get("old", None))
            content = item.get("content", None)
            if replacement is None and content is not None: replacement = content
            if not operation: operation = "apply_patch" if expected is not None or "base_sha256" in item else "write_file"
            normalized = {"path": path, "operation": cls._string(operation, 32)}
            if "base_sha256" in item:
                digest = item["base_sha256"]
                if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                    raise PatchContractError("base_sha256 must be a lowercase SHA-256 digest")
                normalized["base_sha256"] = digest
            for name, value in (("expected", expected), ("replacement", replacement)):
                if value is not None:
                    if not isinstance(value, str) or len(value) > MAX_ITEM_CHARS:
                        raise PatchContractError("patch %s must be a string of at most %d characters" % (name, MAX_ITEM_CHARS))
                    normalized[name] = value
            result.append(normalized)
        return result

    @staticmethod
    def _validate_patch(item: Dict[str, Any]) -> None:
        path = item.get("path", "")
        if not isinstance(path, str) or not path or path.startswith(("/", "\\")) or "\x00" in path:
            raise PatchContractError("patch path must be relative")
        if PureWindowsPath(path).drive or "\\" in path or any(part in ("", ".", "..") for part in path.split("/")):
            raise PatchContractError("patch path cannot escape workspace")
        if item["operation"] not in ("apply_patch", "write_file", "create"):
            raise PatchContractError("unsupported patch operation: %s" % item["operation"])
        if "base_sha256" in item and item["operation"] != "apply_patch":
            raise PatchContractError("base_sha256 is only supported for apply_patch")
        if item["operation"] == "apply_patch" and ("replacement" not in item or not any(key in item for key in ("expected", "base_sha256"))):
            raise PatchContractError("apply_patch requires expected or base_sha256, and replacement")
        if item["operation"] in ("write_file", "create") and "replacement" not in item:
            raise PatchContractError("write_file requires replacement content")
        for key in ("expected", "replacement"):
            if key in item and len(item[key]) > MAX_ITEM_CHARS:
                raise PatchContractError("patch %s is too large" % key)
