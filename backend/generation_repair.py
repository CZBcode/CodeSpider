"""Bounded, resumable repair of proposals; never writes or executes source."""
from backend.model_gateway import ModelContractError
from code_intelligence.design_contract import DESIGN_GUIDANCE, review_proposal
from code_intelligence.structure import summarize_structure


class GenerationRepair:
    MAX_ROUNDS = 3
    MAX_FILES = 3

    def __init__(self, model, request, save, progress):
        self.model, self.request, self.save, self.progress = model, request, save, progress

    def converge(self, turn, context, state, goal):
        repair = state.setdefault('repair', {'round': 0, 'history': []})
        for attempt in range(self.MAX_ROUNDS + 1):
            # Finish a saved repair plan before reviewing partially repaired code.
            if repair.get('pending'):
                self._files(turn, context, state, goal)
            try:
                self.model.validate_generation(turn, context)
                repair.update(status='completed', pending=[], error='')
                state['validation_failed'] = False
                self.save(state)
                return turn
            except (ValueError, ModelContractError) as exc:
                repair.update(status='repairing', error=str(exc)[:2000])
                state['validation_failed'] = True
                self.save(state)
            if attempt == self.MAX_ROUNDS:
                repair['status'] = 'paused'
                self.save(state)
                raise RuntimeError('本轮自动修复已达 3 轮，草稿和修复进度已保存。点击“继续修复”将从当前结果继续，不会从头生成。')
            report = review_proposal(context, turn['patches'], check_design=False, raise_on_block=False)
            repair['round'] += 1
            self.progress({'stage': '正在收敛设计与代码，第 %s 轮修复' % repair['round'],
                           'repairing': True, 'repair_round': repair['round']})
            paths = {p['path'] for p in turn['patches']}

            def validate_plan(value):
                if not isinstance(value, dict) or set(value) != {'design', 'files'}:
                    raise ModelContractError('repair requires design and files')
                design, files = value['design'], value['files']
                if (not isinstance(design, dict) or set(design) != {'modules', 'interfaces', 'patterns'}
                        or any(not isinstance(v, list) for v in design.values())):
                    raise ModelContractError('repair must preserve a complete design artifact')
                if (not isinstance(files, list) or len(files) > self.MAX_FILES
                        or any(not isinstance(p, str) or p not in paths or p == 'design-contract.json' for p in files)
                        or len(files) != len(set(files))):
                    raise ModelContractError('repair at most 3 existing proposal paths; never alter design policy')
                if not report['blocking'] and files:
                    raise ModelContractError('metadata-only failure: correct design without changing source')
                return value

            plan = self.request(
                'Repair an existing generated project, preserving the user requirements. Return JSON {design,files}. '
                'Use actual source evidence to correct design module responsibilities and exact interface symbols. '
                'Every interface outputs field must be nonempty: describe the created instance for constructors, '
                'or use void/no return value for operations without a return value. '
                'If structure is not blocking, change design metadata only and return files: []. '
                'For blocking source findings select at most 3 existing proposal paths to repair. '
                'Never remove features/tests, relax design policy, or claim execution.\n' + DESIGN_GUIDANCE,
                {'goal': goal, 'manifest': state['manifest'], 'error': repair['error'],
                 'structure': summarize_structure(report), 'blocking': report['blocking'],
                 'design_contract': context.get('design_contract')},
                validate_plan, '正在制定最小修复方案', 6000)
            turn['design'] = state['manifest']['design'] = plan['design']
            repair['pending'] = list(plan['files'])
            repair['history'] = (repair.get('history', []) + [
                {'round': repair['round'], 'error': repair['error'], 'files': list(plan['files'])}])[-12:]
            self.save(state)
        raise AssertionError('unreachable')

    def _files(self, turn, context, state, goal):
        repair = state['repair']
        while repair['pending']:
            path = repair['pending'][0]
            index = next(i for i, p in enumerate(turn['patches']) if p['path'] == path)
            original = turn['patches'][index]

            def validate_file(value):
                if not isinstance(value, dict) or set(value) != {'path', 'replacement'} or value['path'] != path:
                    raise ModelContractError('return path and full replacement for ' + path)
                # Preserve original disk preconditions, not the uncommitted draft.
                candidate = self.model.validate_turn({'summary': '修复草稿', 'patches': [dict(original, replacement=value['replacement'])]})
                self.model.validate_generation(candidate, {k: v for k, v in context.items() if k != 'design_contract'})
                return candidate['patches'][0]

            dependencies = {}; budget = 48000
            for patch in turn['patches']:
                content = patch['replacement']
                if patch['path'] != path and len(content) <= budget:
                    dependencies[patch['path']] = content
                    budget -= len(content)
            fixed = self.request(
                'Repair one existing proposal. Return JSON {path,replacement} with the complete file. '
                'Preserve features and tests, honor the manifest and design contract. '
                'Fix the reported structural errors without weakening validation or changing unrelated files.',
                {'goal': goal, 'manifest': state['manifest'], 'current_file': original,
                 'error': repair['error'], 'proposed_dependencies': dependencies,
                 'design_contract': context.get('design_contract')},
                validate_file, '正在修复 ' + path, 6000)
            turn['patches'][index] = fixed
            state['patches'] = turn['patches']
            repair['pending'].pop(0)
            self.save(state)
