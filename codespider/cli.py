"""Download, start, and control CodeSpider from a terminal."""
import argparse
from collections import deque
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import webbrowser

from codespider.daemon import contact, saved_state


def start(directory, port, host='127.0.0.1', open_browser=False):
    current = contact(directory)
    if current:
        if current['status'] != 'running':
            raise ValueError('daemon 正在启动或停止，请稍后重试')
        if current['port'] != port or current.get('host', '127.0.0.1') != host:
            raise ValueError('已有实例使用端口 %s；请先 stop 再切换端口' % current['port'])
        print('CodeSpider 已运行：' + current['url'])
        if open_browser:
            webbrowser.open(current['url'])
        return 0
    log_dir = directory / 'logs'
    log_dir.mkdir(exist_ok=True)
    env = dict(os.environ, PYTHONUNBUFFERED='1')
    env.setdefault('CODESPIDER_AUTH_REQUIRED', '1')
    source_root = str(Path(__file__).resolve().parent.parent)
    env['PYTHONPATH'] = source_root + os.pathsep + env.get('PYTHONPATH', '')
    with open(log_dir / 'daemon.log', 'ab') as log:
        child = subprocess.Popen([sys.executable, '-m', 'codespider.daemon', '--data-dir', str(directory), '--port', str(port), '--host', host],
                                 stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                 cwd=source_root, env=env, start_new_session=True)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if child.poll() is not None:
            raise ValueError('启动失败：%s。日志：%s' % (saved_state(directory).get('error', '查看 daemon.log'), log_dir))
        current = contact(directory)
        if current and current['status'] == 'running':
            print('CodeSpider 已启动：' + current['url'])
            print('daemon PID: %s | web PID: %s | agent PID: %s' %
                  (current['pid'], current['children']['web']['pid'], current['children']['agent']['pid']))
            print('数据目录：' + str(directory))
            if open_browser:
                webbrowser.open(current['url'])
            return 0
        time.sleep(.1)
    contact(directory, 'POST', '/stop')
    try:
        child.wait(timeout=20)
    except subprocess.TimeoutExpired:
        child.terminate()
    raise ValueError('启动超时，请查看 ' + str(log_dir))


def stop(directory):
    current = contact(directory, 'POST', '/stop')
    if current is None:
        previous = saved_state(directory)
        if previous.get('status') in ('starting', 'running', 'stopping'):
            raise ValueError('daemon 无响应；为避免误杀其他进程，未根据旧 PID 发送信号。请检查日志')
        print('CodeSpider 未运行')
        return 0
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        if contact(directory) is None:
            print('CodeSpider 已停止，项目及配置已保留')
            return 0
        time.sleep(.1)
    raise ValueError('停止超时，请查看 daemon.log')


def main(argv=None):
    parser = argparse.ArgumentParser(description='CodeSpider 本地 Agent 工作台')
    sub = parser.add_subparsers(dest='command', required=True)
    for command in ('start', 'stop', 'restart', 'status', 'logs'):
        item = sub.add_parser(command)
        item.add_argument('--data-dir', default=os.environ.get('CODESPIDER_DATA_DIR', str(Path.home() / '.codespider')))
        if command in ('start', 'restart'):
            item.add_argument('--port', type=int, default=8787)
            item.add_argument('--host', default='127.0.0.1', help='Web 监听地址；服务器公开访问可用 0.0.0.0')
            item.add_argument('--open', action='store_true', help='就绪后打开浏览器')
        if command == 'status':
            item.add_argument('--json', action='store_true')
        if command == 'logs':
            item.add_argument('--component', choices=['daemon', 'web', 'agent'], default='daemon')
            item.add_argument('--lines', type=int, default=60)
    args = parser.parse_args(argv)
    directory = Path(args.data_dir).expanduser().resolve()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        if args.command == 'status':
            current = contact(directory)
            output = current or {'status': saved_state(directory).get('status', 'stopped')}
            if current is None and output['status'] in ('running', 'starting', 'stopping'):
                output['status'] = 'unreachable'
            print(json.dumps(output, ensure_ascii=False, indent=2) if args.json else
                  'CodeSpider: %s%s' % (output['status'], ' · ' + output['url'] if output.get('url') else ''))
            return 0 if current and current['status'] == 'running' else 1
        if args.command == 'logs':
            path = directory / 'logs' / (args.component + '.log')
            if not path.exists():
                print('暂无日志：' + str(path))
                return 0
            with open(path, errors='replace') as handle:
                print(''.join(deque(handle, maxlen=max(1, min(args.lines, 10000)))), end='')
            return 0
        with open(directory / 'cli.lock', 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if args.command in ('start', 'restart') and not 1 <= args.port <= 65535:
                raise ValueError('端口必须为 1–65535')
            if args.command in ('stop', 'restart'):
                stop(directory)
            if args.command in ('start', 'restart'):
                return start(directory, args.port, args.host, args.open)
        return 0
    except (OSError, ValueError) as exc:
        print('CodeSpider: ' + str(exc), file=sys.stderr)
        return 1
