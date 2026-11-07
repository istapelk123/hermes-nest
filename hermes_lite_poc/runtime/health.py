"""Independent live transport probe. TLS success is not message delivery."""
import socket
import http.client
import json
import math
from pathlib import Path
import ssl
import threading


class TLSProbe:
    """At most one daemon worker, even if OS DNS resolution ignores timeouts."""
    def __init__(self, timeout):
        self.timeout = timeout
        self._pending = None
        self._lock = threading.Lock()

    def __call__(self):
        with self._lock:
            if self._pending is None:
                done = threading.Event()
                result = {'ok': False}
                self._pending = (done, result)
                def attempt():
                    try:
                        context = ssl.create_default_context()
                        with socket.create_connection(('web.whatsapp.com', 443), timeout=self.timeout) as raw:
                            with context.wrap_socket(raw, server_hostname='web.whatsapp.com'):
                                result['ok'] = True
                    except (OSError, ValueError):
                        pass
                    finally:
                        done.set()
                threading.Thread(target=attempt, name='tls-reachability', daemon=True).start()
            done, result = self._pending
        completed = done.wait(self.timeout)
        with self._lock:
            if completed and self._pending is not None and self._pending[0] is done:
                self._pending = None
        return completed and result['ok']


def probe_bridge(port, expected_session, timeout):
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=timeout)
    timer = None
    try:
        connection.connect()  # Literal loopback: no external DNS or proxy env.
        raw = connection.sock
        def abort():
            try:
                raw.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        timer = threading.Timer(timeout, abort)
        timer.daemon = True
        timer.start()
        connection.request('GET', '/health')
        response = connection.getresponse()
        body = response.read(65537)
        if response.status != 200 or len(body) > 65536:
            return 'bridge_unavailable'
        value = json.loads(body)
        if not isinstance(value, dict):
            return 'bridge_unavailable'
        if value.get('status') not in ('connected', 'disconnected', 'connecting'):
            return 'bridge_unavailable'
        if (type(value.get('queueLength')) is not int or value['queueLength'] < 0
                or type(value.get('uptime')) not in (int, float) or not math.isfinite(value['uptime'])
                or value['uptime'] < 0 or not isinstance(value.get('scriptHash'), str)
                or not 1 <= len(value['scriptHash']) <= 256
                or not isinstance(value.get('capabilities'), dict)
                or value['capabilities'].get('outboundMentions') is not True
                or not isinstance(value.get('session'), str)):
            return 'bridge_unavailable'
        if not Path(value['session']).is_absolute() or value['session'] != str(expected_session.resolve()):
            return 'session_mismatch'
        return 'connected' if value['status'] == 'connected' else 'waiting_for_auth'
    except (OSError, ValueError, TypeError, OverflowError, RecursionError, http.client.HTTPException):
        return 'bridge_unavailable'
    finally:
        if timer:
            timer.cancel()
        connection.close()


def transport_state(bridge_state, mode, tls_probe):
    if mode == 'live' and bridge_state in ('connected', 'waiting_for_auth', 'bridge_unavailable') and not tls_probe():
        return 'network_down'
    return bridge_state
