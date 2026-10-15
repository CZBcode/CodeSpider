"""Local-only fixture server for the real Vue build/browser acceptance test."""
import json
import os
import tempfile
from http.server import ThreadingHTTPServer
from pathlib import Path

from backend.app import AppContext, Handler


def component(label):
    return '<script setup>\nimport { ref } from "vue";\nconst count = ref(0);\n</script>\n<template><main><h1>' + label + '</h1><button @click="count++">Count {{ count }}</button></main></template>\n<style>main{padding:40px;font-family:system-ui}button{padding:12px}</style>\n'


def main():
    with tempfile.TemporaryDirectory(prefix='codespider-preview-e2e-') as temp:
        root = Path(temp) / 'project'; root.mkdir()
        if os.environ.get('CODESPIDER_TEST_NPM_REGISTRY'):
            (root / '.npmrc').write_text('registry=' + os.environ['CODESPIDER_TEST_NPM_REGISTRY'] + '\n')
        files = {
            'package.json': json.dumps({'name':'preview-acceptance', 'private':True, 'type':'module',
                'scripts':{'build':'vite build'}, 'dependencies':{'vue':'3.5.13'},
                'devDependencies':{'vite':'5.4.21', '@vitejs/plugin-vue':'5.2.1'}}),
            'index.html':'<div id="app"></div><script type="module" src="/src/main.js"></script>',
            'vite.config.js':"import {defineConfig} from 'vite'; import vue from '@vitejs/plugin-vue'; export default defineConfig({plugins:[vue()]});",
            'src/main.js':"import {createApp} from 'vue'; import App from './App.vue'; createApp(App).mount('#app');",
            'src/App.vue':component('First preview'),
        }
        for name, content in files.items():
            target = root / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_text(content)
        context = AppContext(str(Path(temp) / 'state'))
        workspace = context.workspaces.create(str(root), name='Vue 预览验收', owner_id='local')
        other = Path(temp) / 'other'; other.mkdir(); (other / 'main.py').write_text('value = 1')
        second = context.workspaces.create(str(other), name='Python 工程', owner_id='local')

        class FixtureHandler(Handler):
            def log_message(self, *_): pass
            def do_POST(self):
                if self.path == '/fixture/update':
                    body = self._body()
                    content = '<template><unclosed' if body.get('broken') else component('Updated preview')
                    task = context.tasks.create(workspace.id, '更新 Vue 页面',
                        [{'path':'src/App.vue','content':content}], owner_id='local')
                    context.tasks.approve(task.id)
                    return self._json(200, task.to_dict())
                return super().do_POST()
        FixtureHandler.context = context
        server = ThreadingHTTPServer(('127.0.0.1', 0), FixtureHandler)
        print(json.dumps({'url':'http://127.0.0.1:%s' % server.server_port, 'workspace':workspace.id, 'other':second.id}), flush=True)
        try: server.serve_forever()
        finally:
            server.server_close(); context.tasks.executor.shutdown(wait=True); context.processes.close(); context.close()


if __name__ == '__main__': main()
