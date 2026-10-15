"""Preview real generated cases locally; does not call a model or use production state.

Usage: python3 -m tests.prototype_visual_fixture /path/to/generated/cases [members studio board]
Case directory names come from prototype_visual_cases.json.
"""
import json
from pathlib import Path
import shutil
import sys
import tempfile
import time
from http.server import ThreadingHTTPServer

from backend.app import AppContext, Handler
from backend.tool_protocol import ToolRequest


def main():
    cases = json.loads(Path(__file__).with_name('prototype_visual_cases.json').read_text())
    if sys.argv[2:]:
        selected = set(sys.argv[2:])
        if selected - {case['name'] for case in cases}:
            raise ValueError('Unknown visual case')
        cases = [case for case in cases if case['name'] in selected]
    source = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory(prefix='codespider-visual-preview-') as temp:
        context = AppContext(temp)
        try:
            urls = {}
            for case in cases:
                project = Path(temp)/'projects'/case['name']
                shutil.copytree(source/case['name'], project,
                    ignore=shutil.ignore_patterns('.codespider', '.codespider-preview-*'))
                workspace = context.workspaces.create(str(project), owner_id='local')

                def call(action):
                    response = context.tools.call(ToolRequest('preview', action,
                        workspace_id=workspace.id, owner_id='local', approval={'approved': True}))
                    if not response.ok:
                        raise RuntimeError(response.error)
                    return response.data

                call('build')
                deadline = time.monotonic()+30
                while time.monotonic() < deadline:
                    state = call('status')
                    if state.get('job', {}).get('status') not in ('queued', 'installing', 'building'):
                        break
                    time.sleep(.1)
                if state['job']['status'] != 'published':
                    raise RuntimeError(state['job'])
                urls[case['name']] = state['current']['url']

            class QuietHandler(Handler):
                def log_message(self, *_):
                    pass

            QuietHandler.context = context
            server = ThreadingHTTPServer(('127.0.0.1', 0), QuietHandler)
            print(json.dumps({'base': 'http://127.0.0.1:'+str(server.server_port), 'urls': urls}), flush=True)
            try:
                server.serve_forever()
            finally:
                server.server_close()
        finally:
            context.tasks.executor.shutdown(wait=True)
            context.processes.close()
            context.close()


if __name__ == '__main__':
    main()
