import json
import os
import threading
import fcntl
import tempfile
from contextlib import contextmanager
from typing import Any, Dict, List, Optional


class JsonStore:
    """Small atomic JSON store for the local MVP.

    The store is intentionally replaceable by PostgreSQL later. Writes use a
    temporary file and os.replace so a process interruption does not leave a
    partially written database.
    """

    def __init__(self, root: str):
        self.root = os.path.abspath(root)
        os.makedirs(self.root, exist_ok=True)
        self._lock = threading.RLock()

    def _path(self, name: str) -> str:
        return os.path.join(self.root, name + ".json")

    def read(self, name: str, default: Any) -> Any:
        with self._lock:
            try:
                with open(self._path(name), "r", encoding="utf-8") as handle:
                    return json.load(handle)
            except (FileNotFoundError, json.JSONDecodeError):
                return default

    def write(self, name: str, value: Any) -> None:
        with self._write_lock():
            self._write(name, value)

    @contextmanager
    def _write_lock(self):
        with self._lock, open(os.path.join(self.root, "store.lock"), "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _write(self, name: str, value: Any) -> None:
        target = self._path(name)
        fd, temp = tempfile.mkstemp(prefix=name + ".", suffix=".tmp", dir=self.root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(value, handle, ensure_ascii=False, indent=2)
            os.replace(temp, target)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)

    def update(self, name: str, default: Any, transform) -> Any:
        """Atomic read-modify-write across Web and Agent processes."""
        with self._write_lock():
            value = transform(self.read(name, default))
            self._write(name, value)
            return value

    def append(self, name: str, value: Any) -> None:
        self.update(name, [], lambda items: items + [value])
