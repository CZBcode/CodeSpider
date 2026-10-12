"""Small H2-backed JSON collection store used for identity and billing data."""
import base64
import fcntl
import json
import os
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any


def find_h2_jar() -> str:
    candidates = []
    if os.environ.get("CODESPIDER_H2_JAR"):
        candidates.append(os.environ["CODESPIDER_H2_JAR"])
    candidates.extend([
        str(Path(__file__).resolve().parent / "lib" / "h2.jar"),
        "/opt/codespider-lib/h2.jar",
        str(Path.home() / ".cache" / "codespider" / "h2.jar"),
    ])
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return ""


class H2Store:
    def __init__(self, root: str, jar: str = ""):
        self.root = os.path.abspath(root)
        os.makedirs(self.root, exist_ok=True)
        self.jar = jar or find_h2_jar()
        if not self.jar:
            raise RuntimeError("H2 JDBC jar not found; set CODESPIDER_H2_JAR")
        self._lock = threading.RLock()
        self._process = None
        self._start()

    def _start(self):
        source = Path(__file__).resolve().parent / "h2bridge" / "H2Bridge.java"
        cache = Path(tempfile.gettempdir()) / ("codespider-h2-%s" % os.getuid())
        cache.mkdir(mode=0o700, exist_ok=True)
        class_file = cache / "H2Bridge.class"
        if not class_file.exists() or class_file.stat().st_mtime < source.stat().st_mtime:
            subprocess.run(["javac", "-cp", self.jar, "-d", str(cache), str(source)], check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        db_path = os.path.join(self.root, "accounts")
        self._process = subprocess.Popen(
            ["java", "-cp", "%s%s%s" % (cache, os.pathsep, self.jar), "H2Bridge", db_path],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1,
        )
        if self._process.stdout.readline().strip() != "READY":
            error = self._process.stderr.read(2000)
            self._process.kill()
            raise RuntimeError("H2 bridge failed to start: %s" % error)

    def _request(self, command: str, name: str, value: Any = None):
        with self._lock:
            if self._process is None or self._process.poll() is not None:
                self._start()
            encoded = ""
            if value is not None:
                encoded = base64.b64encode(json.dumps(value, ensure_ascii=False).encode()).decode()
            line = "\t".join([command, name] + ([encoded] if value is not None else [])) + "\n"
            try:
                self._process.stdin.write(line)
                self._process.stdin.flush()
                response = self._process.stdout.readline().rstrip("\n")
            except (BrokenPipeError, OSError) as error:
                raise RuntimeError("H2 bridge connection failed") from error
            parts = response.split("\t", 1)
            if parts[0] == "ERROR":
                raise RuntimeError(base64.b64decode(parts[1]).decode())
            return parts

    def read(self, name: str, default: Any):
        with self._lock:
            result = self._request("GET", name)
            if result[0] == "MISSING":
                return default
            return json.loads(base64.b64decode(result[1]).decode())

    def write(self, name: str, value: Any) -> None:
        with self._write_lock():
            self._request("PUT", name, value)

    def update(self, name: str, default: Any, transform) -> Any:
        with self._write_lock():
            value = transform(self.read(name, default))
            self._request("PUT", name, value)
            return value

    def append(self, name: str, value: Any) -> None:
        self.update(name, [], lambda items: items + [value])

    def _write_lock(self):
        class Lock:
            def __init__(inner):
                inner.handle = None
            def __enter__(inner):
                self._lock.acquire()
                inner.handle = open(os.path.join(self.root, "accounts.lock"), "a")
                fcntl.flock(inner.handle, fcntl.LOCK_EX)
                return inner
            def __exit__(inner, *_):
                fcntl.flock(inner.handle, fcntl.LOCK_UN)
                inner.handle.close()
                self._lock.release()
        return Lock()

    def close(self):
        with self._lock:
            if self._process and self._process.poll() is None:
                self._process.terminate()
                try:
                    self._process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self._process.kill()
            if self._process:
                for stream in (self._process.stdin, self._process.stdout, self._process.stderr):
                    if stream:
                        stream.close()
            self._process = None
