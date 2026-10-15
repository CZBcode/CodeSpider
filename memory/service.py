from typing import Any, Dict, List, Optional


class MemoryService:
    def __init__(self, store: Any):
        self.store = store

    def _items(self) -> List[Dict[str, Any]]:
        return self.store.read("memories", [])

    def add_short_term(self, task_id: str, content: Dict[str, Any]) -> Dict[str, Any]:
        item = {"scope": "task", "scope_id": task_id, "type": "short_term", "content": content}
        self.store.append("memories", item)
        return item

    def add_project(self, workspace_id: str, content: Dict[str, Any]) -> Dict[str, Any]:
        item = {"scope": "workspace", "scope_id": workspace_id, "type": "project", "content": content}
        self.store.append("memories", item)
        return item

    def set_preferences(self, user_id: str, content: Dict[str, Any]) -> Dict[str, Any]:
        item = {"scope": "user", "scope_id": user_id, "type": "preference", "content": content}
        self.store.update("memories", [], lambda items: [old for old in items if not (old["scope"] == "user" and old["scope_id"] == user_id and old["type"] == "preference")] + [item])
        return item

    def add_skill(self, scope_id: str, name: str, body: str, trigger: str = "") -> Dict[str, Any]:
        item = {"scope": "workspace", "scope_id": scope_id, "type": "skill", "name": name, "trigger": trigger, "body": body}
        self.store.append("skills", item)
        return item

    def search(self, scope_id: str, query: str, include_global: bool = True) -> List[Dict[str, Any]]:
        query_words = [word.lower() for word in query.split() if word.strip()]
        scopes = (scope_id, "global") if include_global else (scope_id,)
        candidates = [item for item in self._items() if item["scope_id"] in scopes]
        candidates += [item for item in self.store.read("skills", []) if item.get("scope_id") in scopes]
        def score(item: Dict[str, Any]) -> int:
            text = str(item).lower()
            return sum(1 for word in query_words if word in text)
        return sorted([item for item in candidates if score(item) > 0], key=score, reverse=True)
