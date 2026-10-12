"""Supervisor for the browser control plane and the local execution agent."""
import argparse
import fcntl
import hashlib
import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from http.client import HTTPException
from pathlib import Path

from codespider.ipc import Server, request


def runtime_dir(data_dir):
    # macOS Unix sockets have a short path limit. Never place them in a workspace.
    digest = hashlib.sha256(str(Path(data_dir).resolve()).encode()).hexdigest()[:16]
    path = Path(tempfile.gettempdir()) / ('cs-%s-%s' % (os.getuid(), digest))
    path.mkdir(mode=0o700, exist_ok=True)
    if path.is_symlink() or path.stat().st_uid != os.getuid():
        raise ValueError('unsafe runtime directory')
    os.chmod(path, 0o700)
    return path


def write_state(directory, value):
    target = directory / 'daemon.json'
    temp = target.with_suffix('.tmp')
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as handle:
        json.dump(value, handle)
    os.replace(temp, target)


def saved_state(directory):
    try:
        return json.loads((directory / 'daemon.json').read_text())
    except (FileNotFoundError, ValueError):
        return {}


def contact(directory, method='GET', path='/status'):
    state = saved_state(directory)
    if not state:
        return None
    try:
        result = request(runtime_dir(directory) / 'daemon.sock', state['token'], method, path)
        if result.get('instance') == state.get('instance'):
            return result
    except (OSError, ValueError, KeyError, HTTPException):
        pass
    return None


def stop_child(child):
    if child.poll() is not None:
        return
    child.terminate()
    try:
        child.wait(timeout=8)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait(timeout=3)


def supervise(data_dir, port, host='127.0.0.1'):
    directory = Path(data_dir).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    runtime = runtime_dir(directory)
    with open(directory / 'daemon.lock', 'a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 1
        token = secrets.token_urlsafe(32)
        instance = secrets.token_hex(16)
        stopping = threading.Event()
        children = {}
        state = {'instance': instance, 'pid': os.getpid(), 'host': host, 'port': port,
                 'url': 'http://127.0.0.1:%s' % port, 'status': 'starting', 'token': token}
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda *_: stopping.set())

        def dispatch(method, path, body):
            if method == 'POST' and path == '/stop':
                stopping.set()
            elif method != 'GET' or path != '/status':
                raise ValueError('unknown endpoint')
            public = {key: value for key, value in state.items() if key != 'token'}
            public['children'] = {name: {'pid': child.pid, 'running': child.poll() is None}
                                  for name, child in children.items()}
            return public

        for name in ('daemon.sock', 'agent.sock'):
            (runtime / name).unlink(missing_ok=True)
        server = Server(runtime / 'daemon.sock', token, dispatch)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        write_state(directory, state)
        env = dict(os.environ, CODESPIDER_IPC_TOKEN=token, CODESPIDER_INSTANCE=instance,
                   PYTHONUNBUFFERED='1')
        # Also works after installation when the caller's cwd is unrelated.
        source_root = str(Path(__file__).resolve().parent.parent)
        env['PYTHONPATH'] = source_root + os.pathsep + env.get('PYTHONPATH', '')
        log_dir = directory / 'logs'
        log_dir.mkdir(exist_ok=True)

        def spawn(name, module, arguments):
            with open(log_dir / (name + '.log'), 'ab') as log:
                child = subprocess.Popen([sys.executable, '-m', module] + arguments,
                                         stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                         cwd=source_root, env=env)
            children[name] = child
            return child

        def wait_ready(check):
            deadline = time.monotonic() + 12
            while time.monotonic() < deadline and not stopping.is_set():
                if any(child.poll() is not None for child in children.values()):
                    raise RuntimeError('child exited during startup; see logs')
                try:
                    if check():
                        return
                except (OSError, ValueError, HTTPException):
                    pass
                stopping.wait(.1)
            raise RuntimeError('startup cancelled or readiness timed out')

        exit_code = 0
        try:
            # Fail before spawning anything if another app owns the requested port.
            with socket.socket() as probe:
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                probe.bind((host, port))
            spawn('agent', 'agent_client.server', ['--data-dir', str(directory), '--socket', str(runtime / 'agent.sock')])
            wait_ready(lambda: request(runtime / 'agent.sock', token, 'GET', '/health', timeout=1).get('ok'))
            spawn('web', 'backend.app', ['--host', host, '--port', str(port), '--data-dir', str(directory), '--agent-socket', str(runtime / 'agent.sock')])

            def web_ready():
                with urllib.request.urlopen(state['url'] + '/api/health', timeout=1) as response:
                    health = json.load(response)
                    return health.get('ok') and health.get('instance') == instance

            wait_ready(web_ready)
            state['status'] = 'running'
            write_state(directory, state)
            print('CodeSpider ready at ' + state['url'], flush=True)
            while not stopping.wait(.3):
                failed = [name for name, child in children.items() if child.poll() is not None]
                if failed:
                    raise RuntimeError('child exited: ' + ', '.join(failed))
        except Exception as exc:
            exit_code = 1
            state['error'] = str(exc)
            print('CodeSpider daemon failed: ' + str(exc), flush=True)
        finally:
            state['status'] = 'stopping'
            write_state(directory, state)
            # Stop accepting work and cancel Agent commands together; otherwise
            # Web may wait for a command whose Agent has not been told to stop.
            for child in reversed(list(children.values())):
                if child.poll() is None:
                    child.terminate()
            for child in reversed(list(children.values())):
                stop_child(child)
            state['status'] = 'failed' if exit_code else 'stopped'
            write_state(directory, state)
            server.shutdown()
            server.server_close()
            for name in ('daemon.sock', 'agent.sock'):
                (runtime / name).unlink(missing_ok=True)
        return exit_code


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', required=True)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--host', default='127.0.0.1')
    args = parser.parse_args()
    raise SystemExit(supervise(args.data_dir, args.port, args.host))
