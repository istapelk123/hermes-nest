"""Fail-closed runtime policy and process supervision (stdlib only)."""
from dataclasses import dataclass
from datetime import datetime, timezone
import math
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import threading
import time


from .resources import owned_rss_bytes, configure_cli_limits
from .events import EventLog
from .health import TLSProbe, transport_state, probe_bridge
from .policy import (ActivationError, PolicyError, FileLock, child_environment,
                     prepare_home, prepared_home_allowed, safe_path, read_json, enforce_live_activation,
                     ACTIVATION, LIVE_COMMAND, validate_live_artifacts, enforce_agent_isolation)


@dataclass(frozen=True)
class Config:
    data_dir: Path
    mode: str = 'fixture'
    interval: float = 1.0
    health_timeout: float = 1.5
    heartbeat_max_age: float = 120.0
    stop_grace: float = 2.0
    startup_grace: float = 30.0
    restart_base: float = 2.0
    restart_cap: float = 60.0
    circuit_failures: int = 5
    circuit_window: float = 300.0
    liveness_max_age: float = 10.0
    bridge_port: int | None = None
    worker_memory_mb: int = 1536

    def __post_init__(self):
        if type(self.worker_memory_mb) is not int or not 64 <= self.worker_memory_mb <= 65536:
            raise PolicyError('invalid worker RSS budget')
        if self.mode not in ('fixture', 'agent', 'live'):
            raise PolicyError('unsupported mode')
        for name in ('interval', 'health_timeout', 'heartbeat_max_age', 'stop_grace',
                     'startup_grace', 'restart_base', 'restart_cap', 'circuit_window', 'liveness_max_age'):
            value = getattr(self, name)
            if type(value) not in (float, int) or not math.isfinite(value) or value <= 0:
                raise PolicyError('invalid runtime timing')
        if self.restart_cap < self.restart_base or type(self.circuit_failures) is not int or not 1 <= self.circuit_failures <= 100:
            raise PolicyError('invalid restart limits')
        if self.bridge_port is not None and (type(self.bridge_port) is not int or not 1 <= self.bridge_port <= 65535):
            raise PolicyError('invalid bridge port')
        if self.mode == 'live' and self.bridge_port not in (None, 3000):
            raise PolicyError('live bridge port is fixed')


def pid_alive(pid):
    if os.name == 'nt':
        import ctypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        h = kernel.OpenProcess(0x1000, False, int(pid))
        if not h:
            return False
        code = ctypes.c_ulong()
        kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        kernel.GetExitCodeProcess(h, ctypes.byref(code))
        kernel.CloseHandle(h)
        return code.value == 259
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def owns_pid(root_pid, candidate):
    if type(candidate) is not int or candidate <= 0:
        return False
    if os.name != 'nt':
        try:
            return os.getpgid(candidate) == root_pid
        except OSError:
            return False
    import ctypes
    from ctypes import wintypes
    class Entry(ctypes.Structure):
        _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD),
                    ('pid', wintypes.DWORD), ('heap', ctypes.c_size_t),
                    ('module', wintypes.DWORD), ('threads', wintypes.DWORD),
                    ('parent', wintypes.DWORD), ('priority', wintypes.LONG),
                    ('flags', wintypes.DWORD), ('name', wintypes.WCHAR * 260)]
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    k.Process32FirstW.argtypes = [ctypes.c_void_p, ctypes.POINTER(Entry)]
    k.Process32NextW.argtypes = [ctypes.c_void_p, ctypes.POINTER(Entry)]
    k.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = k.CreateToolhelp32Snapshot(2, 0)
    if handle == ctypes.c_void_p(-1).value:
        return False
    parents = {}
    entry = Entry()
    entry.dwSize = ctypes.sizeof(entry)
    try:
        ok = k.Process32FirstW(handle, ctypes.byref(entry))
        while ok:
            parents[entry.pid] = entry.parent
            ok = k.Process32NextW(handle, ctypes.byref(entry))
    finally:
        k.CloseHandle(handle)
    seen = set()
    while candidate and candidate not in seen:
        if candidate == root_pid:
            return True
        seen.add(candidate)
        candidate = parents.get(candidate, 0)
    return False


class Supervisor:
    def __init__(self, config):
        self.config = config
        self.data = safe_path(config.data_dir)
        self.home = self.data
        self.session = self.home / 'platforms' / 'whatsapp' / 'session'
        self.process = None
        self._stop = threading.Event()
        self._thread = None
        self._lock = threading.Lock()
        self._state = 'starting'
        self._last_tick = 0.0
        self.bridge_port = None
        self._instance_lock = None
        self._job = None
        self._launched_at = 0.0
        self._failures = []
        self._restart_due = None
        self._restarts = 0
        self._circuit_open = False
        self._tls_probe = TLSProbe(config.health_timeout)
        self.events = None
        self._owned_active = False
        self._used = False
        self._closed = False
        self._bridge_failure_since = None

    def start(self):
        if self._used or self._closed:
            raise PolicyError('supervisor instances are single use')
        self._used = True
        if self.config.mode not in ('fixture', 'agent', 'live'):
            raise PolicyError('unsupported mode')
        if self.config.mode == 'live':
            enforce_live_activation()
        safe_path(self.data)
        # Reject a data directory containing runtime source before creating files.
        if self.data in Path(__file__).resolve().parents or self.data.is_relative_to(Path('/opt/hermes').absolute()):
            raise PolicyError('source and data collision')
        if self.data.exists() and not safe_path(self.data / 'runtime-meta.json').exists():
            if (any(entry.name != 'supervisor.lock' for entry in self.data.iterdir())
                    and not prepared_home_allowed(self.data, self.config.mode)):
                raise PolicyError('nonempty unowned data directory rejected')
        self.data.mkdir(parents=True, exist_ok=True)
        lock = FileLock(self.data / 'supervisor.lock')
        lock.acquire()
        self._instance_lock = lock
        try:
            self.session = prepare_home(self.data, 'live' if self.config.mode == 'agent' else self.config.mode)
            self.events = EventLog(self.data)
            self.events.emit('started')
            return self._start_process()
        except BaseException:
            self.stop()
            raise

    def _start_process(self):
        self._launch()
        self._thread = threading.Thread(target=self._run, name='supervisor', daemon=True)
        self._thread.start()
        return self

    def _launch(self):
        self._bridge_failure_since = None
        if self.config.mode == 'live':
            enforce_live_activation()
            validate_live_artifacts()
        elif self.config.mode == 'agent':
            enforce_agent_isolation(self.home)
            validate_live_artifacts()
        port = 3000 if self.config.mode == 'live' else (self.config.bridge_port or 0)
        try:
            with socket.socket() as sock:
                if os.name == 'nt':
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                sock.bind(('127.0.0.1', port))
                self.bridge_port = sock.getsockname()[1]
        except OSError:
            raise PolicyError('bridge port occupied; refusing foreign listener') from None
        safe_path(self.home / 'gateway_state.json').unlink(missing_ok=True)
        command = LIVE_COMMAND if self.config.mode in ('agent', 'live') else [
            sys.executable, str(Path(__file__).with_name('fixture.py')), '--role', 'gateway',
            '--data-dir', str(self.data), '--port', str(self.bridge_port)]
        self.process = subprocess.Popen(
            command, env=child_environment(self.home), cwd=self.home,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=os.name != 'nt',
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0)
        if os.name == 'nt':
            from .windows_job import WindowsJob
            self._job = WindowsJob(self.process)
        self._launched_at = time.monotonic()
        self._owned_active = True

    def _health(self):
        if self.process.poll() is not None:
            return 'crashed'
        try:
            state = read_json(self.home / 'gateway_state.json')
            stamp = datetime.fromisoformat(state['updated_at'])
            age = (datetime.now(timezone.utc) - stamp).total_seconds()
            if not 0 <= age < self.config.heartbeat_max_age:
                return 'hung'
            if not owns_pid(self.process.pid, state['pid']):
                return 'ownership_mismatch'
        except (OSError, ValueError, KeyError, TypeError):
            return 'starting' if time.monotonic() - self._launched_at < self.config.startup_grace else 'hung'
        if self.config.mode == 'agent':
            return 'connected'
        bridge_state = probe_bridge(self.bridge_port, self.session, self.config.health_timeout)
        return transport_state(bridge_state, self.config.mode, self._tls_probe)

    def _memory_check(self):
        if sys.platform == 'linux' and self.process.poll() is None:
            if owned_rss_bytes(self.process.pid) > self.config.worker_memory_mb * 1024 * 1024:
                return 'memory_limit'
        return None

    def _run(self):
        try:
            self._loop()
        except Exception:
            # Fixed failure only; never pass exception text to thread excepthook.
            with self._lock:
                self._state = 'worker_failed'
            try:
                self.events.emit('worker_failed', 'worker_failed')
            except Exception:
                pass
            try:
                self._terminate_owned()
            except Exception:
                pass

    def _restartable(self,state,now):
        if state == 'bridge_unavailable':
            if self._bridge_failure_since is None:self._bridge_failure_since=now
            return now-self._bridge_failure_since >= self.config.startup_grace
        self._bridge_failure_since=None
        return state in ('crashed','hung','memory_limit')

    def _loop(self):
        while not self._stop.is_set():
            now = time.monotonic()
            if self._circuit_open:
                state = 'circuit_open'
            elif self._restart_due is not None:
                state = 'backoff'
                if now >= self._restart_due:
                    self._restart_due = None
                    try:
                        self._launch()
                        self._restarts += 1
                        state = 'starting'
                    except (OSError, PolicyError):
                        self._circuit_open = True
                        state = 'circuit_open'
            else:
                state = self._memory_check() or self._health()
                if self._restartable(state,now):
                    self._terminate_owned()
                    self._failures = [t for t in self._failures if now - t < self.config.circuit_window]
                    self._failures.append(now)
                    if len(self._failures) >= self.config.circuit_failures:
                        self._circuit_open = True
                        state = 'circuit_open'
                    else:
                        delay = min(self.config.restart_cap, self.config.restart_base * 2 ** (len(self._failures) - 1))
                        self._restart_due = time.monotonic() + delay
            with self._lock:
                if self._state != state:
                    self.events.emit('state_changed', state)
                self._state = state
                self._last_tick = time.monotonic()
            self._stop.wait(self.config.interval)

    def status(self):
        with self._lock:
            state = self._state
            live = bool(self._thread and self._thread.is_alive() and not self._stop.is_set()
                        and 0 <= time.monotonic() - self._last_tick < self.config.liveness_max_age)
        fixture = self.config.mode == 'fixture'
        agent_only = self.config.mode == 'agent'
        transport = state == 'connected' and live
        return {'state': state, 'live': live, 'ready': transport and not fixture,
                'transport_ready': transport and not agent_only, 'fixture': fixture,
                'health_scope': 'agent_process' if agent_only else ('synthetic_transport' if fixture else 'transport_only'),
                'delivery_proven': False, 'schema': 32 if fixture else None,
                'expected_schema': 32, 'restarts': self._restarts}

    def _terminate_owned(self):
        if not self.process or not self._owned_active:
            return
        if os.name == 'nt':
            if self.process.poll() is None:
                try:
                    self.process.send_signal(signal.CTRL_BREAK_EVENT)
                except OSError:
                    pass
                try:
                    self.process.wait(timeout=self.config.stop_grace)
                except subprocess.TimeoutExpired:
                    pass
            if self._job:
                self._job.close()
                self._job = None
                time.sleep(.05)
            if self.process.poll() is None:
                self.process.wait(timeout=2)
        else:
            # The isolated session/group remains ours even if its leader exited.
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                self.process.wait(timeout=self.config.stop_grace)
            except subprocess.TimeoutExpired:
                pass
            # Grace also applies to descendants after leader exits.
            deadline = time.monotonic() + self.config.stop_grace
            while time.monotonic() < deadline:
                try:
                    os.killpg(self.process.pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(.02)
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            self.process.wait(timeout=2)
        self._owned_active = False

    def stop(self):
        if self._closed:
            return
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=self.config.health_timeout * 3 + self.config.stop_grace * 2 + 3)
            if self._thread.is_alive():
                raise RuntimeError('supervisor worker failed to stop')
        self._terminate_owned()
        try:
            if self.events:
                self.events.emit('stopped')
        finally:
            if self._instance_lock:
                self._instance_lock.close()
                self._instance_lock = None
            with self._lock:
                self._state = 'stopped'
            self._closed = True


def main(argv=None):
    import argparse
    from .status import StatusServer
    parser = argparse.ArgumentParser(description='Isolated Hermes PoC runtime; fixture by default')
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--mode', choices=('fixture', 'agent', 'live'), default='fixture')
    parser.add_argument('--port', type=int, default=8787)
    parser.add_argument('--host', choices=('127.0.0.1', '0.0.0.0'), default='0.0.0.0')
    parser.add_argument('--activation-file', type=Path, default=ACTIVATION,
                        help='compatibility flag; only /data/control/activation.json is accepted')
    parser.add_argument('--worker-memory-mb', type=int, default=1536,
                        help='owned gateway process-group RSS sampling fuse in MiB (Linux only)')
    parser.add_argument('--allow-peer', action='append', default=None,
                        help='literal peer IP; repeated flags replace the default fixed allowlist')
    args = parser.parse_args(argv)
    if args.activation_file != ACTIVATION:
        parser.error('activation path is fixed at /data/control/activation.json')
    if not 0 <= args.port <= 65535:
        parser.error('invalid port')
    if not 64 <= args.worker_memory_mb <= 65536:
        parser.error('invalid worker RSS budget')
    try:
        supervisor = Supervisor(Config(args.data_dir, mode=args.mode, worker_memory_mb=args.worker_memory_mb))
    except (OSError, PolicyError, ValueError):
        print('isolated runtime refused startup', file=sys.stderr)
        return 2
    server = None
    stopped = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT, getattr(signal, 'SIGBREAK', signal.SIGTERM)):
        signal.signal(sig, lambda *_: stopped.set())
    result = 0
    try:
        configure_cli_limits()
        supervisor.start()
        kwargs = {} if args.allow_peer is None else {'allowed': tuple(args.allow_peer)}
        server = StatusServer(supervisor, host=args.host, port=args.port, **kwargs)
        server.start()
        while not stopped.wait(.1):
            if not supervisor._thread.is_alive():
                result = 3
                break
    except (OSError, PolicyError, ValueError):
        print('isolated runtime refused startup', file=sys.stderr)
        result = 2
    finally:
        try:
            supervisor.stop()
        except (OSError, RuntimeError, PolicyError):
            print('isolated runtime cleanup failed', file=sys.stderr)
            result = 3
        if server:
            server.stop()
    return result


if __name__ == '__main__':
    raise SystemExit(main())
