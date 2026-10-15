"""Source-derived design evidence. Python AST; conservative Java/JS lexical evidence.

No code is imported or executed. Findings are not proof of semantic cohesion.
"""
import ast
from fnmatch import fnmatch
import posixpath
import re

SOURCE_SUFFIXES = ('.py', '.java', '.js', '.ts', '.vue')


def summarize_structure(report):
    """Bound model context separately from the full local review evidence."""
    symbols_left, calls_left = 120, 120
    result = {'metrics': report['metrics'], 'complete': report['complete'],
              'dependencies': report['dependencies'][:200], 'findings': report['findings'][:40],
              'limitations': report['limitations'], 'modules': []}
    limited = len(report['dependencies']) > 200 or len(report['findings']) > 40
    for module in report['modules']:
        symbols = module['symbols'][:symbols_left]
        calls = module['calls'][:calls_left]
        limited |= len(symbols) < len(module['symbols']) or len(calls) < len(module['calls'])
        symbols_left -= len(symbols); calls_left -= len(calls)
        result['modules'].append({'path': module['path'], 'parser': module['parser'], 'layer': module['layer'],
            'symbols': [{k: (v[:200] if isinstance(v,str) else v) for k,v in s.items()
                         if k in ('name','kind','line','parameters','methods','returns','qualified_name')} for s in symbols],
            'calls': [dict(c, callee=c['callee'][:200]) for c in calls]})
    result['evidence_limited'] = limited
    return result


def _python(path, source):
    tree = ast.parse(source, filename=path)
    symbols, imports, calls = [], [], []
    package = path[:-3].replace('/', '.').split('.')[:-1]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            prefix = package[:len(package)-node.level+1] if node.level else []
            base = '.'.join(prefix + ([node.module] if node.module else []))
            imports.append(base)
            imports.extend((base+'.'+a.name).strip('.') for a in node.names if a.name!='*')
    def visit(nodes, owner=''):
        for node in nodes:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                name = owner + node.name
                item = {'name':name, 'kind':'class' if isinstance(node,ast.ClassDef) else 'function',
                        'line':node.lineno, 'lines':node.end_lineno-node.lineno+1}
                if isinstance(node,ast.ClassDef):
                    item['methods'] = sum(isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) for n in node.body)
                    item['bases'] = [ast.unparse(base) for base in node.bases]
                else:
                    args = node.args
                    item['parameters'] = len(args.posonlyargs)+len(args.args)+len(args.kwonlyargs)+bool(args.vararg)+bool(args.kwarg)
                    if owner and args.args and args.args[0].arg in ('self','cls'): item['parameters']-=1
                    item['parameter_names'] = [a.arg for a in args.posonlyargs+args.args+args.kwonlyargs]
                    item['returns'] = ast.unparse(node.returns) if node.returns else None
                    # Nested functions get their own call ownership, never attribute their body to the outer function.
                    def collect(n):
                        if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)): return
                        if isinstance(n,ast.Call):
                            calls.append({'caller':name,'callee':ast.unparse(n.func),'line':n.lineno})
                        for child in ast.iter_child_nodes(n): collect(child)
                    for child in node.body: collect(child)
                symbols.append(item)
                visit(node.body,name+'.')
            else:
                # Definitions nested in branches are also public evidence.
                visit(list(ast.iter_child_nodes(node)),owner)
    visit(tree.body)
    return {'path':path,'parser':'python-ast','symbols':symbols,'imports':sorted(set(imports)), 'calls':calls}


def _lexical(path, source):
    if path.endswith('.vue'):
        source = '\n'.join(re.findall(r'<script\b[^>]*>(.*?)</script\s*>',source,re.S))
    # Preserve strings for import extraction, remove comments before looking for dependencies.
    token = r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`(?:\\.|[^`\\])*`|//[^\n]*|/\*[\s\S]*?\*/'
    clean = re.sub(token,lambda m: re.sub(r'[^\n]',' ',m.group()) if m.group().startswith(('//','/*')) else m.group(),source)
    code = re.sub(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`(?:\\.|[^`\\])*`',lambda m:re.sub(r'[^\n]',' ',m.group()),clean)
    java = path.endswith('.java')
    if java:
        imports = re.findall(r'\bimport\s+(?:static\s+)?([\w.*]+)\s*;',code)
        package = re.search(r'\bpackage\s+([\w.]+)\s*;',code)
        package = package.group(1) if package else ''
        patterns = [(r'\b(?:class|interface|enum|record)\s+(\w+)','class'),
                    (r'\b(?!(?:return|throw|new)\b)[\w<>\[\],.?]+\s+(\w+)\s*\([^;{}]*\)\s*(?:throws\s+[\w., ]+)?[;{]','method')]
    else:
        imports = re.findall(r'\b(?:import|export)\s+(?:[^;\n]*?\s+from\s*)?[\'"]([^\'"]+)[\'"]',clean)
        imports += re.findall(r'\b(?:require|import)\s*\(\s*[\'"]([^\'"]+)[\'"]\s*\)',clean)
        package = ''
        patterns = [(r'\bclass\s+(\w+)','class'),(r'\bfunction\s+(\w+)\s*\(','function'),
                    # TypeScript public contracts are declarations even though
                    # they have no runtime function body. Comments and strings
                    # have already been blanked above.
                    (r'\binterface\s+(\w+)\s*(?:<[^;{}]*>)?\s*(?:extends\s+[^;{}]+)?\{', 'interface'),
                    (r'\btype\s+(\w+)\s*(?:<[^;{}]*>)?\s*=', 'type'),
                    (r'\benum\s+(\w+)\s*\{', 'enum'),
                    (r'\b(?:const|let)\s+(\w+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|\w+)\s*=>','function'),
                    # Vue 2 methods and ordinary object function properties are
                    # declared symbols too. Keep this bounded lexical evidence;
                    # it does not infer dotted receiver names or call ownership.
                    (r'(?:^|[,{])\s*(\w+)\s*:\s*(?:async\s+)?function\s*(?:\w+\s*)?\(', 'method'),
                    (r'(?:^|[,{])\s*(?:async\s+)?(\w+)\s*\([^;{}]*\)\s*\{', 'method')]
    symbols = ([{'name':posixpath.basename(path)[:-4],'kind':'component','line':1}] if path.endswith('.vue') else [])
    for pattern,kind in patterns:
        for match in re.finditer(pattern,code):
            if match.group(1) in ('if','for','while','switch','catch'): continue
            symbol={'name':match.group(1),'kind':kind,'line':code[:match.start(1)].count('\n')+1}
            if java and kind=='method':
                owners=list(re.finditer(r'\b(?:class|interface|enum|record)\s+(\w+)',code[:match.start()]))
                if owners: symbol['qualified_name']=owners[-1].group(1)+'.'+symbol['name']
            symbols.append(symbol)
    if not java:
        symbols.extend(_typed_members(code))
    return {'path':path,'parser':'java-lexical' if java else 'js-vue-lexical','symbols':symbols,
            'imports':sorted(set(imports)),'calls':[], 'package':package,'identifiers':set(re.findall(r'\b\w+\b',code))}


def _typed_members(code):
    """Bounded declaration evidence for JS/TS class and interface methods.

    Track lexical brace depth so another class or a method's local function is
    never attributed to the preceding declaration. This is not type resolution.
    """
    result = []
    method = re.compile(r'(?:^|[;\n}])\s*(?:(?:public|private|protected|static|abstract|readonly|async|override)\s+)*'
                        r'(\w+)\s*(?:<[^;{}]*>)?\s*\([^;{}]*\)\s*(?::\s*[^;{}=]+)?\s*[;{]')
    for owner in re.finditer(r'\b(?:class|interface)\s+(\w+)[^;{}]*\{', code):
        start = owner.end(); depth = 1; end = start
        while end < len(code) and depth:
            depth += (code[end] == '{') - (code[end] == '}')
            end += 1
        body = code[start:end-1]
        cursor = 0; level = 0
        for match in method.finditer(body):
            # Include the delimiter before the declaration when calculating depth.
            prefix = body[cursor:match.start(1)]
            level += prefix.count('{') - prefix.count('}')
            cursor = match.start(1)
            if level != 0 or match.group(1) in ('if','for','while','switch','catch','function','return'):
                continue
            result.append({'name':match.group(1), 'qualified_name':owner.group(1)+'.'+match.group(1),
                           'kind':'method', 'line':code[:start+match.start(1)].count('\n')+1})
    return result


def _dependencies(modules):
    paths={m['path'] for m in modules}
    python={p[:-3].replace('/','.').removesuffix('.__init__'):p for p in paths if p.endswith('.py')}
    for name,path in list(python.items()):
        if name.startswith('src.'):
            python.setdefault(name[4:],path)
    java={((m['package']+'.') if m.get('package') else '')+s['name']:m['path']
          for m in modules if m['path'].endswith('.java') for s in m['symbols'] if s['kind']=='class'}
    edges=set()
    for module in modules:
        path=module['path']
        for imported in module['imports']:
            targets=[]
            if path.endswith('.py'):
                name=imported
                while name:
                    if name in python:
                        targets.append(python[name]); break
                    name=name.rpartition('.')[0]
            elif path.endswith('.java'):
                targets.extend(p for name,p in java.items() if imported==name or imported.startswith(name+'.') or (imported.endswith('.*') and name.rpartition('.')[0]==imported[:-2]))
            elif imported.startswith('.'):
                base=posixpath.normpath(posixpath.join(posixpath.dirname(path),imported))
                targets.extend(p for p in [base]+[base+s for s in ('.js','.ts','.vue','/index.js','/index.ts')] if p in paths)
            for target in targets:
                if path!=target: edges.add((path,target))
        if path.endswith('.java'):
            for name,target in java.items():
                if target!=path and name.rpartition('.')[0]==module['package'] and name.rpartition('.')[2] in module['identifiers']:
                    edges.add((path,target))
        module.pop('identifiers',None)
    return sorted(edges)


def review_structure(files, contract, incomplete=False):
    findings, modules = [], []
    def add(code,path,message,severity='error',line=None):
        findings.append(dict(code=code,path=path,message=message,severity=severity,**({'line':line} if line else {})))
    for path,source in sorted(files.items()):
        if not path.endswith(SOURCE_SUFFIXES) or any(fnmatch(path,p) for p in contract['exclude']): continue
        try:
            if path.endswith('/__init__.py') or path == '__init__.py':
                body = ast.parse(source).body
                if all(isinstance(n, ast.Pass) or (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)) for n in body):
                    continue
            modules.append(_python(path,source) if path.endswith('.py') else _lexical(path,source))
        except (SyntaxError, ValueError, RecursionError) as exc: add('parse_error',path,'Cannot parse source: '+str(exc)[:200])
    edges=_dependencies(modules)
    assignment={}
    for module in modules:
        path=module['path']
        matched=[layer['name'] for layer in contract['layers'] if any(fnmatch(path,p) for p in layer['paths'])]
        if len(matched)>1: add('ambiguous_layer',path,'Matches multiple layers: '+', '.join(matched))
        if not matched and contract['require_layer_assignment']: add('unassigned_module',path,'Production module has no assigned responsibility layer')
        assignment[path]=matched[0] if len(matched)==1 else None
        module['layer']=assignment[path]
        forbidden=contract.get('forbidden_imports',{}).get(assignment[path],[])
        for imported in module['imports']:
            if any(imported==p or imported.startswith(p+'.') or imported.startswith(p+'/') for p in forbidden):
                add('forbidden_import',path,'Layer %s cannot import %s' % (assignment[path],imported))
        limits=contract['limits']
        for symbol in module['symbols']:
            for metric,limit in [('lines','function_lines'),('parameters','parameters'),('methods','class_methods')]:
                if metric=='lines' and symbol['kind']=='class': continue
                if symbol.get(metric,0)>limits[limit]:
                    add('large_'+metric,path,'%s: %s=%s exceeds %s' % (symbol['name'],metric,symbol[metric],limits[limit]),'warning',symbol['line'])
        count=sum(a==path for a,b in edges)
        module['fan_out']=count
        module['fan_in']=sum(b==path for a,b in edges)
        if count>limits['module_fan_out']: add('high_fan_out',path,'Depends on %d local modules' % count,'warning')
    allowed={l['name']:set(l['may_depend_on']) for l in contract['layers']}
    graph={m['path']:[] for m in modules}
    for source,target in edges:
        graph[source].append(target)
        a,b=assignment[source],assignment[target]
        if a and b and a!=b and b not in allowed[a]: add('forbidden_dependency',source,'%s -> %s (%s -> %s)' % (source,target,a,b))
    # DFS reports back edges with the exact cycle; only analyzed local imports are considered.
    visited,stack,active=set(),[],set()
    def visit(path):
        if path in active:
            add('dependency_cycle',path,' -> '.join(stack[stack.index(path):]+[path])); return
        if path in visited: return
        visited.add(path); active.add(path); stack.append(path)
        for dep in graph[path]: visit(dep)
        stack.pop(); active.remove(path)
    for path in graph: visit(path)
    if incomplete: add('incomplete_analysis','','Source budget or read restrictions omitted files; result is incomplete')
    errors=sum(f['severity']=='error' for f in findings)
    return {'schema':'codespider.design-review/v1','mode':contract['mode'],'passed':errors==0,
            'blocking':contract['mode']=='enforce' and errors>0, 'complete':not incomplete,
            'modules':modules,'dependencies':[{'from':a,'to':b} for a,b in edges], 'findings':findings,
            'metrics':{'modules':len(modules),'classes':sum(s['kind']=='class' for m in modules for s in m['symbols']),
                       'functions':sum(s['kind'] in ('function','method') for m in modules for s in m['symbols']),
                       'components':sum(s['kind']=='component' for m in modules for s in m['symbols']),
                       'dependencies':len(edges),'errors':errors,'warnings':len(findings)-errors},
            'limitations':['Python calls are syntactic, not runtime dispatch resolution.',
                            'Java/JS/Vue use lexical evidence, not full AST/type resolution; aliases, reflection and dynamic imports may be missed.',
                            'Metrics and import direction do not prove semantic cohesion or pattern correctness.']}
