"""A short, public requirements brief before answering or generating code."""
import hashlib
import json

from backend.model_gateway import ModelContractError, ModelRequestError


class IntentService:
    def __init__(self, model):
        self.model = model

    @staticmethod
    def validate(value):
        if not isinstance(value, dict) or not isinstance(value.get('summary'), str) or not 1 <= len(value['summary'].strip()) <= 1000:
            raise ModelContractError('intent.summary must be a short public requirements summary')
        result = {'summary': value['summary'].strip()}
        for key in ('goals', 'constraints', 'steps'):
            entries = value.get(key, [])
            if not isinstance(entries, list) or len(entries) > 6 or any(not isinstance(v, str) or not 1 <= len(v.strip()) <= 300 for v in entries):
                raise ModelContractError('intent.' + key + ' must contain at most 6 short strings')
            result[key] = [v.strip() for v in entries]
        return dict(result, status='ready')

    def prepare(self, goal, context, settings, checkpoint, save, progress, on_call=None):
        # Conversation changes on retry; keep the original brief for the same
        # goal, project settings and model. The brief contains no source patches.
        signature = hashlib.sha256(json.dumps({'goal': goal,
            'context': {k:v for k,v in context.items() if k != 'conversation'},
            'model': {k:settings.get(k) for k in ('provider','model','base_url')}}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        cached = checkpoint.get('intent') if checkpoint.get('intent_signature') == signature else None
        progress({'stage':'正在理解你的需求…'})
        if cached and cached.get('status') == 'ready':
            intent = self.validate(cached)
        elif settings.get('provider') in ('local', '', None):
            intent = {'status':'unavailable', 'summary':'当前为本地演示模式，未调用模型理解需求；将按原始消息处理。', 'goals':[], 'constraints':[], 'steps':[]}
        else:
            intent = self._request(goal, context, settings, on_call)
        checkpoint = dict(checkpoint, intent=intent, intent_signature=signature)
        save(checkpoint)
        progress({'stage':'需求已理解，正在继续处理' if intent['status']=='ready' else '正在按原始需求处理', 'intent':intent})
        return checkpoint

    def _request(self, goal, context, settings, on_call):
        if not settings.get('base_url') or not settings.get('api_key'):
            raise ValueError('所选模型缺少服务地址或 API Key，请在模型设置中补全配置')
        endpoint = settings['base_url'].rstrip('/')
        if not endpoint.endswith('/chat/completions'): endpoint += '/chat/completions'
        system = ('你是需求理解助手。只输出 JSON：summary（面向用户的简短中文行动摘要）、goals、constraints、steps（各最多6条短句）。'
            '先理解当前消息，并结合项目说明、最近对话及归档摘要解析“它、继续、改成”等指代，当前消息优先。'
            'summary 用1到3句自然语言说明你理解的目标、范围和下一步，例如“我会增加删除入口和二次确认，并保留最近15轮对话原文，较早内容归档为摘要。”'
            '准确保留用户明确的数字、名称、边界和禁止事项，不擅自增加需求；未知信息不得声称已经确认。'
            '这是公开的需求与行动摘要，不输出内部推理、思维链、源代码、工具调用，也不要声称已读取文件、执行命令或完成修改。'
            '如果没有绑定项目，只说明如何回答或分析，不承诺操作工程。简单问候简短回应意图，不虚构实施计划。')
        for attempt in range(2):
            try:
                raw = self.model._request_completion(endpoint, settings, system,
                    json.dumps({'phase':'understand','goal':goal,'context':context}, ensure_ascii=False),
                    max_tokens=900, on_model_call=on_call, request_timeout=30)
                return self.validate(self.model._parse_content(raw))
            except ModelRequestError as exc:
                if not exc.retryable: break
            except (ModelContractError, ValueError, TypeError, KeyError):
                pass
        return {'status':'unavailable', 'summary':'暂时未能生成需求摘要，将直接按你的原始需求继续处理。', 'goals':[], 'constraints':[], 'steps':[]}
