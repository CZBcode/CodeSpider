import concurrent.futures
import os
import shlex
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app import AppContext
from backend.tool_protocol import ToolRequest, ToolResponse


def wait_until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.01)
    raise AssertionError('condition timed out')


class TaskRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'project'
        self.root.mkdir()
        (self.root / 'main.py').write_text('value = 1\n')
        self.context = AppContext(str(Path(self.temp.name) / 'data'))
        self.addCleanup(self.context.processes.close)
        self.addCleanup(self.context.tasks.executor.shutdown, wait=True)
        self.tasks = self.context.tasks
        self.workspace = self.context.workspaces.create(str(self.root))

    def test_verification_nonzero_marks_failed_with_no_success_event(self):
        task = self.tasks.create(self.workspace.id, 'compile invalid code', [{'path': 'bad.py', 'content': 'def broken(\n'}])
        self.tasks.approve(task.id)
        self.tasks.executor.shutdown(wait=True)
        result = self.tasks.get(task.id)
        self.assertEqual(result.status, 'failed')
        self.assertIn('exit code 1', result.error)
        events = self.tasks.events(task.id)
        self.assertNotIn('task.succeeded', [event.type for event in events])
        self.assertIn(1, [event.payload['exit_code'] for event in events if event.type == 'process.output'])
        with self.assertRaises(ValueError):
            self.tasks.cancel(task.id)
        self.assertEqual(self.tasks.get(task.id).status, 'failed')

    def test_concurrent_creates_preserve_all_tasks(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
            tasks = list(pool.map(lambda n: self.tasks.create(self.workspace.id, 'task %s' % n), range(48)))
        self.assertEqual(len(self.tasks._tasks()), 48)
        for task in tasks:
            self.assertEqual(self.tasks.get(task.id).goal, task.goal)
            self.assertEqual([event.sequence for event in self.tasks.events(task.id)], [1, 2])

    def test_concurrent_approvals_submit_once(self):
        task = self.tasks.create(self.workspace.id, 'approve once')
        def approve(_):
            try:
                self.tasks.approve(task.id)
                return True
            except ValueError:
                return False
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            approvals = list(pool.map(approve, range(16)))
        self.tasks.executor.shutdown(wait=True)
        self.assertEqual(sum(approvals), 1)
        self.assertEqual(self.tasks.get(task.id).status, 'succeeded')
        self.assertEqual([e.type for e in self.tasks.events(task.id)].count('approval.accepted'), 1)
        with self.assertRaises(ValueError):
            self.tasks.cancel(task.id)

    def test_cancel_running_command_reaps_process_and_preserves_cancelled_state(self):
        marker = self.root / 'command.pid'
        script = "import os,time; from pathlib import Path; Path('command.pid').write_text(str(os.getpid())); time.sleep(3); Path('too-late').write_text('bad')"
        self.tasks._default_verify = lambda _: shlex.quote(sys.executable) + ' -c ' + shlex.quote(script)
        task = self.tasks.create(self.workspace.id, 'cancel command')
        self.tasks.approve(task.id)
        wait_until(marker.exists)
        pid = int(marker.read_text())
        cancelled = self.tasks.cancel(task.id)
        self.assertEqual(cancelled.status, 'cancelled')
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)
        self.tasks.executor.shutdown(wait=True)
        self.assertFalse((self.root / 'too-late').exists())
        self.assertEqual(self.tasks.get(task.id).status, 'cancelled')
        events = [event.type for event in self.tasks.events(task.id)]
        self.assertNotIn('task.succeeded', events)
        self.assertNotIn('task.failed', events)
        self.assertEqual(events.count('task.cancelled'), 1)
        self.tasks.cancel(task.id)
        self.assertEqual([e.type for e in self.tasks.events(task.id)].count('task.cancelled'), 1)

    def test_cancel_before_approval_prevents_writes(self):
        task = self.tasks.create(self.workspace.id, 'cancel pending', [{'path': 'new.py', 'content': 'value=2'}])
        self.assertEqual(self.tasks.cancel(task.id).status, 'cancelled')
        with self.assertRaises(ValueError):
            self.tasks.approve(task.id)
        self.assertFalse((self.root / 'new.py').exists())

    def test_agent_refuses_delayed_operations_after_cancellation(self):
        tools = self.context.tools
        response = tools.call(ToolRequest('process', 'cancel', task_id='cancelled-before-arrival'))
        self.assertTrue(response.ok)
        response = tools.call(ToolRequest('workspace', 'write_file', {'path': 'late.txt', 'content': 'bad'},
            workspace_id=self.workspace.id, task_id='cancelled-before-arrival', approval={'approved': True}))
        self.assertFalse(response.ok)
        self.assertFalse((self.root / 'late.txt').exists())
        # Cancellation affects only its own task.
        other = self.tasks.create(self.workspace.id, 'different task')
        response = tools.call(ToolRequest('workspace', 'write_file', {'path': 'other.txt', 'content': 'ok'},
            workspace_id=self.workspace.id, task_id=other.id, approval={'approved': True}))
        self.assertTrue(response.ok)

    def test_cancellation_waits_for_inflight_write_and_blocks_next_patch(self):
        started, release = threading.Event(), threading.Event()
        original = self.context.tools._workspace
        def delayed(request):
            started.set()
            release.wait(timeout=3)
            return original(request)
        task = self.tasks.create(self.workspace.id, 'cancel between patches', [
            {'path': 'first.txt', 'content': 'first'}, {'path': 'second.txt', 'content': 'second'}])
        with patch.object(self.context.tools, '_workspace', side_effect=delayed):
            self.tasks.approve(task.id)
            self.assertTrue(started.wait(timeout=3))
            with concurrent.futures.ThreadPoolExecutor() as pool:
                cancellation = pool.submit(self.tasks.cancel, task.id)
                wait_until(lambda: self.tasks.get(task.id).status == 'cancelling')
                self.assertFalse(cancellation.done())
                release.set()
                self.assertEqual(cancellation.result(timeout=3).status, 'cancelled')
            self.tasks.executor.shutdown(wait=True)
        self.assertTrue((self.root / 'first.txt').exists())
        self.assertFalse((self.root / 'second.txt').exists())

    def test_agent_unavailable_does_not_claim_cancellation_completed(self):
        task = self.tasks.create(self.workspace.id, 'cancellation acknowledgement')
        task.status = 'executing'
        self.tasks._save_task(task)
        with patch.object(self.context.tools, 'call', return_value=ToolResponse('cancel', False,
                error={'code': 'AGENT_UNAVAILABLE', 'message': 'Agent unavailable'})):
            with self.assertRaises(ValueError):
                self.tasks.cancel(task.id)
        self.assertEqual(self.tasks.get(task.id).status, 'cancelling')
        self.assertNotIn('task.cancelled', [e.type for e in self.tasks.events(task.id)])
        self.assertEqual(self.tasks.cancel(task.id).status, 'cancelled')
