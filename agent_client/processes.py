import os
import signal
import subprocess
import threading
import time
from typing import Any, Dict, List

from backend.policy import WorkspacePolicy


class ProcessManager:
    """Owns user-started local services without invoking a shell."""

    def __init__(self):
        self._lock = threading.RLock()
        self._processes: Dict[int, Dict[str, Any]] = {}
        self._closing = False

    def start(self, policy: WorkspacePolicy, command: str, approved: bool = False) -> Dict[str, Any]:
        risk, tokens = policy.validate_command(command, approved=approved)
        log_dir = os.path.join(policy.root, ".codespider")
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, "process.log")
        with self._lock:
            if self._closing:
                raise ValueError("agent is stopping")
            log_handle = open(log_path, "a", encoding="utf-8")
            try:
                process = subprocess.Popen(
                    tokens, cwd=policy.root, stdout=log_handle, stderr=subprocess.STDOUT,
                    env={key: value for key, value in os.environ.items() if key in ("PATH", "HOME", "LANG", "LC_ALL", "JAVA_HOME", "PYTHONPATH", "VIRTUAL_ENV", "NODE_PATH")},
                    start_new_session=True,
                )
            except Exception:
                log_handle.close()
                raise
            self._processes[process.pid] = {"pid": process.pid, "command": command, "risk": risk, "status": "running", "log": log_path, "process": process, "log_handle": log_handle, "root": policy.root}
        return self._public(self._processes[process.pid])

    def list(self, root: str = "") -> List[Dict[str, Any]]:
        normalized_root = os.path.realpath(root) if root else ""
        with self._lock:
            for item in self._processes.values():
                process = item["process"]
                if process.poll() is not None:
                    item["status"] = "stopped"
                    item["exit_code"] = process.returncode
            return [self._public(item) for item in self._processes.values() if not normalized_root or item["root"] == normalized_root]

    def stop(self, pid: int, timeout: float = 5) -> Dict[str, Any]:
        with self._lock:
            item = self._processes.get(pid)
            if not item:
                raise KeyError("process not found")
            if item["log_handle"].closed:
                return self._public(item)
            process = item["process"]
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait(timeout=5)
            # A service may leave children in its session after its parent exits.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            item["status"] = "stopped"
            item["exit_code"] = process.returncode
            item["log_handle"].close()
            return self._public(item)

    def close(self) -> None:
        """Stop services owned by this agent when the daemon shuts down."""
        with self._lock:
            self._closing = True
            # Signal all services first so their grace periods overlap.
            for item in self._processes.values():
                if item["process"].poll() is None:
                    try:
                        os.killpg(item["pid"], signal.SIGTERM)
                    except ProcessLookupError:
                        pass
            deadline = time.monotonic() + 3
            for pid in list(self._processes):
                self.stop(pid, timeout=max(0, deadline - time.monotonic()))

    @staticmethod
    def _public(item: Dict[str, Any]) -> Dict[str, Any]:
        return {key: value for key, value in item.items() if key not in ("process", "log_handle")}
