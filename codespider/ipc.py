"""Authenticated JSON over owner-only Unix sockets (macOS and Linux)."""
import http.client
import json
import os
import secrets
import socket
import socketserver
import logging
from http.server import BaseHTTPRequestHandler


class Connection(http.client.HTTPConnection):
    def __init__(self, path, timeout=5):
        super().__init__('localhost', timeout=timeout)
        self.path = str(path)

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.path)


def request(path, token, method, endpoint, payload=None, timeout=5):
    connection = Connection(path, timeout)
    try:
        connection.request(method, endpoint, body=json.dumps(payload) if payload is not None else None,
                           headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
        response = connection.getresponse()
        data = json.loads(response.read())
        if response.status != 200:
            raise ValueError(data.get('error', 'IPC request failed'))
        return data
    finally:
        connection.close()


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True

    def __init__(self, path, token, dispatch):
        self.token = token
        self.dispatch = dispatch
        super().__init__(str(path), Handler)
        os.chmod(path, 0o600)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        self.handle_json()

    def do_POST(self):
        self.handle_json()

    def handle_json(self):
        status = 200
        try:
            if not secrets.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + self.server.token):
                status, data = 403, {'error': 'unauthorized'}
            else:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 <= size <= 2 * 1024 * 1024:
                    raise ValueError('request body too large')
                payload = json.loads(self.rfile.read(size)) if size else {}
                if not isinstance(payload, dict):
                    raise ValueError('expected JSON object')
                data = self.server.dispatch(self.command, self.path, payload)
        except Exception:
            logging.exception('IPC request failed: %s %s', self.command, self.path)
            status, data = 400, {'error': 'internal request failed'}
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
