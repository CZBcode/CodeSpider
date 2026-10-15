"""Account-scoped background generation jobs and resumable proposal checkpoints."""
import threading
from contextlib import nullcontext
from concurrent.futures import ThreadPoolExecutor
from backend.models import new_id, now_iso


class GenerationService:
    def __init__(self, context):
        self.context = context
        self.store = context.store
        self.executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix='codespider-generation')
        self.lock = threading.RLock()
        self.active = set()
        self.slots = threading.BoundedSemaphore(8)
        # This daemon owns generation workers; persisted running jobs belong to
        # the previous process and can be explicitly resumed after restart.
        self.store.update('generations', [], lambda items: [dict(j,status='interrupted',
            error='服务已重启，已保存的生成批次可继续。') if j['status'] in ('queued','running') else j for j in items])

    def _update(self, job_id, **values):
        self.store.update('generations', [], lambda items: [dict(j,**values) if j['id']==job_id else j for j in items])

    def get(self, job_id, owner_id, private=False):
        job=next((j for j in self.store.read('generations',[]) if j['id']==job_id),None)
        if not job or job['owner_id']!=owner_id:
            raise PermissionError('无权访问该生成任务')
        if job.get('kind') != 'chat':
            self.context.workspaces.get(job['workspace_id'],owner_id=owner_id)
        if job.get('turn_id') and job['status'] in ('interrupted','failed'):
            existing=next((t for t in self.store.read('tasks',[]) if t.get('conversation_turn_id')==job['turn_id']
                and t.get('owner_id')==owner_id and t['workspace_id']==job['workspace_id']),None)
            if existing: job=dict(job,status='completed',task_id=existing['id'],error='')
            if job.get('kind') == 'chat':
                turn=next((t for t in self.context.account_store.read('conversation_turns', [])
                    if t['id']==job['turn_id'] and t['user_id']==owner_id and t['workspace_id']==''), None)
                if turn and turn['status']=='completed':
                    job=dict(job,status='completed',reply=turn['reply'],intent=turn.get('intent'),timing=self.context.conversations.timing(turn),error='')
        if private: return job
        public={k:v for k,v in job.items() if k not in ('request','checkpoint','owner_id')}
        public['goal']=job['request']['goal']
        checkpoint=job.get('checkpoint',{})
        public['draft']={'files':len(checkpoint.get('patches',[])),
                         'repair_pending':bool(checkpoint.get('validation_failed')),
                         'repair_round':checkpoint.get('repair',{}).get('round',0)}
        if (job['status'] in ('failed','interrupted') and checkpoint.get('signature') == ''
                and checkpoint.get('validation_failed')):
            public['error']='整体检查尚未通过，草稿已保留。点击“继续修复”会校验并恢复已有文件，再继续修正设计与代码。'
        if job.get('task_id'):
            task=self.context.tasks.get(job['task_id'],owner_id=owner_id)
            public['task']=self.context.conversations.task_payload(task.to_dict())
        return public

    def submit(self, user, body, resume_id='', kind='project'):
        with self.lock:
            job=self.get(resume_id,user['id'],private=True) if resume_id else None
            if job and job['status']=='completed': return self.get(resume_id,user['id'])
            if job and (job['id'] in self.active or job['status'] not in ('failed','interrupted')):
                raise ValueError('该任务已经在生成，请等待当前请求完成')
            kind=job.get('kind','project') if job else kind
            request=job['request'] if job else {k:body[k] for k in ('workspace_id','goal','patches','plugin_id','intent_preview') if k in body}
            workspace_id=request.get('workspace_id','')
            if not isinstance(workspace_id,str) or not isinstance(request.get('goal'),str) or not 1<=len(request['goal'].strip())<=32000:
                raise ValueError('请填写工程及 1 到 32000 字符的需求')
            if kind=='chat' and workspace_id:
                raise ValueError('随意对话不能绑定工程')
            with self.context.workspaces.lease(workspace_id) if kind!='chat' else nullcontext():
                selection={'recommendation':''}
                if kind!='chat':
                    workspace=self.context.workspaces.get(workspace_id,owner_id=user['id'])
                    selection=self.context.market.select(request['goal']+'\n'+workspace.description,workspace.project_type,user['id'],request.get('plugin_id',''))
                    if selection['requires_choice'] and not request.get('plugin_id'):
                        raise ValueError(selection['recommendation'])
                if self.context.auth_required and not self.context.auth.selected_model(user):
                    raise ValueError('管理员尚未为当前用户分配模型')
                if not self.slots.acquire(blocking=False): raise ValueError('生成队列已满，请稍后重试')
                try:
                    if not job:
                        job={'id':new_id('gen'),'workspace_id':workspace_id,'owner_id':user['id'],
                             'request':request,'created_at':now_iso(),'checkpoint':{},'kind':kind}
                        self.store.append('generations',dict(job,status='queued'))
                    job_id=job['id']; self.active.add(job_id)
                    self._update(job_id,status='queued',error='',finished_at=None,progress={'stage':'已排队，准备生成','recommendation':selection['recommendation']})
                    self.executor.submit(self._run,job_id,dict(user),request,job.get('checkpoint',{}),kind)
                except Exception:
                    self.active.discard(job.get('id') if job else '')
                    self.slots.release()
                    raise
            return self.get(job_id,user['id'])

    def _run(self, job_id, user, request, checkpoint, kind='project'):
        try:
            self._update(job_id,status='running')
            callbacks=dict(
                on_turn=lambda turn_id:self._update(job_id,turn_id=turn_id),
                progress=lambda value:self._progress(job_id,value),checkpoint=checkpoint,
                save_checkpoint=lambda value:self._update(job_id,checkpoint=value))
            if kind=='chat':
                reply=self.context.generate_chat(user,request,**callbacks)
                self._update(job_id,status='completed',finished_at=now_iso(),**reply)
            else:
                task=self.context.generate_task(user,request,background=True,**callbacks)
                self._update(job_id,status='completed',task_id=task.id,finished_at=now_iso())
        except Exception as exc:
            error=str(exc)
            if any(w in error.lower() for w in ('timed out','timeout','model api request failed')):
                error='模型本次响应超时，已保存已完成批次。请点击“继续生成”重试，或缩小单个模块范围。'
            self._update(job_id,status='failed',error=error,finished_at=now_iso())
        finally:
            with self.lock: self.active.discard(job_id)
            self.slots.release()

    def _progress(self, job_id, value):
        self.store.update('generations',[],lambda items:[dict(j,progress={**j.get('progress',{}),**value})
            if j['id']==job_id else j for j in items])

    def close(self):
        self.executor.shutdown(wait=True)
