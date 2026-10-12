"""Independent execution process started by the daemon."""
import argparse
import os
import signal
import threading
from pathlib import Path

from agent_client.processes import ProcessManager
from agent_client.executor import AgentExecutor
from backend.store import JsonStore
from backend.workspaces import WorkspaceManager
from backend.tool_service import ToolService
from codespider.ipc import Server


def run(data_dir, socket_path):
    store = JsonStore(data_dir)
    processes = ProcessManager()
    tools = ToolService(store, WorkspaceManager(store), processes)

    def dispatch(method, path, body):
        if method == 'GET' and path == '/health':
            return {'ok': True, 'service': 'codespider-agent', 'pid': os.getpid()}
        if method == 'GET' and path == '/tools':
            return tools.catalog()
        if method == 'POST' and path == '/tools/call':
            return tools.call(body).to_dict()
        raise ValueError('unknown endpoint')

    server = Server(socket_path, os.environ['CODESPIDER_IPC_TOKEN'], dispatch)
    stopping = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stopping.set())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        stopping.wait()
    finally:
        server.shutdown()
        AgentExecutor.close_commands()
        processes.close()
        server.server_close()
        Path(socket_path).unlink(missing_ok=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', required=True)
    parser.add_argument('--socket', required=True)
    args = parser.parse_args()
    run(args.data_dir, args.socket)
