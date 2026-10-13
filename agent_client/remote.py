"""Web-side proxy; preserves the public tool wire contract."""
from backend.tool_protocol import ToolRequest, ToolResponse, new_request_id
from codespider.ipc import request
from http.client import HTTPException


class RemoteTools:
    def __init__(self, socket_path, token):
        self.socket_path = socket_path
        self.token = token

    def health(self):
        try:
            return request(self.socket_path, self.token, 'GET', '/health', timeout=2)
        except (OSError, ValueError, HTTPException):
            return {'ok': False, 'service': 'codespider-agent'}

    def catalog(self):
        return request(self.socket_path, self.token, 'GET', '/tools')

    def call(self, payload):
        payload = payload.to_dict() if isinstance(payload, ToolRequest) else dict(payload)
        payload.setdefault('request_id', new_request_id())
        try:
            data = request(self.socket_path, self.token, 'POST', '/tools/call', payload, timeout=310)
            return ToolResponse(**data)
        except (OSError, ValueError, HTTPException):
            return ToolResponse(payload['request_id'], False, error={
                'code': 'AGENT_UNAVAILABLE', 'message': 'Agent 连接中断，请检查 daemon 状态；写操作请先核实结果再重试',
                'retryable': True})
