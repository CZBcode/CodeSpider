"""Generate a reviewed manifest, then one file per bounded model request.

Checkpoints contain proposals only. No generated file is executed or written
until the normal task approval and design checks have succeeded.
"""
import hashlib
import json
import time
from backend.model_gateway import ModelContractError, ModelRequestError
from backend.patch_contract import PatchContract
from backend.generation_repair import GenerationRepair
from code_intelligence.design_contract import DESIGN_GUIDANCE


class ProjectGenerator:
    MAX_FILES = 48

    def __init__(self, model):
        self.model = model

    @staticmethod
    def needed(goal):
        text = goal.lower()
        return len(goal) > 600 or any(w in text for w in (
            '系统', '工程', '项目', '应用', '网站', 'project', 'application', 'system', 'full stack'))

    def generate(self, goal, context, settings, on_call=None, progress=None, checkpoint=None, save=None):
        if not settings.get('base_url') or not settings.get('api_key'):
            raise ValueError('所选模型缺少服务地址或 API Key，请在模型设置中补全配置')
        progress = progress or (lambda value: None)
        save = save or (lambda value: None)
        # Scope is supplied by GenerationService; content/model changes invalidate
        # proposals instead of applying stale patches or reusing another model.
        signature = hashlib.sha256(json.dumps({'goal':goal, 'context':{k:v for k,v in context.items() if k!='conversation'},
            'model':settings.get('model'), 'base_url':settings.get('base_url'),
            'temperature':settings.get('temperature'), 'max_tokens':settings.get('max_tokens')},
            ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        checkpoint = checkpoint or {}
        cached = checkpoint if checkpoint.get('signature') == signature else {}
        # Older versions erased the signature after final validation. These
        # server-owned drafts may be recovered only after rechecking every path
        # and disk precondition below, before replacing the saved checkpoint.
        if checkpoint.get('signature') == '' and checkpoint.get('validation_failed') is True:
            cached = checkpoint
        if cached.get('conversation') is not None:
            context = dict(context, conversation=cached['conversation'])
        endpoint = settings['base_url'].rstrip('/')
        if not endpoint.endswith('/chat/completions'): endpoint += '/chat/completions'

        def request(system, payload, validate, label, tokens=5000):
            previous = ''
            for attempt in range(3):
                progress({'stage':label, 'attempt':attempt+1, 'max_attempts':3})
                try:
                    raw = self.model._request_completion(endpoint, settings, system,
                        json.dumps(payload,ensure_ascii=False) + ('\nCorrect the previous error: '+previous[:500] if previous else ''),
                        max_tokens=min(tokens,max(1024,int(settings.get('max_tokens',8192)))), on_model_call=on_call)
                    return validate(self.model._parse_content(raw))
                except ModelRequestError as exc:
                    if not exc.retryable or attempt == 2:
                        raise RuntimeError('模型暂时没有完成当前批次，已保存先前进度。请点击“继续生成”重试。') from exc
                    previous = 'Request interrupted; return a complete small response.'
                    time.sleep(.5 * (2 ** attempt))
                except (ModelContractError, ValueError, TypeError, KeyError) as exc:
                    previous = str(exc)
                    if attempt == 2:
                        raise RuntimeError('当前批次输出未通过完整性检查，已保留先前进度。请继续生成或缩小单个模块范围。') from exc
            raise RuntimeError('generation did not finish')

        def validate_manifest(value):
            if not isinstance(value,dict) or not isinstance(value.get('summary'),str) or not value['summary'].strip():
                raise ModelContractError('manifest requires a summary')
            files=value.get('files')
            if not isinstance(files,list) or not 1 <= len(files) <= self.MAX_FILES:
                raise ModelContractError('manifest requires 1 to 48 files; split a larger scope into modules')
            seen=set()
            for item in files:
                if not isinstance(item,dict) or not isinstance(item.get('contract'),str) or not item['contract'].strip():
                    raise ModelContractError('each file needs a concrete public interface contract')
                path=item.get('path')
                PatchContract._validate_patch({'path':path,'operation':'create','replacement':''})
                if path in seen: raise ModelContractError('duplicate manifest path')
                if len(path)>240 or len(item['contract'])>2000: raise ModelContractError('manifest entry too large')
                seen.add(path)
                if path in context.get('file_paths',[]) and path not in context.get('files',{}):
                    raise ModelContractError('cannot modify an existing file that is absent from supplied source context: '+path)
            if len(json.dumps(value,ensure_ascii=False))>64000: raise ModelContractError('manifest too large')
            design=value.get('design')
            if design is not None and (not isinstance(design,dict) or set(design)!={'modules','interfaces','patterns'} or any(not isinstance(design[k],list) for k in design)):
                raise ModelContractError('design must contain modules, interfaces, patterns arrays')
            return value

        manifest = cached.get('manifest')
        if manifest:
            manifest=validate_manifest(manifest)
            recovered=self.model.validate_turn({'summary':'检查保存的草稿','patches':cached.get('patches',[])})
            if recovered['patches']:
                self.model.validate_generation(recovered,{k:v for k,v in context.items() if k!='design_contract'})
            if any(p['path'] not in {f['path'] for f in manifest['files']} for p in recovered['patches']):
                raise ModelContractError('saved draft contains paths outside manifest')
        else:
            manifest=request(
                'You are a software architect. Return ONE JSON object with summary, design, files. '
                'Each files item has path and contract (exact exported classes/functions, signatures, imports, API routes, data fields, dependencies, and behavior). '
                'Do not output source code. Plan all requested features, plugin-required verification/build files and README, at most 48 files. '
                'Order dependencies before consumers. Keep each file small with one responsibility. '
                'Resolve every nonstandard type to an explicit build dependency or a file in this manifest. '
                'Use fully qualified names for shared exceptions. For in-memory repositories prefer standard-library exceptions; do not silently require an ORM. '
                'Test constructors, mock types and method signatures must match the implementation contracts exactly. '
                'Use context.plugin, context.skills, source interfaces, design_contract and recent conversation. '
                'Carry context.intent goals and constraints into the file contracts; original user requirements override any conflicting brief. '
                'List only production symbols in design.interfaces; test classes and test methods are excluded from the structural index. '
                'Preserve exact user requirements; use one selected engineering stack. Define shared API/domain contracts consistently. '
                'Existing files may only be modified if present in context.files. Keep each contract concise. Do not claim execution.\n'+DESIGN_GUIDANCE,
                {'goal':goal,'context':context}, validate_manifest, '正在拆分需求与设计文件契约',6000)
        patches=[]
        cached_patches={p['path']:p for p in cached.get('patches',[])}
        state={'signature':signature,'manifest':manifest,'patches':patches,'conversation':context.get('conversation')}
        for key in ('repair','validation_failed'):
            if key in cached: state[key]=cached[key]
        # Keep the complete persisted draft until reconstruction has finished.
        if not cached_patches: save(state)
        for index,item in enumerate(manifest['files']):
            path=item['path']
            progress({'stage':'正在生成 '+path,'completed':index,'total':len(manifest['files']), 'path':path})
            def validate_file(value):
                turn=self.model.validate_turn(value)
                if len(turn['patches'])!=1 or turn['patches'][0]['path']!=path:
                    raise ModelContractError('return exactly one patch for '+path)
                self.model.validate_generation(turn,{k:v for k,v in context.items() if k!='design_contract'})
                return turn['patches'][0]
            if path in cached_patches:
                patch=validate_file({'summary':'恢复已完成批次','patches':[cached_patches[path]]})
            else:
                # The manifest carries the complete cross-file contract. Include
                # bounded concrete dependency code to preserve imports/signatures.
                dependencies={}; budget=48000
                # Keep build declarations visible even when newer source files
                # have filled the context budget.
                build_names={'pom.xml','build.gradle','build.gradle.kts','package.json','pyproject.toml','requirements.txt'}
                ordered=[p for p in patches if p['path'].rsplit('/',1)[-1] in build_names]
                ordered += [p for p in reversed(patches) if p['path'].rsplit('/',1)[-1] not in build_names]
                for old in ordered:
                    content=old['replacement']
                    if len(content)<=budget:
                        dependencies[old['path']]=content; budget-=len(content)
                payload={'goal':goal,'context':context,'manifest':manifest,
                    'current_file':item,'proposed_dependencies':dependencies}
                patch=request(self.model._system_prompt() +
                    '\nThis is ONE FILE of a staged project. Return exactly one patch for current_file.path. '
                    'Implement its entire contract; other manifest files are generated separately. '
                    'Follow shared class/function signatures and import paths exactly. Do not output patches for dependencies. '
                    'Concrete proposed dependency code takes precedence over inconsistent manifest descriptions. '
                    'Only import libraries available in the supplied build declarations. Match test constructors and mock types to the generated implementation. '
                    'proposed_dependencies are uncommitted proposals, not files on disk. Never claim execution.',
                    payload,validate_file,'正在生成 %s/%s：%s' % (index+1,len(manifest['files']),path),6000)
            patches.append(patch)
            if not cached_patches or index+1 == len(manifest['files']) or path not in cached_patches:
                save(state)
            progress({'stage':'已生成 '+path,'completed':index+1,'total':len(manifest['files']), 'path':path})
        turn=self.model.validate_turn({'summary':manifest['summary'], 'design':manifest.get('design'),
            'steps':[{'step':1,'title':'审查生成内容','action':'review','detail':'分批生成 %s 个文件，批准后统一写入并验证。'%len(patches)}],
            'thinking':[], 'tool_calls':[], 'patches':patches})
        turn=GenerationRepair(self.model,request,save,progress).converge(turn,context,state,goal)
        progress({'stage':'全部文件已生成，等待审批与工程验证','completed':len(patches),'total':len(patches)})
        return turn
