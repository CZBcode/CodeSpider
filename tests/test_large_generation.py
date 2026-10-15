import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from backend.model_gateway import ModelGateway, ModelRequestError
from backend.project_generator import ProjectGenerator
import test_conversations as fixtures


def response(value):
    return json.dumps({'choices':[{'message':{'content':json.dumps(value)}}]})


CONFIG={'provider':'custom','model':'fake','base_url':'https://example.invalid/v1','api_key':'test-only','max_tokens':8192}
MANIFEST={'summary':'实现模块与测试', 'files':[
    {'path':'domain.py','contract':'def add(a: int, b: int) -> int'},
    {'path':'service.py','contract':'from domain import add; def total() -> int returns add(2,3)'},
    {'path':'tests/test_service.py','contract':'unittest verifies service.total() == 5'}]}
FILES={'domain.py':'def add(a, b):\n    return a + b\n',
       'service.py':'from domain import add\ndef total():\n    return add(2, 3)\n',
       'tests/test_service.py':'import unittest\nfrom service import total\nclass ServiceTests(unittest.TestCase):\n    def test_total(self):\n        self.assertEqual(total(), 5)\n'}


class StagedGenerationTests(unittest.TestCase):
    def test_build_dependencies_survive_source_context_budget(self):
        model=ModelGateway(); supplied=[]
        files={'pom.xml':'<project/>','first.txt':'a'*25000,'second.txt':'b'*25000,'last.txt':'done'}
        manifest={'summary':'bounded context','files':[{'path':p,'contract':'content'} for p in files]}
        def request(endpoint,settings,system,payload,**kwargs):
            data=json.loads(payload)
            if 'current_file' not in data:return response(manifest)
            supplied.append(data)
            path=data['current_file']['path']
            return response({'summary':'ready','patches':[{'path':path,'operation':'create','replacement':files[path]}]})
        with patch.object(model,'_request_completion',side_effect=request):
            ProjectGenerator(model).generate('project',{'files':{},'file_paths':[]},CONFIG)
        self.assertIn('pom.xml',supplied[-1]['proposed_dependencies'])
        self.assertIn('second.txt',supplied[-1]['proposed_dependencies'])
        self.assertLessEqual(sum(len(v) for v in supplied[-1]['proposed_dependencies'].values()),48000)

    def test_retry_resume_keeps_completed_files_and_charges_only_new_requests(self):
        model=ModelGateway(); checkpoint={}; calls=[]; charges=[]; failing=True
        def request(endpoint,settings,system,payload,**kwargs):
            if kwargs.get('on_model_call'): kwargs['on_model_call']()
            data=json.loads(payload.split('\nCorrect the previous error:')[0]); calls.append(data)
            if 'current_file' not in data: return response(MANIFEST)
            path=data['current_file']['path']
            if path=='service.py' and failing: raise ModelRequestError('timed out',True)
            return response({'summary':'file ready','patches':[{'path':path,'operation':'create','replacement':FILES[path]}]})
        def save(value): checkpoint.clear();checkpoint.update(json.loads(json.dumps(value)))
        context={'files':{},'file_paths':[],'require_patches':True,'conversation':{'summary':'initial'}}
        with patch.object(model,'_request_completion',side_effect=request),patch('backend.project_generator.time.sleep'):
            with self.assertRaisesRegex(RuntimeError,'先前进度'):
                ProjectGenerator(model).generate('Python 工程',context,CONFIG,lambda:charges.append(1),checkpoint=checkpoint,save=save)
            self.assertEqual(len(checkpoint['patches']),1)
            self.assertEqual(len(charges),5)
            failing=False
            turn=ProjectGenerator(model).generate('Python 工程',dict(context,conversation={'summary':'new retry turn'}),CONFIG,
                lambda:charges.append(1),checkpoint=checkpoint,save=save)
        self.assertEqual(len(turn['patches']),3);self.assertEqual(len(charges),7)
        self.assertEqual(sum(c.get('current_file',{}).get('path')=='domain.py' for c in calls),1)
        self.assertIn('domain.py',calls[-1]['proposed_dependencies'])

    def test_no_charge_when_transport_capacity_is_unavailable(self):
        from unittest.mock import Mock
        charge=Mock()
        with patch('backend.model_gateway._REMOTE_SEMAPHORE') as semaphore, patch('backend.model_gateway.urlrequest.urlopen') as network:
            semaphore.acquire.return_value=False
            with self.assertRaises(ModelRequestError):
                ModelGateway._request_completion('https://example.invalid',CONFIG,'system','user',on_model_call=charge)
            charge.assert_not_called();network.assert_not_called();semaphore.release.assert_not_called()
        with patch('backend.model_gateway.urlrequest.urlopen') as network:
            charge.side_effect=ValueError('积分余额不足')
            with self.assertRaisesRegex(RuntimeError,'积分余额不足'):
                ModelGateway._request_completion('https://example.invalid',CONFIG,'system','user',on_model_call=charge)
            network.assert_not_called()

    def test_contract_rejects_wrong_file_and_unsafe_manifest_and_clears_stale_checkpoint(self):
        model=ModelGateway(); states=[]; calls=[]
        def request(endpoint,settings,system,payload,**kwargs):
            if kwargs.get('on_model_call'): kwargs['on_model_call']()
            calls.append(payload)
            data=json.loads(payload.split('\nCorrect the previous error:')[0])
            if 'current_file' not in data: return response({'summary':'bad','files':[{'path':'../escape.py','contract':'unsafe'}]})
            return response({'summary':'wrong','patches':[{'path':'wrong.py','operation':'create','replacement':'x=1'}]})
        with patch.object(model,'_request_completion',side_effect=request):
            with self.assertRaises(RuntimeError):
                ProjectGenerator(model).generate('工程',{'files':{}},CONFIG,save=states.append)
        self.assertEqual(len(calls),3);self.assertEqual(states,[])
        # Cached signatures from a different source/model must never be reused.
        with patch.object(model,'_request_completion',side_effect=request):
            with self.assertRaises(RuntimeError):
                ProjectGenerator(model).generate('工程',{'files':{'a':'changed'}},CONFIG,
                    checkpoint={'signature':'old','manifest':MANIFEST,'patches':[]})
        self.assertEqual(len(calls),6)


class BackgroundGenerationTests(unittest.TestCase):
    setUp=fixtures.ConversationHttpTests.setUp
    tearDown=fixtures.ConversationHttpTests.tearDown
    request=fixtures.ConversationHttpTests.request

    def wait_job(self,job_id):
        for _ in range(100):
            job=self.request('/api/generations/'+job_id)
            if job['status'] in ('completed','failed','interrupted'): return job
            time.sleep(.05)
        self.fail('job did not complete')

    def test_background_returns_before_model_and_isolates_users_and_deletion(self):
        entered=threading.Event();release=threading.Event();original=self.context.tasks.model.plan
        def slow(*args,**kwargs):
            entered.set();release.wait(5);return original(*args,**kwargs)
        with patch.object(self.context.tasks.model,'plan',side_effect=slow):
            job=self.request('/api/tasks',{'workspace_id':self.workspace['id'],'goal':'inspect','async_generation':True},202)
            try:
                self.assertTrue(entered.wait(3));self.assertIn(job['status'],('queued','running'))
                self.request('/api/generations/'+job['id'],expected=403,opener=self.other)
                self.request('/api/generations/'+job['id']+'/resume',{},403,self.other)
                self.request('/api/workspaces/'+self.workspace['id']+'/delete',{'confirmed':True,'confirm_name':self.workspace['name']},400)
            finally:release.set()
            finished=self.wait_job(job['id'])
        self.assertEqual(finished['status'],'completed')
        self.assertNotIn('checkpoint',finished);self.assertNotIn('request',finished)
        self.assertEqual(set(finished['draft']),{'files','repair_pending','repair_round'})
        self.assertEqual(finished['task']['status'],'created')
        self.assertTrue(self.project.joinpath('README.md').exists())

    def test_staged_http_checkpoints_billing_resume_and_real_execution(self):
        charges_before=self.request('/api/auth/me')['user']['balance']
        failing=True
        def request(endpoint,settings,system,payload,**kwargs):
            if kwargs.get('on_model_call'): kwargs['on_model_call']()
            data=json.loads(payload.split('\nCorrect the previous error:')[0])
            if 'current_file' not in data:return response(MANIFEST)
            path=data['current_file']['path']
            if path=='service.py' and failing:raise ModelRequestError('timed out',True)
            return response({'summary':'ready','patches':[{'path':path,'operation':'create','replacement':FILES[path]}]})
        with patch.object(self.context.auth,'model_config',return_value=CONFIG),patch.object(self.context.tasks.model,'_request_completion',side_effect=request),patch('backend.project_generator.time.sleep'):
            job=self.request('/api/tasks',{'workspace_id':self.workspace['id'],'goal':'实现 Python 工程','async_generation':True},202)
            failed=self.wait_job(job['id']);self.assertEqual(failed['status'],'failed')
            self.assertEqual(failed['draft']['files'],1)
            self.assertFalse((self.project/'domain.py').exists())
            self.assertEqual(self.request('/api/auth/me')['user']['balance'],charges_before-5)
            history=self.request('/api/conversations?workspace_id='+self.workspace['id'])
            self.assertEqual(history['generations'][0]['id'],job['id'])
            from backend.generations import GenerationService
            self.context.generations.close()
            self.context.generations._update(job['id'],status='running')
            self.context.generations=GenerationService(self.context)
            self.assertEqual(self.request('/api/generations/'+job['id'])['status'],'interrupted')
            failing=False
            self.request('/api/generations/'+job['id']+'/resume',{},202)
            finished=self.wait_job(job['id'])
            self.assertEqual(finished['status'],'completed',finished.get('error'))
            self.assertEqual(self.request('/api/auth/me')['user']['balance'],charges_before-7)
        task=finished['task'];self.assertEqual(task['plugin_id'],'plugin.python')
        self.request('/api/tasks/'+task['id']+'/approve',{})
        self.context.tasks.executor.shutdown(wait=True)
        executed=self.request('/api/tasks/'+task['id'])
        self.assertEqual(executed['status'],'succeeded',executed.get('error'))
        self.assertEqual((self.project/'domain.py').read_text(),FILES['domain.py'])
        self.assertTrue(any('Ran 1 test' in str(e.payload) for e in self.context.tasks.events(task['id'])))

    def test_intent_recommendations_and_ambiguity_are_actionable(self):
        endpoint='/api/workspaces/'+self.workspace['id']+'/recommendation'
        for goal,plugin in [('学生教务管理系统','plugin.springboot'),('做一个交互仪表盘页面','plugin.vue'),('写一个自动化批处理脚本','plugin.python')]:
            result=self.request(endpoint,{'goal':goal});self.assertEqual(result['plugin']['id'],plugin)
            self.assertTrue(result['recommendation'])
        ambiguous=self.request(endpoint,{'goal':'Spring Boot 和 Vue 管理系统'})
        self.assertTrue(ambiguous['requires_choice'])
        self.assertIn('独立项目',ambiguous['recommendation'])
        self.request(endpoint,{'goal':'Python'},403,self.other)
