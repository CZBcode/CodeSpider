"""Run on Linux with CODESPIDER_EXECUTION_SANDBOX=bubblewrap."""
import os
from pathlib import Path
import shlex
import tempfile
import unittest
from unittest.mock import patch
from agent_client.executor import AgentExecutor
from agent_client.sandbox import prepare
from backend.policy import WorkspacePolicy


class SandboxConfigurationTests(unittest.TestCase):
    def test_configured_sandbox_fails_closed(self):
        with tempfile.TemporaryDirectory() as root:
            with patch.dict(os.environ, CODESPIDER_EXECUTION_SANDBOX='bubblewrap'), patch('agent_client.sandbox.shutil.which', return_value=None):
                with self.assertRaisesRegex(ValueError, '不会降级'):
                    prepare(WorkspacePolicy(root), ['python3'], {})


@unittest.skipUnless(os.environ.get('CODESPIDER_EXECUTION_SANDBOX') == 'bubblewrap', 'Linux sandbox integration only')
class SandboxIntegrationTests(unittest.TestCase):
    def test_only_current_project_is_visible_and_environment_is_private(self):
        with tempfile.TemporaryDirectory() as base:
            root = Path(base)/'alice'; root.mkdir()
            secret = Path(base)/'bob-secret'; secret.write_text('private')
            executor = AgentExecutor(WorkspacePolicy(str(root)))
            script = ('import os; from pathlib import Path; '
                      f'assert not Path({str(secret)!r}).exists(); '
                      "assert not Path('/var/lib/codespider/.codespider/h2/accounts.mv.db').exists(); "
                      "assert not Path('/opt/codespider').exists(); "
                      "assert 'CODESPIDER_IPC_TOKEN' not in os.environ; "
                      "assert os.getpid() < 100; Path('output').write_text('own project')")
            with patch.dict(os.environ, CODESPIDER_IPC_TOKEN='never-in-child'):
                result = executor.run_command('python3 -c '+shlex.quote(script), approved=True)
            self.assertEqual(result['exit_code'], 0, result['output'])
            self.assertEqual((root/'output').read_text(), 'own project')
            self.assertEqual(secret.read_text(), 'private')

    def test_runtime_compilation_and_dependency_installation(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)
            (p/'Hello.java').write_text('class Hello {public static void main(String[] a){System.out.println("ok");}}')
            (p/'pom.xml').write_text('<project><modelVersion>4.0.0</modelVersion><groupId>example</groupId><artifactId>smoke</artifactId><version>1</version></project>')
            (p/'package.json').write_text('{"private":true,"dependencies":{"vue":"3.5.13","vite":"5.4.21"},"scripts":{"build":"vite build"},"type":"module"}')
            (p/'index.html').write_text('<div id="app"></div><script type="module" src="/main.js"></script>')
            (p/'main.js').write_text('import {createApp} from "vue"; createApp({template:"<h1>ok</h1>"}).mount("#app")')
            executor=AgentExecutor(WorkspacePolicy(root))
            for cmd in ('javac Hello.java','java Hello','mvn -q test','npm install --ignore-scripts --no-audit --no-fund','npm run build'):
                with self.subTest(command=cmd):
                    result=executor.run_command(cmd, timeout=180, approved=True)
                    self.assertEqual(result['exit_code'],0,result['output'])
            self.assertTrue((p/'dist/index.html').exists())
