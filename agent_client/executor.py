import os
import subprocess
import signal
import threading
import time
from typing import Any, Dict, List, Optional

from backend.policy import ApprovalRequired, PolicyError, WorkspacePolicy


class ExecutionError(RuntimeError):
    pass


class AgentExecutor:
    _commands = set()
    _command_lock = threading.RLock()
    _closing = False

    def __init__(self, policy: WorkspacePolicy):
        self.policy = policy

    def read_file(self, relative_path: str, max_bytes: int = 512 * 1024, approved: bool = False) -> str:
        path = self.policy.validate_read(relative_path, approved=approved)
        if not os.path.isfile(path):
            raise ExecutionError("file not found: %s" % relative_path)
        with self.policy.open_file(relative_path, "rb") as handle:
            data = handle.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise ExecutionError("file is larger than read limit")
        return data.decode("utf-8")

    def search(self, query: str, limit: int = 100, approved: bool = False) -> List[Dict[str, Any]]:
        if not query:
            return []
        if self.policy.mode == "safe" and not approved:
            raise ApprovalRequired("code_search", "安全执行模式要求确认搜索工程文件内容", "confirm")
        results = []
        for current, dirs, files in os.walk(self.policy.root):
            relative_dir = os.path.relpath(current, self.policy.root)
            dirs[:] = [name for name in dirs if not self.policy.is_ignored(os.path.join(relative_dir, name))]
            for filename in files:
                relative = os.path.normpath(os.path.join(relative_dir, filename))
                if self.policy.is_ignored(relative):
                    continue
                try:
                    with self.policy.open_file(relative, "r") as handle:
                        for line_number, line in enumerate(handle, 1):
                            if query.lower() in line.lower():
                                results.append({"path": relative, "line": line_number, "text": line.rstrip()})
                                if len(results) >= limit:
                                    return results
                except (OSError, UnicodeDecodeError, PolicyError):
                    continue
        return results

    def write_file(self, relative_path: str, content: str, approved: bool = False) -> Dict[str, Any]:
        if type(approved) is not bool:
            raise PolicyError("approved must be a boolean")
        if not approved:
            raise PolicyError("file write requires explicit approval")
        with self.policy.open_file(relative_path, "w", create_parents=True) as handle:
            handle.write(content)
        return {"path": relative_path, "bytes": len(content.encode("utf-8"))}

    def apply_patch(self, relative_path: str, expected: str, replacement: str, approved: bool = False) -> Dict[str, Any]:
        if type(approved) is not bool or not approved:
            raise PolicyError("file patch requires explicit boolean approval")
        with self.policy.open_file(relative_path, "r+") as handle:
            current = handle.read(512 * 1024 + 1)
            if len(current.encode("utf-8")) > 512 * 1024:
                raise ExecutionError("file is larger than read limit")
            if current != expected:
                raise ExecutionError("file changed since patch was prepared")
            handle.seek(0)
            handle.write(replacement)
            handle.truncate()
        return {"path": relative_path, "bytes": len(replacement.encode("utf-8"))}

    def run_command(self, command: str, timeout: int = 60, approved: bool = False, cancel_event=None) -> Dict[str, Any]:
        risk, tokens = self.policy.validate_command(command, approved=approved)
        if not 1 <= timeout <= 300:
            raise ValueError("command timeout must be between 1 and 300 seconds")
        with self._command_lock:
            if self._closing:
                raise ExecutionError("agent is stopping")
            if cancel_event is not None and cancel_event.is_set():
                raise ExecutionError("task cancelled")
            process = subprocess.Popen(tokens, cwd=self.policy.root, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                env=self._safe_env(), start_new_session=True)
            self._commands.add(process)
        try:
            deadline = time.monotonic() + timeout
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    self._kill_command(process)
                    process.communicate()
                    raise ExecutionError("task cancelled")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(tokens, timeout)
                try:
                    output, _ = process.communicate(timeout=min(remaining, .1))
                    break
                except subprocess.TimeoutExpired:
                    continue
        except subprocess.TimeoutExpired as exc:
            self._kill_command(process)
            process.communicate()
            raise ExecutionError("command timed out after %ss: %s" % (timeout, command)) from exc
        finally:
            with self._command_lock:
                self._commands.discard(process)
        return {"risk": risk, "output": output[-100_000:], "exit_code": process.returncode}

    @staticmethod
    def _kill_command(process):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    @classmethod
    def close_commands(cls):
        with cls._command_lock:
            cls._closing = True
            for process in cls._commands:
                cls._kill_command(process)

    def _safe_env(self) -> Dict[str, str]:
        allowed = ("PATH", "HOME", "LANG", "LC_ALL", "JAVA_HOME", "PYTHONPATH", "VIRTUAL_ENV", "NODE_PATH")
        return {key: value for key, value in os.environ.items() if key in allowed}
