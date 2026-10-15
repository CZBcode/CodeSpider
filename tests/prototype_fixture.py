"""Local-only HTTP fixture using the real plugin, tools and preview pipeline."""
import json
from pathlib import Path
import shutil
import tempfile
from http.server import ThreadingHTTPServer

from backend.app import AppContext, Handler


def main():
    with tempfile.TemporaryDirectory(prefix='codespider-prototype-e2e-') as temp:
        root = Path(temp) / 'element'
        shutil.copytree(Path(__file__).resolve().parents[1]/'examples/prototypes/element-admin', root)
        plain = Path(temp) / 'plain'; plain.mkdir()
        (plain/'index.html').write_text('<h1>原生页面</h1><button id="count">0</button>'
            '<form id="local-form"><label>内容<input id="value" required></label><button>提交本地表单</button><output id="saved"></output></form>'
            '<form action="/fixture/forbidden-submit" method="post"><button>尝试网络提交</button></form><script src="app.js"></script>')
        (plain/'app.js').write_text("let count=0;document.querySelector('#count').addEventListener('click',function increment(){document.querySelector('#count').textContent=++count;});"
            "document.querySelector('#local-form').addEventListener('submit',function save(event){event.preventDefault();document.querySelector('#saved').textContent=document.querySelector('#value').value;});")
        context = AppContext(str(Path(temp)/'state'))
        workspaces = [context.workspaces.create(str(p), name=name, owner_id='local') for p,name in ((root,'Element UI 成员原型'),(plain,'原生 JavaScript 原型'))]
        submissions = []
        class FixtureHandler(Handler):
            def log_message(self, *_): pass
            def do_GET(self):
                if self.path == '/fixture/submission-count':
                    return self._json(200, {'count':len(submissions)})
                return super().do_GET()
            def do_POST(self):
                if self.path == '/fixture/forbidden-submit':
                    submissions.append(True)
                    return self._json(200, {})
                if self.path == '/fixture/update':
                    body = self._body()
                    content = (root/'index.html').read_text().replace('<h1>团队成员</h1>', '<h1>最新团队成员</h1>')
                    patches = [{'path':'app.js','content':'invalid {{{'}] if body.get('broken') else [{'path':'index.html','content':content}]
                    task = context.tasks.create(workspaces[0].id,'更新 HTML 原型',patches,owner_id='local')
                    context.tasks.approve(task.id)
                    return self._json(200,task.to_dict())
                return super().do_POST()
        FixtureHandler.context = context
        server = ThreadingHTTPServer(('127.0.0.1',0),FixtureHandler)
        print(json.dumps({'url':'http://127.0.0.1:%s'%server.server_port,'element':workspaces[0].id,'plain':workspaces[1].id}),flush=True)
        try: server.serve_forever()
        finally: server.server_close();context.tasks.executor.shutdown(wait=True);context.processes.close();context.close()


if __name__ == '__main__': main()
