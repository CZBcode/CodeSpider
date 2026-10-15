"""Versioned capabilities and durable per-user installation/preferences."""
from copy import deepcopy
import re
import uuid
from engineering_plugins.registry import plugins
from backend.function_registry import descriptors

BUILTIN_SKILLS = [
    {'id':'skill.design-contracts','kind':'skill','name':'设计契约与职责分离','version':'1.0.0',
     'description':'检查 MVC、职责边界、高内聚低耦合和设计契约。','keywords':['设计模式','职责','mvc','高内聚','低耦合','架构'],
     'instructions':'Keep controllers thin, business rules in services/domain modules, persistence behind repositories. Prefer explicit interfaces and dependency injection. Preserve the supplied design-contract.json; changes must pass structural review.'},
    {'id':'skill.test-first','kind':'skill','name':'工程化验证','version':'1.0.0',
     'description':'用可执行的行为测试验证工程，而非只检查编译。','keywords':['测试','test','验证','回归','可靠'],
     'instructions':'Implement tests for externally observable behavior, errors and boundaries. Preserve exact requested API values and names. Run the plugin verification commands. Do not replace failing behavioral tests with syntax-only checks.'},
    {'id':'skill.ast-context','kind':'skill','name':'AST 代码理解','version':'1.0.0',
     'description':'先根据符号和调用结构定位函数、类和模块，再生成补丁。','keywords':['函数','类','模块','代码理解','重构','function','class'],
     'instructions':'Use supplied symbols, file hashes and structure to locate public interfaces and dependent modules. Preserve signatures and imports unless the user requests a change. Never patch unseen files.'},
]


def matches(text, keyword):
    # Token boundaries stop py matching copy, or java matching javascript.
    if re.fullmatch(r'[a-z0-9 ._-]+', keyword):
        return bool(re.search(r'(?<![a-z0-9_])' + re.escape(keyword) + r'(?![a-z0-9_])', text))
    return keyword in text


def plugin_matches(text, keyword):
    """Don't recommend a stack from an explicit '不用 Vue / without Vue'."""
    pattern = re.escape(keyword)
    if re.fullmatch(r'[a-z0-9 ._-]+', keyword):
        pattern = r'(?<![a-z0-9_])' + pattern + r'(?![a-z0-9_])'
    for match in re.finditer(pattern, text):
        prefix = text[max(0, match.start()-30):match.start()]
        if not re.search(r'(?:不要|不用|不使用|无需|不需要|不采用|不依赖|不引入|非|\bwithout|\bno|\bnot|\bdo not use|\bdon.t use)\s*$', prefix):
            return True
    return False


class MarketService:
    def __init__(self, store, account_store=None):
        # Web and Agent read the same atomic store, never process-global user state.
        self.store = store

    @staticmethod
    def _all_builtin():
        return deepcopy([p.MANIFEST for p in plugins()] + BUILTIN_SKILLS + descriptors())

    def catalog(self, owner_id=''):
        prefs = {p['item_id']:p for p in self.store.read('market_preferences', []) if p['user_id'] == owner_id}
        items = self._all_builtin()
        items += [deepcopy(s) for s in self.store.read('user_skills', []) if s['user_id'] == owner_id and owner_id]
        for item in items:
            pref = prefs.get(item['id'], {})
            item['installed'] = pref.get('installed', True)
            item['enabled'] = item['installed'] and pref.get('enabled', True)
            item['personal'] = 'user_id' in item
            item.pop('user_id', None)
        return dict(items=items, **{plural:[x for x in items if x['kind']==kind] for plural,kind in
                                   [('plugins','plugin'),('skills','skill'),('functions','function')]})

    def by_id(self, item_id, owner_id=''):
        return next((item for item in self.catalog(owner_id)['items'] if item['id'] == item_id), None)

    def require(self, item_id, owner_id, kind=None):
        item = self.by_id(item_id, owner_id)
        if not item or (kind and item['kind'] != kind):
            raise KeyError('market item not found')
        if not item['enabled']:
            raise ValueError('请先安装并启用市场能力：' + item['name'])
        return item

    def set_enabled(self, owner_id, item_id, enabled, installed=None):
        if type(enabled) is not bool or (installed is not None and type(installed) is not bool):
            raise ValueError('enabled and installed must be boolean')
        item = self.by_id(item_id, owner_id)
        if not item:
            raise KeyError('market item not found')
        record = {'user_id':owner_id, 'item_id':item_id, 'enabled':enabled,
                  'installed':item['installed'] if installed is None else installed, 'version':item.get('version','1.0.0')}
        if enabled and not record['installed']:
            raise ValueError('请先安装该能力')
        self.store.update('market_preferences', [], lambda items: [p for p in items if not
            (p['user_id']==owner_id and p['item_id']==item_id)] + [record])
        return record

    def add_skill(self, owner_id, payload):
        name, instructions = payload.get('name',''), payload.get('instructions','')
        keywords, description = payload.get('keywords',[]), payload.get('description','')
        if not isinstance(name,str) or not 1 <= len(name.strip()) <= 120 or not isinstance(instructions,str) or not 1 <= len(instructions.strip()) <= 20000:
            raise ValueError('Skill 名称和执行指导不能为空或超出长度限制')
        if not isinstance(description,str) or len(description)>2000 or not isinstance(keywords,list) or len(keywords)>30 or any(not isinstance(k,str) or not 1<=len(k.strip())<=100 for k in keywords):
            raise ValueError('Skill 描述或关键词格式不正确')
        item={'id':'skill.user.'+uuid.uuid4().hex[:12], 'kind':'skill','version':'1.0.0','user_id':owner_id,
              'name':name.strip(),'description':description.strip(),'instructions':instructions.strip(),
              'keywords':[k.strip().lower() for k in keywords]}
        self.store.append('user_skills',item)
        return self.by_id(item['id'],owner_id)

    def select(self, goal, project_type='unknown', owner_id='', plugin_id=''):
        text=str(goal or '').lower()
        catalog=self.catalog(owner_id)
        existing=next((p for p in catalog['plugins'] if project_type in p['project_types']),None)
        ranked=sorted([(sum(plugin_matches(text,k) for k in p['keywords']),
                        sum(plugin_matches(text,k) for k in p.get('intent_keywords',[])), p)
                       for p in catalog['plugins']],
                      key=lambda pair:(pair[0] > 0, pair[0], pair[1], pair[2].get('recommendation_priority',0)), reverse=True)
        # Explicit stack names take precedence over generic overlapping words
        # such as "前端", "组件" or "后台". Metadata belongs to each plugin.
        preferred = lambda p: sum(plugin_matches(text, k) for k in p.get('preferred_keywords', []))
        ranked.sort(key=lambda item: preferred(item[2]), reverse=True)
        mentioned=[p for explicit, intent, p in ranked if explicit]
        if ranked and preferred(ranked[0][2]):
            mentioned = [p for p in mentioned if preferred(p)]
        plugin=None; reason='generic'; recommendation=''; requires_choice=False
        if existing:
            plugin=self.require(existing['id'],owner_id,'plugin'); reason='project_type'
            recommendation='沿用现有'+plugin['name']+'，保持现有依赖与接口兼容。'
            if plugin_id and plugin_id != existing['id']:
                raise ValueError('当前目录已有'+plugin['name']+'，切换技术栈请创建独立项目。')
        elif plugin_id:
            plugin=self.require(plugin_id,owner_id,'plugin'); reason='user_selected'
            recommendation='本次使用已确认的'+plugin['name']+'。'
        elif ranked and (ranked[0][0] or ranked[0][1]):
            plugin=self.require(ranked[0][2]['id'],owner_id,'plugin')
            reason='semantic' if ranked[0][0] else 'intent'
            recommendation='推荐'+plugin['name']+'：'+plugin.get('recommendation',plugin.get('description','适合当前需求。'))
            requires_choice=len(mentioned)>1
        elif any(word in text for word in ('创建','实现','开发','生成','搭建','build','create','implement')):
            available=[p for _,_,p in ranked if p['enabled']]
            if available:
                plugin=max(available,key=lambda p:p.get('recommendation_priority',0)); reason='recommended_default'
                recommendation='未指定技术栈，建议先使用'+plugin['name']+'。'+plugin.get('recommendation','')
                requires_choice=True
        if requires_choice:
            recommendation+=' 检测到多种可选方案；当前支持单个工程插件，前后端组合建议拆分为独立项目。请确认本项目的技术栈。'
        selected=lambda kind:[x for x in catalog[kind] if x['enabled'] and any(matches(text,k) for k in x.get('keywords',[]))]
        return {'plugin':plugin,'skills':selected('skills')[:6],'functions':selected('functions'), 'selection':reason,
                'recommendation':recommendation,'requires_choice':requires_choice,
                'alternatives':[{'id':p['id'],'name':p['name'],'enabled':p['enabled']} for _,_,p in ranked]}
