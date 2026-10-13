import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend.app import AppContext
from backend.model_gateway import ModelGateway, ModelContractError
from backend.tool_protocol import ToolRequest
from code_intelligence.design_contract import DEFAULT_CONTRACT, load_contract, review_proposal
from code_intelligence.structure import review_structure


def contract(mode='enforce'):
    value=copy.deepcopy(DEFAULT_CONTRACT)
    value.update(mode=mode,layers=[
        {'name':'web','paths':['web/*'],'may_depend_on':['service']},
        {'name':'service','paths':['service/*'],'may_depend_on':[]}])
    return value


class DesignStructureTests(unittest.TestCase):
    def test_real_dependencies_not_comment_or_string_keywords(self):
        files={'web/api.py':'from service.logic import run\ndef request():\n return run()\n',
               'service/logic.py':'# from web.api import request\ntext="import web.api"\ndef run(): return 42\n'}
        report=review_structure(files,contract())
        self.assertTrue(report['passed'])
        self.assertEqual(report['dependencies'],[{'from':'web/api.py','to':'service/logic.py'}])
        self.assertEqual(report['modules'][1]['calls'][0]['callee'],'run')

    def test_forbidden_edge_and_cycle_are_blocked(self):
        report=review_structure({'web/api.py':'from service.logic import run',
                                 'service/logic.py':'from web.api import request'},contract())
        self.assertTrue(report['blocking'])
        self.assertEqual({f['code'] for f in report['findings']},{'forbidden_dependency','dependency_cycle'})
        advisory=review_structure({'web/api.py':'import service.logic','service/logic.py':'import web.api'},contract('advisory'))
        self.assertFalse(advisory['blocking']); self.assertFalse(advisory['passed'])

    def test_relative_imports_classes_and_nested_call_ownership(self):
        source='''from . import helper
class Service:
 def run(self, value):
  def nested(): return helper.compute(value)
  return nested()
'''
        report=review_structure({'pkg/service.py':source,'pkg/helper.py':'def compute(x): return x'},contract())
        module=next(m for m in report['modules'] if m['path']=='pkg/service.py')
        self.assertEqual(module['symbols'][1]['parameters'],1)
        self.assertEqual({(c['caller'],c['callee']) for c in module['calls']},
                         {('Service.run','nested'),('Service.run.nested','helper.compute')})
        self.assertIn({'from':'pkg/service.py','to':'pkg/helper.py'},report['dependencies'])
        src=review_structure({'src/shop/service.py':'from shop.pricing import total',
                              'src/shop/pricing.py':'def total(): return 1'},contract())
        self.assertEqual(src['metrics']['dependencies'],1)

    def test_java_and_vue_imports_and_same_package_dependencies(self):
        files={'web/Controller.java':'package web; import service.Service; public class Controller { private Service service; }',
               'service/Service.java':'package service; public class Service { private Helper helper; }',
               'service/Helper.java':'package service; public class Helper {}',
               'web/App.vue':'<template>import x from "../service/fake.js"</template><script setup>import {load} from "../service/api.js";</script>',
               'service/api.js':'export function load() {}'}
        report=review_structure(files,contract())
        self.assertTrue(report['passed'])
        self.assertEqual(report['metrics']['dependencies'],3)
        self.assertIn('lexical',next(m for m in report['modules'] if m['path']=='web/App.vue')['parser'])

    def test_incomplete_analysis_never_passes_enforced_contract(self):
        self.assertTrue(review_structure({},contract(),incomplete=True)['blocking'])
        self.assertFalse(review_structure({},contract('advisory'),incomplete=True)['blocking'])

    def test_metrics_warn_instead_of_inventing_semantic_failure(self):
        policy=contract();policy['limits']['parameters']=1
        report=review_structure({'f.py':'def function(a,b): return a+b'},policy)
        self.assertTrue(report['passed'])
        self.assertEqual(report['findings'][0]['code'],'large_parameters')

    def test_invalid_policy_fails_closed(self):
        for raw in ('not json','[]','{"mode":"off"}','{"limits":{"parameters":true}}',
                    '{"layers":[{"name":"x","paths":["*"],"may_depend_on":["missing"]}]}'):
            with self.subTest(raw=raw),self.assertRaises(ValueError): load_contract({'design-contract.json':raw})

    def test_model_cannot_weaken_contract_and_claim_pass(self):
        context={'files':{},'design_contract':contract()}
        with self.assertRaisesRegex(ValueError,'cannot be changed'):
            review_proposal(context,[{'path':'design-contract.json','replacement':'{}'}])
        response={'patches':[{'path':'service/core.py','operation':'create','replacement':'import web.api'},
                             {'path':'web/api.py','operation':'create','replacement':'x=1'}],
                  'design_review':{'passed':True}}
        with self.assertRaisesRegex(ModelContractError,'violation'):
            ModelGateway.validate_generation(response,context)

    def test_required_design_checks_symbol_existence_and_responsibility(self):
        policy=contract();policy['require_design']=True
        context={'files':{},'design_contract':policy}
        patches=[{'path':'service/core.py','replacement':'def run(): return 1'}]
        with self.assertRaisesRegex(ValueError,'requires modules'): review_proposal(context,patches)
        design={'modules':[{'path':'service/core.py','responsibility':'Compute answer','depends_on':[]}],
                'interfaces':[{'path':'service/core.py','symbol':'missing','inputs':'none','outputs':'integer','errors':'none'}],'patterns':[]}
        with self.assertRaisesRegex(ValueError,'not found'):review_proposal(context,patches,design)
        design['interfaces'][0]['symbol']='run'
        self.assertTrue(review_proposal(context,patches,design)['passed'])

    def test_empty_package_marker_needs_no_invented_responsibility(self):
        report=review_structure({'shop/__init__.py':'', 'shop/logic.py':'def run(): return 1'},contract())
        self.assertEqual(report['metrics']['modules'],1)
        report=review_structure({'shop/__init__.py':'from .logic import run','shop/logic.py':'def run(): return 1'},contract())
        self.assertEqual(report['metrics']['dependencies'],1)

    def test_framework_import_in_domain_and_implicit_java_vue_symbols(self):
        policy=contract();policy['forbidden_imports']={'service':['org.springframework','requests']}
        report=review_structure({'service/Policy.java':'package service; import org.springframework.stereotype.Service; public interface Policy { int total(int a, int b); }',
                                 'web/List.vue':'<template><p>List</p></template>'},policy)
        self.assertTrue(report['blocking'])
        java=next(m for m in report['modules'] if m['path'].endswith('.java'))
        self.assertIn('Policy.total',[s.get('qualified_name') for s in java['symbols']])
        self.assertEqual(report['metrics']['components'],1)

    def test_hash_precondition_keeps_exact_original_and_rejects_stale_content(self):
        original='def run(): return 1\n'
        digest=hashlib.sha256(original.encode()).hexdigest()
        response={'patches':[{'path':'logic.py','operation':'apply_patch','base_sha256':digest,'replacement':'def run(): return 2\n'}]}
        ModelGateway.validate_generation(response,{'files':{'logic.py':original}})
        self.assertEqual(response['patches'][0]['expected'],original)
        with self.assertRaisesRegex(ModelContractError,'base_sha256'):
            ModelGateway.validate_generation(response,{'files':{'logic.py':original+'# user edit\n'}})
        response['patches'][0]['expected']=original.rstrip()
        with self.assertRaisesRegex(ModelContractError,'full provided file'):
            ModelGateway.validate_generation(response,{'files':{'logic.py':original}})

    def test_structured_interface_inputs_and_empty_errors_are_valid(self):
        policy=contract();policy['require_design']=True
        design={'modules':[{'path':'service/core.py','responsibility':'Compute','depends_on':[]}],
                'interfaces':[{'path':'service/core.py','symbol':'run','inputs':{},'outputs':'int','errors':[]}],'patterns':[]}
        self.assertTrue(review_proposal({'files':{},'design_contract':policy},
                                       [{'path':'service/core.py','replacement':'def run(): return 1'}],design)['passed'])


class DesignWorkflowTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)/'project'; self.root.mkdir()
        self.app=AppContext(str(Path(temp.name)/'state'));self.addCleanup(self.app.close)
        self.addCleanup(self.app.tasks.executor.shutdown,wait=True)
        self.workspace=self.app.workspaces.create(str(self.root))
        (self.root/'design-contract.json').write_text(json.dumps(contract()))

    def test_standard_tool_requires_approval_and_exposes_findings(self):
        request=ToolRequest('code','design_review',workspace_id=self.workspace.id)
        self.assertFalse(self.app.tools.call(request).ok)
        request.approval={'approved':True}
        response=self.app.tools.call(request)
        self.assertTrue(response.ok);self.assertEqual(response.data['schema'],'codespider.design-review/v1')

    def test_forbidden_dependency_prevents_all_writes(self):
        task=self.app.tasks.create(self.workspace.id,'bad dependency',patches=[
            {'path':'web/api.py','operation':'create','replacement':'x=1'},
            {'path':'service/core.py','operation':'create','replacement':'import web.api'}])
        self.app.tasks.approve(task.id);self.app.tasks.executor.shutdown(wait=True)
        self.assertEqual(self.app.tasks.get(task.id).status,'failed')
        self.assertFalse((self.root/'web/api.py').exists())

    def test_contract_changed_after_generation_requires_regeneration(self):
        task=self.app.tasks.create(self.workspace.id,'write',patches=[{'path':'service/core.py','replacement':'x=1'}])
        task.design_contract=contract();self.app.tasks._save_task(task)
        (self.root/'design-contract.json').write_text(json.dumps(contract('advisory')))
        self.app.tasks.approve(task.id);self.app.tasks.executor.shutdown(wait=True)
        self.assertEqual(self.app.tasks.get(task.id).status,'failed')
        self.assertFalse((self.root/'service/core.py').exists())
