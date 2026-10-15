"""Versioned project design policy; source files cannot relax an approved policy."""
import copy
import json
from fnmatch import fnmatch

CONTRACT_FILE = 'design-contract.json'
DEFAULT_CONTRACT = {
    'schema': 'codespider.design/v1', 'mode': 'advisory', 'require_design': False,
    'layers': [], 'require_layer_assignment': False, 'forbidden_imports': {},
    'exclude': ['test_*.py', '*/test_*.py', 'tests/*', 'src/test/*', '*.spec.js', '*.test.js', '*.spec.ts', '*.test.ts'],
    'limits': {'function_lines': 60, 'parameters': 6, 'class_methods': 15, 'module_fan_out': 8},
}
DESIGN_GUIDANCE = """Respect existing architecture and public APIs; keep changes proportional to the use case.
Use context.structure for existing function/class declarations, call evidence and module dependency direction.
Its evidence is bounded and parser capabilities are explicit; never treat an omitted edge as proof of no dependency.
Apply single responsibility, separation of concerns, high cohesion and low coupling: keep related behavior together,
use explicit inputs/outputs/errors and constructor/function dependency injection at real external boundaries.
Apply interface segregation: expose small capabilities clients actually use. Substitutable implementations must honor
the same input validity, output invariants and error contracts (Liskov substitution); test them through the client.
Prefer composition over inheritance and reuse existing validation/domain functions rather than duplicating business rules.
Keep HTTP controllers and Vue views thin; put business rules in services/domain functions, data access in repositories
or API clients. MVC is appropriate for Spring MVC; Vue uses components/composables/services rather than backend MVC.
Use Strategy for existing variable algorithms, Adapter for external APIs and Repository for actual persistence needs.
Explain why each selected pattern is needed; do not create empty layers, global service locators or speculative factories.
Prefer small composable functions, explicit contracts, no circular imports, and behavior tests with replaceable collaborators.
Preserve specified exception types and validation order. Test invalid inputs before external effects and independent instances.
Integration tests must exercise real composition, not duplicate business algorithms in fake collaborators.
In Spring MVC, use full context integration tests for actual bean wiring or isolated slices with explicit replacements;
do not register duplicate beans with the same name in Application and test configuration to simulate injection.
Treat design-contract.json as configuration only. Never generate or modify it to make a failing design pass.
Return design: {modules:[{path,responsibility,depends_on:[project_relative_path]}],
interfaces:[{path,symbol,inputs,outputs,errors}], patterns:[{name,reason}]}.
Document every changed production source module and its meaningful public interfaces. Use qualified Python Class.method
names for methods. The design is a concise public engineering artifact, not private reasoning.
"""


def load_contract(files):
    raw = files.get(CONTRACT_FILE)
    if raw is None:
        return copy.deepcopy(DEFAULT_CONTRACT)
    try:
        value = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise ValueError('invalid design-contract.json: %s' % exc)
    if not isinstance(value, dict) or set(value) - set(DEFAULT_CONTRACT):
        raise ValueError('unknown design contract fields')
    result = copy.deepcopy(DEFAULT_CONTRACT)
    result.update(value)
    if result['schema'] != DEFAULT_CONTRACT['schema'] or result['mode'] not in ('advisory', 'enforce'):
        raise ValueError('unsupported design contract schema or mode')
    for name in ('require_design', 'require_layer_assignment'):
        if type(result[name]) is not bool:
            raise ValueError('%s must be boolean' % name)
    if not isinstance(result['exclude'], list) or len(result['exclude']) > 50 or not all(isinstance(x,str) and x and len(x)<200 for x in result['exclude']):
        raise ValueError('exclude must contain bounded path patterns')
    limits = value.get('limits', {})
    if not isinstance(limits, dict) or set(limits) - set(DEFAULT_CONTRACT['limits']):
        raise ValueError('unknown design metric limits')
    if any(type(v) is not int or not 1 <= v <= 500 for v in limits.values()):
        raise ValueError('design metric limits must be integers in 1..500')
    result['limits'] = dict(DEFAULT_CONTRACT['limits'], **limits)
    layers = result['layers']
    if not isinstance(layers, list) or len(layers)>30:
        raise ValueError('layers must be an array of at most 30 items')
    names = []
    for layer in layers:
        if not isinstance(layer,dict) or set(layer) != {'name','paths','may_depend_on'}:
            raise ValueError('layer requires name, paths and may_depend_on')
        if not isinstance(layer['name'],str) or not layer['name'] or len(layer['name'])>80:
            raise ValueError('invalid layer name')
        names.append(layer['name'])
        for key in ('paths','may_depend_on'):
            if not isinstance(layer[key],list) or not all(isinstance(x,str) and x and len(x)<200 for x in layer[key]):
                raise ValueError('invalid layer '+key)
        if not layer['paths']:
            raise ValueError('layer paths cannot be empty')
    if len(names)!=len(set(names)) or any(set(x['may_depend_on'])-set(names) for x in layers):
        raise ValueError('duplicate or unknown layer name')
    forbidden = result['forbidden_imports']
    if not isinstance(forbidden, dict) or set(forbidden)-set(names):
        raise ValueError('forbidden_imports must use declared layer names')
    for prefixes in forbidden.values():
        if not isinstance(prefixes, list) or len(prefixes)>100 or not all(isinstance(p,str) and p and len(p)<200 for p in prefixes):
            raise ValueError('forbidden_imports requires bounded import prefixes')
    return result


def validate_design(design, files, changed_paths, report, required=False, excluded_paths=()):
    if design is None and not required:
        return
    if not isinstance(design,dict) or set(design) != {'modules','interfaces','patterns'}:
        raise ValueError('design requires modules, interfaces and patterns arrays')
    for key in design:
        if not isinstance(design[key],list) or len(design[key])>200:
            raise ValueError('design '+key+' must be a bounded array')
    documented = set()
    for module in design['modules']:
        if not isinstance(module,dict) or set(module) != {'path','responsibility','depends_on'}:
            raise ValueError('design module requires path, responsibility, depends_on')
        path = module['path']
        if not isinstance(path,str) or path not in files or path in documented:
            raise ValueError('design module path must exist and be unique')
        documented.add(path)
        _text(module['responsibility'], 'module '+path+' responsibility')
        if not isinstance(module['depends_on'],list) or any(not isinstance(p,str) or p not in files for p in module['depends_on']):
            raise ValueError('design dependencies must name existing project paths')
    production = {m['path'] for m in report['modules']}
    if set(changed_paths) & production - documented:
        raise ValueError('design missing changed module responsibilities: '+', '.join(sorted(set(changed_paths) & production - documented)))
    excluded_modules = {}
    for interface in design['interfaces']:
        if not isinstance(interface,dict) or set(interface) != {'path','symbol','inputs','outputs','errors'}:
            raise ValueError('design interface requires path, symbol, inputs, outputs, errors')
        for key in ('path', 'symbol'): _text(interface[key])
        for key in ('inputs', 'outputs', 'errors'):
            value = interface[key]
            if isinstance(value, str):
                # Providers also express no arguments/no error contract as an
                # empty string. Outputs and missing fields remain mandatory.
                if value != '' or key not in ('inputs', 'errors'):
                    _text(value, 'interface '+interface['path']+' '+interface['symbol']+' '+key)
            elif not isinstance(value, (dict, list)) or len(json.dumps(value, ensure_ascii=False)) > 4000:
                raise ValueError('interface descriptions must be bounded text, objects or arrays')
        module = next((m for m in report['modules'] if m['path']==interface['path']), None)
        # Exclusion from production metrics does not mean a documented test
        # symbol is missing. Check its source without adding it to those metrics.
        path = interface['path']
        if module is None and path in files and any(fnmatch(path, pattern) for pattern in excluded_paths):
            if path not in excluded_modules:
                from code_intelligence.structure import review_structure
                evidence = review_structure({path:files[path]}, dict(DEFAULT_CONTRACT, exclude=[]))
                excluded_modules[path] = next(iter(evidence['modules']), None)
            module = excluded_modules[path]
        if not module or interface['symbol'] not in {name for s in module['symbols'] for name in (s['name'],s.get('qualified_name'))}:
            raise ValueError('design interface symbol was not found: '+interface['symbol'])
    for pattern in design['patterns']:
        if not isinstance(pattern,dict) or set(pattern) != {'name','reason'}:
            raise ValueError('design pattern requires name and reason')
        _text(pattern['name']); _text(pattern['reason'])
    if required and production & set(changed_paths) and not any(i['path'] in production for i in design['interfaces']):
        raise ValueError('design requires at least one public interface contract')


def _text(value, field='description'):
    if not isinstance(value,str) or not value.strip() or len(value)>4000:
        raise ValueError('design descriptions must be non-empty bounded strings: '+field)


def review_proposal(context, patches, design=None, check_design=True, raise_on_block=True):
    from code_intelligence.structure import review_structure
    files = dict(context.get('files', {}))
    contract = context.get('design_contract') or load_contract(files)
    for patch in patches:
        if patch['path'] == CONTRACT_FILE:
            raise ValueError('Design policy cannot be changed by a code generation task; edit it explicitly before generating')
        files[patch['path']] = patch.get('replacement', patch.get('content', ''))
    report = review_structure(files, contract, context.get('structure_incomplete', False))
    if report['blocking'] and raise_on_block:
        errors = [f['message'] for f in report['findings'] if f['severity']=='error']
        raise ValueError('design contract violation: '+'; '.join(errors[:5]))
    if check_design:
        validate_design(design,files,[p['path'] for p in patches],report,contract['require_design'],contract['exclude'])
    return report
