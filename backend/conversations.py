"""Durable, account-scoped conversation turns; execution remains in TaskManager."""
from backend.models import new_id, now_iso


FREE_REPLY = "我可以先帮你梳理这个问题。选择一个具体工程后，我还能继续读取代码、生成补丁并运行验证。"


class ConversationService:
    def __init__(self, store, task_store):
        self.store = store
        self.task_store = task_store
        self.active = set()

    def begin(self, user_id, workspace_id, goal):
        if not isinstance(goal, str) or not goal.strip() or len(goal) > 32000:
            raise ValueError("消息长度必须在 1 到 32000 字符之间")
        turn = {"id": new_id("turn"), "user_id": user_id, "workspace_id": workspace_id,
                "goal": goal.strip(), "status": "generating", "reply": "", "error": "",
                "created_at": now_iso()}
        self.active.add(turn["id"])
        try:
            self.store.append("conversation_turns", turn)
        except Exception:
            self.active.discard(turn["id"])
            raise
        return turn["id"]

    def finish(self, turn_id, error="", reply=""):
        self.store.update("conversation_turns", [], lambda items: [
            dict(item, status="failed" if error else "completed", error=error, reply=reply)
            if item["id"] == turn_id else item for item in items])
        self.active.discard(turn_id)

    def history(self, user_id, workspace_id):
        turns = [dict(t) for t in self.store.read("conversation_turns", [])
                 if t["user_id"] == user_id and t["workspace_id"] == workspace_id]
        tasks = {t.get("conversation_turn_id"): t for t in self.task_store.read("tasks", [])
                 if t.get("owner_id") == user_id and t["workspace_id"] == workspace_id}
        task_ids = {tasks[t["id"]]["id"] for t in turns if t["id"] in tasks}
        events = {}
        for event in self.task_store.read("events", []):
            if event["task_id"] in task_ids:
                events.setdefault(event["task_id"], []).append(event)
        for turn in turns:
            turn.pop("user_id", None)
            task = tasks.get(turn["id"])
            if task:
                turn.update(task=task, status=task["status"], events=events.get(task["id"], []))
            elif turn["status"] == "generating" and turn["id"] not in self.active:
                turn.update(status="interrupted", error="生成请求因服务重启中断，请重新发送需求。")
        return turns
