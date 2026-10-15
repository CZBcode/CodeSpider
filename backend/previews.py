"""Agent-owned builds and immutable, isolated static preview releases."""
import hashlib
import os
import re
import secrets
import shutil
import stat
import threading
from pathlib import Path

from agent_client.executor import AgentExecutor, ExecutionError
from backend.models import now_iso
from backend.policy import WorkspacePolicy
from engineering_plugins.registry import by_id, detect


ACTIVE = ('queued', 'installing', 'building')
MAX_BYTES = 64 * 1024 * 1024
MAX_FILES = 4000


def source_digest(root):
    """Detect edits while building and between build and publication."""
    digest = hashlib.sha256()
    count = total = 0
    policy = WorkspacePolicy(root)
    for current, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not d.startswith('.') and d not in
                         ('node_modules', 'dist', 'build', 'coverage', '__pycache__') and
                         not os.path.islink(os.path.join(current, d)))
        for name in sorted(files):
            if name in ('.DS_Store', 'CODESPIDER.md'):
                continue
            relative = os.path.relpath(os.path.join(current, name), root)
            with policy.open_file(relative, 'rb') as handle:
                content = handle.read(MAX_BYTES + 1)
            total += len(content); count += 1
            if total > MAX_BYTES or count > MAX_FILES:
                raise ValueError('工程超过预览构建检查上限（64 MB / 4000 文件，不含依赖和产物）')
            digest.update(relative.encode()); digest.update(b'\0'); digest.update(content)
    return digest.hexdigest()


class PreviewService:
    def __init__(self, store, workspaces, market):
        self.store, self.workspaces, self.market = store, workspaces, market
        self.lock = threading.RLock()
        self.workers = {}
        self.root = Path(store.root) / 'previews'
        self.root.mkdir(exist_ok=True)
        def recover(records):
            for record in records.values():
                job = record.get('job', {})
                if job.get('status') in ACTIVE:
                    job.update(status='failed', error='Agent 已重启，请重新构建；上次成功预览已保留。', finished_at=now_iso())
            return records
        records = store.update('previews', {}, recover)
        retained = {item['id'] for record in records.values() for item in
                    (record.get('current'), record.get('previous'), record.get('job')) if item}
        for directory in self.root.iterdir():
            if re.fullmatch(r'[a-f0-9]{48}', directory.name) and directory.name not in retained:
                shutil.rmtree(directory, ignore_errors=True)

    def status(self, workspace):
        detection = detect(workspace.root)
        record = self.store.read('previews', {}).get(workspace.id, {})
        if record.get('root') != workspace.root or record.get('owner_id') != workspace.owner_id:
            record = {}
        return dict(record, supported=bool(detection.get('preview_supported')))

    def _update_job(self, workspace_id, build_id, **values):
        def update(records):
            job = records[workspace_id]['job']
            if job['id'] != build_id:
                raise ValueError('构建版本已失效，请重新构建')
            job.update(values)
            return records
        return self.store.update('previews', {}, update)[workspace_id]['job']

    def build(self, request, cancel_event=None):
        workspace = self.workspaces.get(request.workspace_id, request.task_id, request.owner_id)
        detected = detect(workspace.root)
        plugin = by_id(detected.get('plugin_id'))
        if not detected.get('preview_supported') or not callable(getattr(plugin, 'preview_build', None)):
            raise ValueError('此工程暂不支持静态预览；请选择前端原型插件，或为 Vue 工程配置 Vite 和 build 脚本')
        self.market.require(detected['plugin_id'], request.owner_id, 'plugin')
        token = secrets.token_hex(24)
        spec = plugin.preview_build(workspace.root, token)
        setup = detected.get('setup_commands', []) if not request.task_id else []
        policy = self.workspaces.policy(workspace.id, request.task_id)
        # Validate all commands before scheduling anything; preserve allowlists.
        for command in setup + [spec['command']]:
            policy.validate_command(command, approved=request.approved)
        with self.lock:
            if len(self.workers) >= 4:
                raise ValueError('构建服务繁忙，请稍后重试')
            current = self.status(workspace)
            if current.get('job', {}).get('status') in ACTIVE or current.get('job', {}).get('id') in self.workers:
                raise ValueError('当前工程已有构建正在执行，请等待完成')
            job = {'id': token, 'task_id': request.task_id, 'status': 'queued', 'created_at': now_iso(),
                   'log': '', 'error': '', 'command': spec.get('label', spec['command']),
                   'runtime_eval': spec.get('runtime_eval') is True}
            record = {'root': workspace.root, 'owner_id': workspace.owner_id, 'job': job,
                      'current': current.get('current'), 'previous': current.get('previous')}
            self.store.update('previews', {}, lambda records: dict(records, **{workspace.id: record}))
            obsolete = (current.get('job') or {}).get('id')
            retained = {(current.get(key) or {}).get('id') for key in ('current', 'previous')}
            if obsolete and obsolete not in retained:
                shutil.rmtree(self.root / obsolete, ignore_errors=True)
            event = cancel_event or threading.Event()
            worker = threading.Thread(target=self._run, args=(workspace, request, spec, setup, token, event), daemon=True)
            self.workers[token] = (worker, event, request.task_id)
            worker.start()
            return {'job': dict(job)}

    def _run(self, workspace, request, spec, setup, token, cancelled):
        destination = self.root / token
        try:
            with self.workspaces.lease(workspace.id):
                policy = self.workspaces.policy(workspace.id, request.task_id)
                executor = AgentExecutor(policy)
                logs = ''
                for command in setup:
                    self._update_job(workspace.id, token, status='installing')
                    result = executor.run_command(command, 300, request.approved, cancelled)
                    logs = (logs + '\n$ ' + command + '\n' + result['output'])[-24000:]
                    self._update_job(workspace.id, token, log=logs)
                    if result['exit_code']:
                        raise ExecutionError('依赖安装失败，请展开构建日志查看原因')
                if cancelled.is_set():
                    raise ExecutionError('构建已取消')
                if spec.get('prepare'):
                    spec['prepare'](policy)
                before = source_digest(workspace.root)
                self._update_job(workspace.id, token, status='building')
                result = executor.run_command(spec['command'], 180, request.approved, cancelled)
                logs = (logs + '\n$ ' + spec.get('label', spec['command']) + '\n' + result['output'])[-24000:]
                self._update_job(workspace.id, token, log=logs)
                if result['exit_code']:
                    raise ExecutionError('前端编译失败，请修复代码后重试；上次成功预览已保留')
                if cancelled.is_set():
                    raise ExecutionError('构建已取消')
                if before != source_digest(workspace.root):
                    raise ValueError('构建期间源码发生变化，请重新构建')
                self._copy_output(policy, spec['output'], destination)
                if cancelled.is_set():
                    raise ExecutionError('构建已取消')
                self._update_job(workspace.id, token, status='ready', digest=before, finished_at=now_iso())
                # Manual builds publish in the Agent, independent of browser lifetime.
                if not request.task_id:
                    self.deploy(workspace, token, cancelled)
        except Exception as exc:
            shutil.rmtree(destination, ignore_errors=True)
            self._update_job(workspace.id, token, status='cancelled' if cancelled.is_set() else 'failed',
                             error=str(exc)[:2000], finished_at=now_iso())
        finally:
            output = Path(workspace.root) / spec['output']
            if output.is_symlink():
                output.unlink()
            else:
                shutil.rmtree(output, ignore_errors=True)
            with self.lock:
                self.workers.pop(token, None)

    @staticmethod
    def _copy_output(policy, relative, destination):
        output = Path(policy.root) / relative
        if output.is_symlink() or not output.is_dir():
            raise ValueError('构建未生成有效静态产物目录')
        destination.mkdir(mode=0o700)
        total = count = 0
        for current, dirs, files in os.walk(output, followlinks=False):
            for name in dirs + files:
                source = Path(current) / name
                if source.is_symlink():
                    raise ValueError('预览产物不能包含符号链接')
            for name in files:
                source = Path(current) / name
                if not stat.S_ISREG(source.lstat().st_mode):
                    raise ValueError('预览产物必须是普通文件')
                suffix = source.relative_to(output)
                if any(part.startswith('.') for part in suffix.parts) or source.suffix == '.map':
                    continue
                with policy.open_file(str(source.relative_to(policy.root)), 'rb') as handle:
                    if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                        raise ValueError('预览产物必须是普通文件')
                    content = handle.read(MAX_BYTES + 1)
                count += 1; total += len(content)
                if count > MAX_FILES or total > MAX_BYTES:
                    raise ValueError('预览产物超过 64 MB / 4000 文件限制')
                target = destination / suffix
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
        if not (destination / 'index.html').is_file():
            raise ValueError('构建未生成 index.html，无法发布预览')

    def deploy(self, workspace, build_id, cancelled=None):
        with self.lock:
            actual = self.workspaces.get(workspace.id, owner_id=workspace.owner_id)
            if actual.root != workspace.root:
                raise ValueError('工程位置已变化，请重新构建')
            record = self.status(workspace)
            job = record.get('job', {})
            if job.get('id') != build_id or job.get('status') not in ('ready', 'published'):
                raise ValueError('构建尚未成功或版本已过期')
            if job.get('status') == 'published':
                return record['current']
            if cancelled is not None and cancelled.is_set():
                raise ExecutionError('构建已取消')
            if job['digest'] != source_digest(workspace.root):
                raise ValueError('构建后源码已变化，请重新构建后发布')
            current = {'id': build_id, 'url': '/preview/' + build_id + '/', 'published_at': now_iso(),
                       'runtime_eval': job.get('runtime_eval') is True}
            def publish(records):
                record = records[workspace.id]
                if record['job']['id'] != build_id:
                    raise ValueError('构建版本已失效')
                if cancelled is not None and cancelled.is_set():
                    raise ExecutionError('构建已取消')
                record['previous'] = record.get('current')
                record['current'] = current
                record['job']['status'] = 'published'
                return records
            self.store.update('previews', {}, publish)
            retired = (record.get('previous') or {}).get('id')
            if retired and retired != build_id:
                shutil.rmtree(self.root / retired, ignore_errors=True)
            return current

    def cancel(self, task_id='', build_id=''):
        with self.lock:
            workers = [v for key, v in self.workers.items() if (build_id and key == build_id) or (task_id and v[2] == task_id)]
            for _, event, _ in workers:
                event.set()
        for worker, _, _ in workers:
            worker.join(10)
        return {'cancelled': bool(workers)}


def preview_asset(store, workspaces, token, relative, include_policy=False):
    """A random capability grants read-only access to just the published build."""
    if not re.fullmatch(r'[a-f0-9]{48}', token):
        raise FileNotFoundError('预览不存在')
    records = store.read('previews', {})
    matched = next(((key, record) for key, record in records.items()
                    if (record.get('current') or {}).get('id') == token), None)
    if not matched:
        raise FileNotFoundError('预览不存在或已更新')
    workspace_id, record = matched
    workspace = workspaces.get(workspace_id, owner_id=record['owner_id'])
    if workspace.root != record['root']:
        raise FileNotFoundError('工程位置已改变，请重新构建')
    if '\\' in relative or any(p.startswith('.') for p in relative.split('/') if p):
        raise FileNotFoundError('无效预览路径')
    policy = WorkspacePolicy(str(Path(store.root) / 'previews' / token))
    path = relative or 'index.html'
    def result(path, content):
        value = (path, content)
        return value + ({'runtime_eval': record['current'].get('runtime_eval') is True},) if include_policy else value
    try:
        with policy.open_file(path, 'rb') as handle:
            return result(path, handle.read(MAX_BYTES + 1))
    except FileNotFoundError:
        if Path(path).suffix:
            raise
        with policy.open_file('index.html', 'rb') as handle:
            return result('index.html', handle.read(MAX_BYTES + 1))
