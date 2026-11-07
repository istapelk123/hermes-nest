"""Generated synthetic gateway/bridge; no network except loopback, no Hermes imports."""
import argparse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import threading
import time


def atomic_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value), encoding='utf-8')
    try:
        os.replace(temporary, path)
    except PermissionError:
        # Windows may briefly hold a reader handle without delete sharing.
        # Leave the previous valid heartbeat; next tick retries.
        pass


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--role', choices=['gateway', 'bridge'], required=True)
    p.add_argument('--data-dir', required=True)
    p.add_argument('--port', type=int, required=True)
    args = p.parse_args()
    data = Path(args.data_dir)
    home = data
    default = home / 'platforms' / 'whatsapp' / 'session'
    legacy = home / 'whatsapp' / 'session'
    session = legacy if legacy.exists() and not default.exists() else default
    started = time.monotonic()
    stopping = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT, getattr(signal, 'SIGBREAK', signal.SIGTERM)):
        signal.signal(sig, lambda *_: stopping.set())
    def controls():
        try:
            value = json.loads((data / 'fixture-control.json').read_text(encoding='utf-8'))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}
    if args.role == 'bridge':
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                if self.path != '/health':
                    self.send_error(404)
                    return
                control = controls()
                if control.get('bridge_health') == 'hang':
                    time.sleep(.7)
                result = dict(status=control.get('bridge_status', 'connected'), queueLength=0,
                              uptime=time.monotonic() - started, scriptHash='synthetic',
                              session=control.get('bridge_session', str(session.resolve())), capabilities={'outboundMentions': True})
                body = b'broken' if control.get('bridge_health') == 'broken' else json.dumps(result).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except OSError:
                    pass
        server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
        server.timeout = 0.05
        while not stopping.is_set():
            server.handle_request()
        server.server_close()
        return
    session.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(home / 'state.db') as db:
        db.execute('PRAGMA user_version=32')
        db.execute('CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)')
        db.execute('DELETE FROM schema_version')
        db.execute('INSERT INTO schema_version VALUES (32)')
        db.execute('CREATE TABLE IF NOT EXISTS fixture_marker (synthetic INTEGER NOT NULL)')
        db.execute('DELETE FROM fixture_marker')
        db.execute('INSERT INTO fixture_marker VALUES (1)')
    db.close()
    bridge = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--role', 'bridge',
                               '--data-dir', str(data), '--port', str(args.port)],
                              stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL)
    (data / 'fixture_bridge.pid').write_text(str(bridge.pid))
    try:
        while not stopping.is_set():
            control = controls()
            if control.get('noisy'):
                os.write(1, b'SYNTHETIC_SECRET_DO_NOT_LOG' * 8192)
                os.write(2, b'SYNTHETIC_QR_DO_NOT_LOG' * 8192)
            if control.get('gateway_fault') == 'crash':
                os._exit(17)
            if control.get('gateway_fault') == 'hang':
                stopping.wait(.05)
                continue
            atomic_json(home / 'gateway_state.json', {
                'updated_at': datetime.now(timezone.utc).isoformat(),
                'state': 'running', 'pid': control.get('heartbeat_pid', bridge.pid if control.get('heartbeat_descendant') else os.getpid())})
            stopping.wait(0.05)
    finally:
        bridge.terminate()
        try:
            bridge.wait(timeout=1)
        except subprocess.TimeoutExpired:
            bridge.kill()
            bridge.wait()


if __name__ == '__main__':
    main()
