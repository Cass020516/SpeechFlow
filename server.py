#!/usr/bin/env python3
"""Static file server with API proxy (solves CORS issues)."""

import http.server
import json
import os
import socket
import socketserver
import sys
import urllib.request
import urllib.error
from urllib.parse import urlparse

PORT = 8080
DIR = os.path.dirname(os.path.abspath(__file__))


class ProxyHandler(http.server.SimpleHTTPRequestHandler):

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_cors()
        self.end_headers()

    def send_cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-API-Key, X-API-Endpoint')

    def do_GET(self):
        path = urlparse(self.path).path
        if path == '/api/ping':
            self.send_json(200, {'ok': True, 'proxy': True})
            return
        return super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        if path == '/api/chat':
            self.proxy_chat()
        elif path == '/api/transcribe':
            self.proxy_transcribe()
        else:
            self.send_error(404)

    def proxy_chat(self):
        try:
            content_len = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_len)
            api_endpoint = self.headers.get('X-API-Endpoint', '').rstrip('/')
            api_key = self.headers.get('X-API-Key', '')

            if not api_endpoint or not api_key:
                self.send_json(400, {'error': 'Missing X-API-Endpoint or X-API-Key header'})
                return

            target = f'{api_endpoint}/chat/completions'
            req = urllib.request.Request(
                target, data=body,
                headers={
                    'Content-Type': 'application/json',
                    'Authorization': f'Bearer {api_key}',
                }, method='POST')

            with urllib.request.urlopen(req, timeout=180) as resp:
                data = resp.read()
                self.send_json(resp.status, json.loads(data))

        except urllib.error.HTTPError as e:
            err_body = e.read().decode('utf-8', errors='replace')
            self.send_json(e.code, {'error': err_body[:500]})
        except urllib.error.URLError as e:
            self.send_json(502, {'error': f'Proxy request failed: {e.reason}'})
        except socket.timeout:
            self.send_json(504, {'error': 'API 请求超时（超过 180 秒）'})
        except Exception as e:
            self.send_json(502, {'error': str(e)})

    def proxy_transcribe(self):
        try:
            api_endpoint = self.headers.get('X-API-Endpoint', '').rstrip('/')
            api_key = self.headers.get('X-API-Key', '')
            if not api_endpoint or not api_key:
                self.send_json(400, {'error': 'Missing headers'})
                return
            content_type = self.headers.get('Content-Type', '')
            content_len = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_len)
            target = f'{api_endpoint}/audio/transcriptions'
            req = urllib.request.Request(
                target, data=body,
                headers={
                    'Content-Type': content_type,
                    'Authorization': f'Bearer {api_key}',
                }, method='POST')
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = resp.read()
                self.send_json(resp.status, json.loads(data))
        except urllib.error.HTTPError as e:
            err_body = e.read().decode('utf-8', errors='replace')
            self.send_json(e.code, {'error': err_body[:500]})
        except urllib.error.URLError as e:
            self.send_json(502, {'error': f'Proxy failed: {e.reason}'})
        except socket.timeout:
            self.send_json(504, {'error': 'Whisper 超时'})
        except Exception as e:
            self.send_json(502, {'error': str(e)})

    def send_json(self, status, data):
        self.send_response(status)
        self.send_cors()
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))

    def log_message(self, format, *args):
        msg = format % args
        if '/api/' in msg:
            print(f'[Proxy] {msg}', flush=True)


class ThreadedServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == '__main__':
    os.chdir(DIR)
    server = ThreadedServer(('0.0.0.0', PORT), ProxyHandler)
    print(f'Serving at http://localhost:{PORT}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
