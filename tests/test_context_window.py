import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from backend.conversations import ConversationService, SUMMARY_CHARS
from backend.model_gateway import ModelGateway
from backend.store import JsonStore
import test_conversations as fixtures


class ContextWindowTests(unittest.TestCase):
    def test_fifteen_round_boundary_archive_restart_and_scope(self):
        with tempfile.TemporaryDirectory() as root:
            store = JsonStore(root)
            service = ConversationService(store, store)
            for n in range(15):
                service.finish(service.begin('alice', 'A', 'requirement-%s' % n), reply='answer-%s' % n)
            self.assertEqual(service.context('alice', 'A')['archived_count'], 0)
            service.finish(service.begin('alice', 'A', 'requirement-15'), reply='answer-15')
            window = service.context('alice', 'A')
            self.assertEqual(len(window['recent_turns']), 15)
            self.assertEqual(window['recent_turns'][0]['goal'], 'requirement-1')
            self.assertEqual(window['archived_count'], 1)
            self.assertIn('requirement-0', window['summary'])
            self.assertIn('answer-0', window['summary'])
            for user, workspace in [('bob', 'A'), ('alice', 'B'), ('alice', '')]:
                self.assertEqual(service.context(user, workspace)['recent_turns'], [])
                self.assertEqual(service.context(user, workspace)['summary'], '')
            reopened = ConversationService(JsonStore(root), JsonStore(root))
            self.assertEqual(reopened.context('alice', 'A'), window)
            self.assertEqual(len(reopened.history('alice', 'A')), 16)
            self.assertEqual(len(store.read('conversation_archives', [])), 1)

    def test_late_failure_refreshes_archive_and_does_not_include_patch_or_logs(self):
        with tempfile.TemporaryDirectory() as root:
            store = JsonStore(root); service = ConversationService(store, store)
            first = service.begin('alice', 'A', 'create a service')
            service.finish(first, reply='proposed service')
            store.append('tasks', {'id': 'task', 'workspace_id': 'A', 'owner_id': 'alice',
                'conversation_turn_id': first, 'status': 'created', 'patches': [{'path': 'service.py', 'content': 'SECRET_FULL_PATCH'}]})
            store.append('events', {'task_id': 'task', 'payload': 'SECRET_EXECUTION_LOG'})
            for n in range(15): service.finish(service.begin('alice', 'A', 'next %s' % n), reply='reply')
            self.assertIn('created', service.context('alice', 'A')['summary'])
            store.update('tasks', [], lambda items: [dict(t, status='failed', error='tests failed') for t in items])
            window = service.context('alice', 'A')
            self.assertIn('failed', window['summary']); self.assertIn('tests failed', window['summary'])
            self.assertNotIn('SECRET_', json.dumps(window))
            self.assertIn('service.py', window['summary'])

    def test_long_archives_are_bounded_and_full_history_remains(self):
        with tempfile.TemporaryDirectory() as root:
            store = JsonStore(root); service = ConversationService(store, store)
            store.write('conversation_turns', [{'id': str(n), 'user_id': 'alice', 'workspace_id': 'A',
                'goal': ('requirement%s ' % n) * 100, 'reply': 'answer ' * 100, 'status': 'completed'} for n in range(120)])
            context = service.context('alice', 'A')
            self.assertEqual(len(context['recent_turns']), 15)
            self.assertEqual(context['archived_count'], 105)
            self.assertLessEqual(len(context['summary']), SUMMARY_CHARS)
            self.assertIn('完整记录仍保留', context['summary'])
            self.assertEqual(len(store.read('conversation_archives', [])[0]['entries']), 105)
            self.assertEqual(len(service.history('alice', 'A')), 120)

    def test_gateway_sends_archive_and_all_fifteen_recent_pairs(self):
        gateway = ModelGateway()
        context = {'summary': 'old architecture decisions', 'recent_turns': [
            {'goal': 'question%s' % n, 'reply': 'answer%s' % n} for n in range(15)]}
        with patch.object(gateway, '_request_chat_completion', return_value=json.dumps({'choices': [{'message': {'content': 'ok'}}]})) as request:
            gateway.chat('current', context, settings_override={'provider': 'openai', 'base_url': 'https://example.invalid', 'api_key': 'fake'})
        messages = request.call_args.args[2]
        self.assertEqual(len(messages), 33)
        self.assertIn('old architecture decisions', messages[1]['content'])
        self.assertEqual(messages[2]['content'], 'question0')
        self.assertEqual(messages[-2]['content'], 'answer14')
        self.assertEqual(messages[-1]['content'], 'current')


class WorkspaceDeletionTests(unittest.TestCase):
    setUp = fixtures.ConversationHttpTests.setUp
    tearDown = fixtures.ConversationHttpTests.tearDown
    request = fixtures.ConversationHttpTests.request

    def delete(self, body=None, expected=200, opener=None):
        return self.request('/api/workspaces/'+self.workspace['id']+'/delete',
            body if body is not None else {'confirmed': True, 'confirm_name': self.workspace['name']}, expected, opener)

    def test_delete_confirmation_ownership_restart_and_original_files(self):
        task = self.request('/api/tasks', {'workspace_id': self.workspace['id'], 'goal': 'inspect'}, 201)
        self.delete({}, 400)
        self.delete({'confirmed': True, 'confirm_name': 'wrong'}, 400)
        self.delete({'confirmed': 'true', 'confirm_name': self.workspace['name']}, 400)
        self.delete(expected=403, opener=self.other)
        self.assertEqual(len(self.request('/api/workspaces')['items']), 1)
        result = self.delete()
        self.assertTrue(result['source_files_preserved'])
        self.assertEqual(self.request('/api/workspaces')['items'], [])
        self.assertEqual((self.project/'README.md').read_text(), 'download me')
        self.request('/api/tasks/'+task['id']+'/approve', {}, 400)
        self.request('/api/tasks/'+task['id'], expected=404)
        self.request('/api/conversations?workspace_id='+self.workspace['id'], expected=404)
        self.request('/api/workspaces/'+self.workspace['id']+'/download', expected=404)
        self.request('/api/workspaces/'+self.workspace['id']+'/file?path=README.md', expected=400)
        self.assertEqual(len(self.context.account_store.read('conversation_turns', [])), 1)
        from backend.workspaces import WorkspaceManager
        restored = WorkspaceManager(JsonStore(str(Path(self.temp.name)/'state')))
        self.assertEqual(restored.list(), [])
        self.assertEqual(len(restored.store.read('deleted_workspaces', [])), 1)
        with self.assertRaises(PermissionError):
            restored.create(str(self.project), owner_id='someone-else')

    def test_delete_rejects_executing_task_and_live_service(self):
        task = self.request('/api/tasks', {'workspace_id': self.workspace['id'], 'goal': 'inspect'}, 201)
        self.context.store.update('tasks', [], lambda items: [dict(t, status='executing') for t in items])
        self.assertIn('执行', self.delete(expected=400)['error'])
        self.context.store.update('tasks', [], lambda items: [dict(t, status='failed') for t in items])
        with patch.object(self.context.processes, 'list', return_value=[{'status': 'running'}]):
            self.assertIn('服务', self.delete(expected=400)['error'])
        self.delete()

    def test_delete_during_generation_or_tool_operation_is_rejected(self):
        entered = threading.Event(); release = threading.Event()
        original = self.context.tasks.model.plan
        def delayed(*args, **kwargs):
            entered.set(); release.wait(5)
            return original(*args, **kwargs)
        with patch.object(self.context.tasks.model, 'plan', side_effect=delayed):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self.request, '/api/tasks', {'workspace_id': self.workspace['id'], 'goal': 'inspect'}, 201)
                try:
                    self.assertTrue(entered.wait(5))
                    self.assertIn('正在', self.delete(expected=400)['error'])
                finally: release.set()
                future.result()
        # Separate manager models the independently running Agent process lock.
        from backend.workspaces import WorkspaceManager
        with WorkspaceManager(self.context.store).lease(self.workspace['id']):
            self.assertIn('正在', self.delete(expected=400)['error'])
        self.delete()

    def test_project_generation_receives_scoped_window(self):
        user = self.request('/api/auth/me')['user']['id']
        service = self.context.conversations
        for n in range(20): service.finish(service.begin(user, self.workspace['id'], 'old-%s' % n), reply='reply-%s' % n)
        service.finish(service.begin(user, '', 'FREE_PRIVATE'), reply='free')
        original = self.context.tasks.model.plan
        with patch.object(self.context.tasks.model, 'plan', wraps=original) as model:
            self.request('/api/tasks', {'workspace_id': self.workspace['id'], 'goal': 'current'}, 201)
        context = model.call_args.args[1]['conversation']
        self.assertEqual(len(context['recent_turns']), 15)
        self.assertEqual(context['recent_turns'][0]['goal'], 'old-5')
        self.assertEqual(context['archived_count'], 5)
        self.assertIn('old-0', context['summary'])
        self.assertNotIn('FREE_PRIVATE', json.dumps(context))
