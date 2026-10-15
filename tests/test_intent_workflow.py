import json
import threading
import unittest
from unittest.mock import patch

from backend.intent import IntentService
from backend.model_gateway import ModelGateway, ModelRequestError
from backend.conversations import ConversationService
import test_large_generation as fixtures
from test_large_generation import CONFIG, MANIFEST, FILES, response


INTENT = {'summary':'我会实现 Python 模块并补充测试，保留最近15轮对话。',
          'goals':['实现模块'], 'constraints':['保留最近15轮对话'], 'steps':['实现并验证模块']}


class IntentTests(unittest.TestCase):
    def test_retry_fallback_does_not_fabricate_understanding(self):
        model=ModelGateway(); saved=[]; progress=[]
        with patch.object(model,'_request_completion',side_effect=ModelRequestError('timeout',True)) as request:
            result=IntentService(model).prepare('任务',{},CONFIG,{},saved.append,progress.append)
        self.assertEqual(request.call_count,2)
        self.assertEqual(result['intent']['status'],'unavailable')
        self.assertIn('原始需求',result['intent']['summary'])
        self.assertEqual(progress[-1]['intent'],result['intent'])
        with patch.object(model,'_request_completion',return_value=response({'summary':'x','steps':['x'*301]})) as request:
            result=IntentService(model).prepare('任务',{},CONFIG,{},saved.append,progress.append)
        self.assertEqual(request.call_count,2);self.assertEqual(result['intent']['status'],'unavailable')

    def test_valid_brief_is_cached_but_new_goal_or_model_invalidates_it(self):
        model=ModelGateway();context={'workspace':{'name':'demo'},'conversation':{'summary':'old'}}
        with patch.object(model,'_request_completion',return_value=response(INTENT)) as request:
            state=IntentService(model).prepare('模块',context,CONFIG,{},lambda x:None,lambda x:None)
            IntentService(model).prepare('模块',dict(context,conversation={'summary':'retry'}),CONFIG,state,lambda x:None,lambda x:None)
            self.assertEqual(request.call_count,1)
            IntentService(model).prepare('另一个需求',context,CONFIG,state,lambda x:None,lambda x:None)
            IntentService(model).prepare('模块',context,dict(CONFIG,model='changed'),state,lambda x:None,lambda x:None)
            self.assertEqual(request.call_count,3)


class IntentHttpTests(unittest.TestCase):
    setUp=fixtures.BackgroundGenerationTests.setUp
    tearDown=fixtures.BackgroundGenerationTests.tearDown
    request=fixtures.BackgroundGenerationTests.request
    wait_job=fixtures.BackgroundGenerationTests.wait_job

    def test_project_brief_precedes_generation_persists_and_is_charged_once(self):
        entered=threading.Event();release=threading.Event();calls=[]
        def request(endpoint,settings,system,payload,**kwargs):
            kwargs['on_model_call']()
            data=json.loads(payload);calls.append(data)
            if data.get('phase')=='understand':return response(INTENT)
            self.assertEqual(data['context']['intent']['summary'],INTENT['summary'])
            if 'current_file' not in data:
                entered.set();release.wait(5);return response(MANIFEST)
            path=data['current_file']['path']
            return response({'summary':'ready','patches':[{'path':path,'operation':'create','replacement':FILES[path]}]})
        before=self.request('/api/auth/me')['user']['balance']
        with patch.object(self.context.auth,'model_config',return_value=CONFIG),patch.object(self.context.tasks.model,'_request_completion',side_effect=request):
            job=self.request('/api/tasks',{'workspace_id':self.workspace['id'],'goal':'实现 Python 工程','async_generation':True,'intent_preview':True},202)
            try:
                self.assertTrue(entered.wait(3))
                running=self.request('/api/generations/'+job['id'])
                self.assertEqual(running['status'],'running')
                self.assertEqual(running['progress']['intent']['summary'],INTENT['summary'])
                self.assertFalse((self.project/'domain.py').exists())
                self.request('/api/generations/'+job['id'],expected=403,opener=self.other)
            finally:release.set()
            completed=self.wait_job(job['id'])
        self.assertEqual(completed['status'],'completed',completed.get('error'))
        self.assertEqual(completed['task']['intent']['summary'],INTENT['summary'])
        self.assertEqual(self.request('/api/auth/me')['user']['balance'],before-5)
        reopened=ConversationService(self.context.account_store,self.context.store)
        history=reopened.history(self.request('/api/auth/me')['user']['id'],self.workspace['id'])
        self.assertEqual(history[0]['intent']['summary'],INTENT['summary'])
        self.assertEqual(history[0]['task']['status'],'created')

    def test_free_chat_failure_resume_restores_intent_without_rebilling(self):
        entered=threading.Event();release=threading.Event();fail=True;intents=[]
        def understand(endpoint,settings,system,payload,**kwargs):
            kwargs['on_model_call']();intents.append(json.loads(payload))
            return response(INTENT)
        def answer(endpoint,settings,messages,**kwargs):
            kwargs['on_model_call']();entered.set();release.wait(5)
            self.assertTrue(any(INTENT['summary'] in m['content'] for m in messages))
            if fail:raise ModelRequestError('timeout',True)
            return json.dumps({'choices':[{'message':{'content':'最终回答'}}]})
        before=self.request('/api/auth/me')['user']['balance']
        with patch.object(self.context.auth,'model_config',return_value=CONFIG),patch.object(self.context.tasks.model,'_request_completion',side_effect=understand),patch.object(self.context.tasks.model,'_request_chat_completion',side_effect=answer):
            job=self.request('/api/conversations/free',{'text':'先讨论方案','async_generation':True,'intent_preview':True},202)
            try:
                self.assertTrue(entered.wait(3))
                running=self.request('/api/generations/'+job['id'])
                self.assertEqual(running['kind'],'chat');self.assertEqual(running['progress']['intent']['summary'],INTENT['summary'])
                self.request('/api/generations/'+job['id']+'/resume',{},403,self.other)
            finally:release.set()
            self.assertEqual(self.wait_job(job['id'])['status'],'failed')
            fail=False
            self.request('/api/generations/'+job['id']+'/resume',{},202)
            completed=self.wait_job(job['id'])
        self.assertEqual(completed['status'],'completed',completed.get('error'))
        self.assertEqual(completed['reply'],'最终回答')
        self.assertEqual(len(intents),1)
        self.assertEqual(self.request('/api/auth/me')['user']['balance'],before-3)
        self.assertEqual(self.request('/api/conversations?workspace_id=')['items'][-1]['intent']['summary'],INTENT['summary'])
        self.assertEqual(self.request('/api/conversations?workspace_id=',opener=self.other)['items'],[])
        self.assertEqual(self.context.store.read('tasks',[]),[])
