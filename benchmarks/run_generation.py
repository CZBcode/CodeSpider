"""Real model -> task approval -> Agent files/build/tests -> independent oracles.

Run only in a trusted, disposable execution environment: generated code executes.
No score is awarded for prose, keyword matches, or an empty patch list.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.app import AppContext
from backend.model_gateway import ModelGateway
from backend.tool_protocol import ToolRequest
from benchmarks.generation_cases import CASES
from benchmarks.engineering_cases import CASES as ENGINEERING_CASES


def run_case(case, destination, settings, replay=None, repair_from=None):
    base = destination / case['id']
    project = base / 'project'
    project.mkdir(parents=True, exist_ok=False)
    for path, content in case.get('seed', {}).items():
        target = project / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    if repair_from:
        original = repair_from / case['id'] / 'project'
        for source in original.rglob('*'):
            relative = source.relative_to(original)
            if not source.is_file() or source.is_symlink() or any(p in ('target','node_modules','dist','.codespider','__pycache__') for p in relative.parts): continue
            if str(relative) == case['oracle_path']: continue
            target = project / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    context = AppContext(str(base / 'state'))
    attempts = []
    request_completion = context.tasks.model._request_completion
    def recorded_completion(*args, **kwargs):
        raw = request_completion(*args, **kwargs)
        attempts.append(raw)
        (base / ('model-attempt-%d.json' % len(attempts))).write_text(raw)
        return raw
    context.tasks.model._request_completion = recorded_completion
    started = time.monotonic()
    result = {'id': case['id'], 'passed': False, 'model': settings['model'], 'goal': case['goal'],
              'generation_source': 'saved_model_patches' if replay else 'live_model_repair' if repair_from else 'live_model'}
    try:
        workspace = context.workspaces.create(str(project), description=case['description'])
        if replay:
            source = replay / case['id'] / 'proposed-task.json'
            if source.exists():
                saved = json.loads(source.read_text())
            else:
                candidates = sorted((replay / case['id']).glob('model-attempt-*.json'))
                if not candidates: raise ValueError('no saved model output to replay')
                saved = ModelGateway.validate_turn(ModelGateway._parse_content(candidates[-1].read_text()))
                result['generation_source'] = 'saved_model_response'
            current = context.tools.call(ToolRequest('code','context',workspace_id=workspace.id,approval={'approved':True}))
            if not current.ok: raise ValueError('cannot read replay context')
            ModelGateway.validate_generation(saved, current.data)
            task = context.tasks.create(workspace.id, case['goal'], patches=saved['patches'])
            task.design = saved.get('design', {})
            task.design_contract = current.data['design_contract']
            context.tasks._save_task(task)
        else:
            task = context.tasks.create(workspace.id, case['goal'], model_settings=settings, context_approved=True)
        result['patch_count'] = len(task.patches)
        if not task.patches:
            raise ValueError('no generated files')
        (base / 'proposed-task.json').write_text(json.dumps(task.to_dict(), ensure_ascii=False, indent=2))
        # Approval in this harness covers only these disposable generated projects.
        context.tasks.approve(task.id)
        context.tasks.executor.shutdown(wait=True)
        task = context.tasks.get(task.id)
        result['task_status'] = task.status
        result['design_review'] = task.design_review
        (base / 'design.json').write_text(json.dumps(task.design, ensure_ascii=False, indent=2))
        (base / 'structure.json').write_text(json.dumps(task.design_review, ensure_ascii=False, indent=2))
        (base / 'events.json').write_text(json.dumps([e.to_dict() for e in context.tasks.events(task.id)], ensure_ascii=False, indent=2))
        if task.status != 'succeeded':
            raise RuntimeError(task.error or task.status)
        oracle = project / case['oracle_path']
        if oracle.exists():
            raise ValueError('generated code conflicts with independent acceptance test')
        oracle.parent.mkdir(parents=True, exist_ok=True)
        oracle.write_text(case['oracle'])
        completed = subprocess.run(case['command'], cwd=project, capture_output=True, text=True, timeout=180)
        result['acceptance_exit_code'] = completed.returncode
        (base / 'acceptance.log').write_text(completed.stdout + completed.stderr)
        if oracle.read_text() != case['oracle']:
            raise ValueError('acceptance test was changed during execution')
        if completed.returncode:
            raise RuntimeError('independent acceptance tests failed; see acceptance.log')
        preserved = case.get('preserve_paths', [])
        for path in preserved:
            if (project/path).read_text() != case['seed'][path]:
                raise ValueError('protected existing module changed: '+path)
        if preserved: result['preserved_files'] = preserved
        if case['id'] == 'python-repair':
            current = (project / 'cart.py').read_text()
            for original in ('Keep public API and this module documentation.', 'LABEL = "total_cents is the public API"', '# Keep this comment: currency contract v1.'):
                if original not in current:
                    raise ValueError('existing API documentation or constant was lost')
        result['passed'] = True
    except Exception as exc:
        result['error'] = str(exc)
    finally:
        context.tasks.executor.shutdown(wait=True)
        context.processes.close()
        context.close()
    result['seconds'] = round(time.monotonic() - started, 2)
    result['model_responses'] = len(attempts)
    result['files'] = {str(p.relative_to(project)): hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in project.rglob('*') if p.is_file() and not any(part in ('node_modules','target','dist','.codespider','__pycache__') for part in p.relative_to(project).parts)}
    (base / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--settings-file', help='private provider settings JSON; never included in reports')
    parser.add_argument('--output', required=True, help='new output directory; existing projects are never overwritten')
    parser.add_argument('--suite', choices=['generation', 'engineering'], default='generation')
    parser.add_argument('--case', action='append', choices=[c['id'] for c in CASES + ENGINEERING_CASES])
    parser.add_argument('--replay', type=Path, help='re-execute saved model patches from a prior run without new model calls')
    parser.add_argument('--repair-from', type=Path, help='copy a previous generated project and ask the model to modify it')
    parser.add_argument('--feedback-file', type=Path, help='explicit, reviewed failure feedback appended to the goal')
    parser.add_argument('--execute', action='store_true', help='authorize model calls and execution in disposable projects')
    args = parser.parse_args()
    if not args.execute:
        parser.error('--execute is required because this benchmark executes generated code')
    if args.replay and args.repair_from: parser.error('replay and repair-from are mutually exclusive')
    settings = json.loads(Path(args.settings_file).read_text()) if args.settings_file else {
        'provider': 'custom', 'base_url': os.environ['CODESPIDER_MODEL_BASE_URL'],
        'api_key': os.environ['CODESPIDER_MODEL_API_KEY'], 'model': os.environ['CODESPIDER_MODEL']}
    settings['max_tokens'] = max(16384 if args.suite == 'engineering' else 8192, int(settings.get('max_tokens', 8192)))
    destination = Path(args.output).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    report = {'model': settings['model'], 'evaluation': 'executed-generation-v1', 'results': []}
    for case in ENGINEERING_CASES if args.suite == 'engineering' else CASES:
        if args.case and case['id'] not in args.case:
            continue
        print('RUN', case['id'], flush=True)
        case = dict(case)
        if args.feedback_file:
            case['goal'] += '\nRepair feedback (do not remove or weaken assertions):\n' + args.feedback_file.read_text()
        result = run_case(case, destination, settings, args.replay, args.repair_from)
        report['results'].append(result)
        report['passed'] = sum(r['passed'] for r in report['results'])
        report['total'] = len(report['results'])
        (destination / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print('PASS' if result['passed'] else 'FAIL', case['id'], result.get('error', ''), flush=True)
    return 0 if report['passed'] == report['total'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
