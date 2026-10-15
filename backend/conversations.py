"""Durable, account-scoped conversation turns; execution remains in TaskManager."""
from backend.models import new_id, now_iso
from contextlib import contextmanager
import threading
import re
from datetime import datetime


CONTEXT_TURNS = 15
SUMMARY_CHARS = 12000


FREE_REPLY = "我可以先帮你梳理这个问题。选择一个具体工程后，我还能继续读取代码、生成补丁并运行验证。"


class ConversationService:
    def __init__(self, store, task_store):
        self.store = store
        self.task_store = task_store
        self.active = set()
        self._guard = threading.Lock()
        self._locks = {}

    @contextmanager
    def serial(self, user_id, workspace_id):
        key = (user_id, workspace_id)
        with self._guard:
            lock = self._locks.setdefault(key, threading.RLock())
        with lock:
            yield

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

    def set_intent(self, turn_id, intent):
        self.store.update('conversation_turns', [], lambda items: [dict(t, intent=intent)
            if t['id'] == turn_id else t for t in items])

    def finish(self, turn_id, error="", reply=""):
        finished_at = now_iso()
        self.store.update("conversation_turns", [], lambda items: [
            dict(item, status="failed" if error else "completed", error=error, reply=reply,
                 finished_at=item.get("finished_at") or finished_at)
            if item["id"] == turn_id else item for item in items])
        self.active.discard(turn_id)
        turn = next((t for t in self.store.read("conversation_turns", []) if t["id"] == turn_id), None)
        if turn:
            self.context(turn["user_id"], turn["workspace_id"])
            return self.timing(turn)

    @staticmethod
    def timing(turn, task=None):
        started = turn.get("created_at") or (task or {}).get("created_at", "")
        response_finished = turn.get("finished_at") or (task or {}).get("created_at", "")
        finished = ((task.get("updated_at", "") if task.get("status") in ("succeeded", "failed", "cancelled") else "")
                    if task else turn.get("finished_at", ""))
        def duration(end):
            try:
                return max(0, round((datetime.fromisoformat(end) - datetime.fromisoformat(started)).total_seconds() * 1000))
            except (TypeError, ValueError):
                return None
        return {"started_at": started, "response_finished_at": response_finished,
                "finished_at": finished, "duration_ms": duration(finished),
                "generation_duration_ms": duration(response_finished)}

    def task_payload(self, task):
        turn = next((t for t in self.store.read("conversation_turns", [])
                     if t["id"] == task.get("conversation_turn_id") and t["user_id"] == task.get("owner_id")
                     and t["workspace_id"] == task["workspace_id"]), {})
        return dict(task, timing=self.timing(turn, task), intent=turn.get('intent'))

    def history(self, user_id, workspace_id, include_events=True):
        turns = [dict(t) for t in self.store.read("conversation_turns", [])
                 if t["user_id"] == user_id and t["workspace_id"] == workspace_id]
        tasks = {t.get("conversation_turn_id"): t for t in self.task_store.read("tasks", [])
                 if t.get("owner_id") == user_id and t["workspace_id"] == workspace_id}
        task_ids = {tasks[t["id"]]["id"] for t in turns if t["id"] in tasks}
        events = {}
        for event in self.task_store.read("events", []) if include_events else []:
            if event["task_id"] in task_ids:
                events.setdefault(event["task_id"], []).append(event)
        generation_ids = {j.get('turn_id'):j['id'] for j in self.task_store.read('generations', [])
                          if j.get('owner_id')==user_id and j.get('workspace_id')==workspace_id}
        for turn in turns:
            if turn['id'] in generation_ids:
                turn['generation_id'] = generation_ids[turn['id']]
            turn.pop("user_id", None)
            task = tasks.get(turn["id"])
            if task:
                turn.update(task=dict(task, timing=self.timing(turn, task), intent=turn.get('intent')), status=task["status"], events=events.get(task["id"], []))
            elif turn["status"] == "generating" and turn["id"] not in self.active:
                turn.update(status="interrupted", error="生成请求因服务重启中断，请重新发送需求。")
            turn["timing"] = self.timing(turn, task)
        return turns

    @staticmethod
    def _excerpt(text, limit):
        text = re.sub(r"\s+", " ", str(text or "")).strip()
        if len(text) <= limit:
            return text
        # Preserve both the initial requirements and the final corrections.
        head = limit * 2 // 3
        return text[:head] + " … " + text[-(limit - head - 3):]

    @staticmethod
    def _context_turn(turn):
        task = turn.get("task") or {}
        return {"id": turn["id"], "goal": turn["goal"], "reply": turn.get("reply", ""),
                "status": turn["status"], "error": task.get("error") or turn.get("error", ""),
                "proposed_files": [p.get("path", "") for p in task.get("patches", [])]}

    def context(self, user_id, workspace_id):
        """Bound model context without deleting the durable UI transcript.

        Extractive summaries cost no model credits. Rebuilding from source also
        reflects late approval/failure of an already archived task accurately.
        """
        with self.serial(user_id, workspace_id):
            turns = self.history(user_id, workspace_id, include_events=False)
            older, recent = turns[:-CONTEXT_TURNS], turns[-CONTEXT_TURNS:]
            entries = []
            for turn in older:
                item = self._context_turn(turn)
                entries.append({"id": item["id"], "status": item["status"],
                    "requirement": self._excerpt(item["goal"], 400),
                    "response": self._excerpt(item["reply"], 260),
                    "error": self._excerpt(item["error"], 200),
                    "proposed_files": item["proposed_files"][:12]})
            # All per-turn summaries persist. Limit the prompt separately; show
            # the first requirements and newest archived decisions on long chats.
            lines = ["轮次 %s | 状态 %s | 需求：%s | 回复/方案：%s | 错误：%s | 涉及文件（不代表已落盘）：%s" %
                     (i + 1, e["status"], e["requirement"], e["response"], e["error"],
                      self._excerpt(", ".join(e["proposed_files"]), 240)) for i, e in enumerate(entries)]
            summary = "\n".join(lines)
            if len(summary) > SUMMARY_CHARS:
                first = lines[0]
                tail, used = [], len(first) + 180
                for line in reversed(lines[1:]):
                    if used + len(line) + 1 > SUMMARY_CHARS:
                        break
                    tail.insert(0, line)
                    used += len(line) + 1
                omitted = len(lines) - len(tail) - 1
                summary = first + "\n[中间 %s 轮摘要未放入本次上下文，完整记录仍保留；信息不足时请询问用户。]\n" % omitted + "\n".join(tail)
            archive = {"user_id": user_id, "workspace_id": workspace_id, "entries": entries,
                       "summary": summary, "archived_count": len(older), "method": "local_extractive_v1"}
            if older:
                self.store.update("conversation_archives", [], lambda items:
                    [a for a in items if (a["user_id"], a["workspace_id"]) != (user_id, workspace_id)] + [archive])
            return {"window_size": CONTEXT_TURNS, "archived_count": len(older), "summary": summary,
                    "recent_turns": [self._context_turn(t) for t in recent]}
