"""Read-only, bounded ingress server. Peer IP, never forwarded headers, authorizes."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import threading


class StatusServer:
    def __init__(self, supervisor, host='0.0.0.0', port=8787,
                 allowed=('127.0.0.1', '::1', '172.30.32.2')):
        self.supervisor = supervisor
        self.allowed = frozenset(str(ipaddress.ip_address(value)) for value in allowed)
        owner = self
        class Server(ThreadingHTTPServer):
            daemon_threads = True
            request_queue_size = 8
            slots = threading.BoundedSemaphore(8)

            def get_request(self):
                connection, address = super().get_request()
                connection.settimeout(1)
                return connection, address

            def process_request(self, request, address):
                if not self.slots.acquire(blocking=False):
                    self.shutdown_request(request)
                    return
                try:
                    super().process_request(request, address)
                except Exception:
                    self.slots.release()
                    raise

            def process_request_thread(self, request, address):
                try:
                    super().process_request_thread(request, address)
                finally:
                    self.slots.release()

            def handle_error(self, *_):
                pass  # Never print raw requests, headers or exceptions.

        class Handler(BaseHTTPRequestHandler):
            server_version = 'IsolatedStatus'
            sys_version = ''

            def log_message(self, *_):
                pass

            def do_GET(self):
                if self.client_address[0] not in owner.allowed:
                    self.send_body(403, b'{"error":"forbidden"}')
                    return
                status = owner.supervisor.status()
                if self.path == '/':
                    body = ('<!doctype html><html lang="en"><meta charset="utf-8">'
                            '<title>Hermes isolated PoC</title><h1>Hermes isolated PoC</h1>'
                            '<p>Read-only transport health. Fixture is synthetic, not WhatsApp delivery.</p>'
                            '<p><a href="status">Status</a> | <a href="live">Liveness</a> | '
                            '<a href="ready">Readiness</a></p></html>').encode()
                    self.send_body(200, body, 'text/html; charset=utf-8')
                elif self.path in ('/live', '/ready', '/status'):
                    code = 200
                    if self.path == '/live' and not status['live']:
                        code = 503
                    if self.path == '/ready' and not status['ready']:
                        code = 503
                    self.send_body(code, json.dumps(status, separators=(',', ':')).encode())
                else:
                    self.send_body(404, b'{"error":"not_found"}')

            def send_body(self, code, body, content_type='application/json'):
                self.send_response(code)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('Content-Security-Policy', "default-src 'none'; frame-ancestors 'self'")
                self.send_header('Connection', 'close')
                self.end_headers()
                self.wfile.write(body)
                self.close_connection = True

        self.server = Server((host, port), Handler)
        self.port = self.server.server_port
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=.05),
                                       name='status-http', daemon=True)

    def start(self):
        self.thread.start()
        return self

    def stop(self):
        if self.thread.is_alive():
            self.server.shutdown()
            self.thread.join(timeout=2)
        self.server.server_close()
