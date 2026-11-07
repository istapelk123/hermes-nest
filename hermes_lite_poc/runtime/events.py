"""Fixed-vocabulary events only: no child output, identifiers, paths or exceptions."""
from datetime import datetime, timezone
import json
import os
import threading
from .policy import safe_path

STATES = frozenset({'starting', 'connected', 'waiting_for_auth', 'network_down',
                    'crashed', 'hung', 'memory_limit', 'bridge_unavailable', 'session_mismatch',
                    'ownership_mismatch', 'backoff', 'circuit_open', 'stopped', 'worker_failed'})
EVENTS = frozenset({'started', 'state_changed', 'restarting', 'circuit_open', 'stopped', 'worker_failed'})


class EventLog:
    def __init__(self, data_dir, max_bytes=65536, copies=3):
        if max_bytes < 256 or not 1 <= copies <= 10:
            raise ValueError('invalid log bounds')
        self.path = safe_path(data_dir / 'events.jsonl')
        self.max_bytes = max_bytes
        self.copies = copies
        self.lock = threading.Lock()

    def emit(self, event, state=None):
        if event not in EVENTS or (state is not None and state not in STATES):
            raise ValueError('event vocabulary rejected')
        record = {'time': datetime.now(timezone.utc).isoformat(), 'event': event}
        if state is not None:
            record['state'] = state
        body = (json.dumps(record, separators=(',', ':')) + '\n').encode('utf-8')
        with self.lock:
            paths = [safe_path(self.path)] + [safe_path(self.path.with_name(self.path.name + '.' + str(i)))
                                              for i in range(1, self.copies + 1)]
            if paths[0].exists() and paths[0].stat().st_size + len(body) > self.max_bytes:
                paths[-1].unlink(missing_ok=True)
                for source, destination in reversed(list(zip(paths[:-1], paths[1:]))):
                    if source.exists():
                        os.replace(source, destination)
            descriptor = os.open(paths[0], os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
            try:
                os.write(descriptor, body)
            finally:
                os.close(descriptor)
