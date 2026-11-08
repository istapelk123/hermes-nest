"""Local-only activation, persistent-home separation and advisory locking."""
import json
import os
from pathlib import Path
import sys

LIVE_COMMAND = ['/opt/venv/bin/python', '/opt/hermes/hermes', 'gateway', 'run', '--quiet']
ACTIVATION = Path('/data/control/activation.json')
LINUX_PATH = '/opt/venv/bin:/opt/node/bin:/usr/local/bin:/usr/bin:/bin'


class PolicyError(RuntimeError):
    pass


class ActivationError(PolicyError):
    pass


def safe_path(path):
    path = Path(path).absolute()
    for component in (path, *path.parents):
        if component.is_symlink() or (hasattr(component, 'is_junction') and component.is_junction()):
            raise PolicyError('symlink or junction rejected')
    return path.resolve(strict=False)

def read_json(path, limit=65536):
    path = safe_path(path)
    with path.open('rb') as stream:
        value = stream.read(limit + 1)
    if len(value) > limit:
        raise ValueError('JSON size limit')
    result = json.loads(value)
    if not isinstance(result, dict):
        raise ValueError('JSON object required')
    return result


def validate_activation(path=ACTIVATION):
    required = {'version': 1, 'operator_approved': True, 'source_gateway_stopped': True,
                'oauth_policy': 'reauthorized', 'whatsapp_policy': 'exclusive-cutover'}
    try:
        value = read_json(path, 4096)
        if set(value) != set(required) or type(value['version']) is not int or value['version'] != 1:
            raise ValueError('unsupported activation')
        if any(type(value[k]) is not type(required[k]) or value[k] != required[k] for k in required):
            raise ValueError('explicit activation policy required')
    except (OSError, ValueError, PolicyError):
        raise ActivationError('valid local operator activation required') from None


def validate_control_metadata(file_uid, file_mode, directory_uid, directory_mode):
    import stat
    if (file_uid != 0 or directory_uid != 0 or file_mode & 0o022 or directory_mode & 0o022
            or not stat.S_ISREG(file_mode) or not stat.S_ISDIR(directory_mode)
            or not file_mode & 0o004 or not directory_mode & 0o001):
        raise ActivationError('activation must be root-owned, non-writable and operator-readable')


def enforce_live_activation():
    if sys.platform != 'linux' or os.geteuid() == 0:
        raise ActivationError('live requires an unprivileged isolated Linux container')
    try:
        path = safe_path(ACTIVATION)
        file_info, directory_info = path.stat(), path.parent.stat()
        validate_control_metadata(file_info.st_uid, file_info.st_mode,
                                  directory_info.st_uid, directory_info.st_mode)
        validate_activation(path)
    except (OSError, PolicyError):
        raise ActivationError('valid immutable local operator activation required') from None


def validate_live_artifacts(hermes_root=Path('/opt/hermes'), node=Path('/opt/node/bin/node'),
                            python=Path('/opt/venv/bin/python')):
    """Offline preflight prevents the pinned adapter's npm/pm bootstrap branch.

    Upstream adapter.py:_file_content_hash uses SHA-256's first 16 hex digits.
    The supervisor never writes this stamp or attempts an install to repair it.
    """
    import hashlib
    try:
        root = safe_path(hermes_root)
        bridge = root / 'scripts' / 'whatsapp-bridge'
        for binary in (Path(node), Path(python), root / 'hermes'):
            if not binary.is_file() or not os.access(binary, os.X_OK):
                raise ValueError('missing packaged executable')
        package = safe_path(bridge / 'package.json')
        if package.stat().st_size > 1024 * 1024:
            raise ValueError('unexpected package manifest')
        expected = hashlib.sha256(package.read_bytes()).hexdigest()[:16]
        stamp = safe_path(bridge / 'node_modules' / '.hermes-pkg-hash')
        with stamp.open('rb') as stream:
            actual = stream.read(65).decode('utf-8-sig').strip()
        if actual != expected:
            raise ValueError('bridge dependencies are not sealed')
        if sys.platform == 'linux' and root == Path('/opt/hermes'):
            info = root.stat()
            if info.st_uid != 0 or info.st_mode & 0o022 or os.access(root, os.W_OK):
                raise ValueError('packaged source must be immutable to worker')
    except (OSError, ValueError, PolicyError):
        raise PolicyError('sealed offline runtime artifacts required; no startup installer permitted') from None


def enforce_agent_isolation(home):
    """Agent-only is never a shortcut around WhatsApp cutover approval."""
    import hermes_yaml as yaml
    home = safe_path(home)
    for relative in ('.env', 'whatsapp/session/creds.json', 'platforms/whatsapp/session/creds.json'):
        if (home / relative).exists():
            raise PolicyError('agent-only refuses messaging credential material')
    config = yaml.safe_load((home / 'config.yaml').read_text(encoding='utf-8')) or {}
    platforms = config.get('platforms', {})
    if not isinstance(platforms, dict) or any(
            name != 'local' and (not isinstance(value, dict) or value.get('enabled') is not False)
            for name, value in platforms.items()):
        raise PolicyError('agent-only requires all messaging platforms disabled')
    if config.get('gateway', {}).get('platforms') not in (None, [], ['local']):
        raise PolicyError('agent-only refuses a messaging platform list')


def child_environment(home):
    """Never inherit provider, OAuth, HA/Supervisor tokens or arbitrary env."""
    home = safe_path(home)
    env = {'HOME': str(home), 'HERMES_HOME': str(home), 'USERPROFILE': str(home),
           'TMP': str(home / 'tmp'), 'TEMP': str(home / 'tmp'), 'TMPDIR': str(home / 'tmp'),
           'PYTHONNOUSERSITE': '1', 'PYTHONUNBUFFERED': '1', 'HERMES_REDACT_SECRETS': 'true', 'LANG': 'C.UTF-8',
           'PATH': LINUX_PATH,
           'HERMES_INSTALL_DIR': '/opt/hermes', 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONPATH': '/opt/poc',
           'NODE_OPTIONS': '--max-old-space-size=256'}
    import re
    zone=os.environ.get('TZ','Europe/Amsterdam')
    if not re.fullmatch(r'[A-Za-z_]+(?:/[A-Za-z0-9_+\-]+)*',zone):raise PolicyError('invalid timezone')
    env['TZ']=zone
    env['HERMES_POC_PRIVATE_LOGS']='1'
    # Pinned image already packages dependencies; PM-generated symlinks in the
    # protected state tree otherwise make the next boot fail its link gate.
    env['HERMES_DISABLE_LAZY_INSTALLS']='1'
    if os.name == 'nt':
        # OS directory is needed to load native Python DLLs, not user config.
        system = os.environ.get('SystemRoot', r'C:\Windows')
        env.update(SystemRoot=system, WINDIR=system,
                   APPDATA=str(home / 'appdata'), LOCALAPPDATA=str(home / 'local'),
                   PATH=str(Path(sys.executable).parent) + os.pathsep + str(Path(system) / 'System32'))
    return env


class FileLock:
    def __init__(self, path):
        self.path = safe_path(path)
        self.file = None

    def acquire(self):
        flags = os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0)
        descriptor = os.open(self.path, flags, 0o600)
        self.file = os.fdopen(descriptor, 'r+b', buffering=0)
        try:
            if os.name == 'nt':
                import msvcrt
                if os.fstat(descriptor).st_size == 0:
                    self.file.write(b'0')
                self.file.seek(0)
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            self.file = None
            raise PolicyError('another supervisor holds this data directory') from None

    def close(self):
        if self.file:
            self.file.close()
            self.file = None


def synthetic_database(path):
    """Read only our tiny generated fixture marker, never migration contents."""
    import sqlite3
    path = safe_path(path)
    if not path.is_file() or path.stat().st_size > 1024 * 1024:
        return False
    connection = None
    try:
        connection = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=.2)
        return (connection.execute('SELECT version FROM schema_version LIMIT 2').fetchall() == [(32,)]
                and connection.execute('SELECT synthetic FROM fixture_marker LIMIT 2').fetchall() == [(1,)])
    except sqlite3.Error:
        return False
    finally:
        if connection:
            connection.close()


def prepared_home_allowed(data, mode, expected=None):
    """Recognize only the parent's fixed, non-secret seed layout in /data.

    No seed configuration or skill code is imported/read by the supervisor.
    expected is an explicit path seam for isolated filesystem unit tests.
    """
    data = safe_path(data)
    canonical = Path('/data/hermes-fixture' if mode == 'fixture' else '/data/hermes') if expected is None else Path(expected)
    if data != canonical.absolute():
        return False
    allowed = {'supervisor.lock', 'tmp', 'workspace', 'logs', 'memories', 'sessions',
               'skills', 'config.yaml', 'SOUL.md', 'AGENTS.md', 'state.db'}
    if mode == 'fixture':
        if (data / 'state.db').exists() and not synthetic_database(data / 'state.db'):
            return False
        marker = safe_path(data / '.poc-fixture')
        try:
            with marker.open('rb') as stream:
                if stream.read(32) != b'synthetic':
                    return False
        except OSError:
            return False
        allowed.add('.poc-fixture')
    return all(entry.name in allowed for entry in data.iterdir())


def prepare_home(data, mode):
    data = safe_path(data)
    code = Path(__file__).resolve()
    if data == code.parent or data in code.parents or data.is_relative_to(Path('/opt/hermes').absolute()):
        raise PolicyError('source and persistent data must be separate')
    home = safe_path(data)
    if mode == 'fixture':
        if (home / 'state.db').exists() and not synthetic_database(home / 'state.db'):
            raise PolicyError('non-synthetic database rejected in fixture home')
        for relative in ('auth.json', '.env', 'vault/vault.key', 'whatsapp/session/creds.json',
                         'platforms/whatsapp/session/creds.json'):
            if safe_path(home / relative).exists():
                raise PolicyError('credential material forbidden in fixture home')
    meta = safe_path(data / 'runtime-meta.json')
    if meta.exists():
        try:
            value = read_json(meta)
        except (OSError, ValueError):
            raise PolicyError('invalid runtime metadata') from None
        if value != {'version': 1, 'mode': mode, 'generated_by': 'isolated-ha-poc'}:
            raise PolicyError('persistent home mode collision')
    else:
        if (any(entry.name != 'supervisor.lock' for entry in data.iterdir())
                and not prepared_home_allowed(data, mode)):
            raise PolicyError('nonempty unowned data directory rejected')
        meta.write_text(json.dumps({'version': 1, 'mode': mode, 'generated_by': 'isolated-ha-poc'}), encoding='utf-8')
    default = safe_path(home / 'platforms' / 'whatsapp' / 'session')
    legacy = safe_path(home / 'whatsapp' / 'session')
    selected = legacy if legacy.exists() and not default.exists() else default
    for path in (home, home / 'tmp', selected):
        safe_path(path).mkdir(parents=True, exist_ok=True)
    # Only inspect this generated home's filesystem; never read/copy credentials.
    for base, directories, files in os.walk(home, followlinks=False):
        for name in directories + files:
            safe_path(Path(base) / name)
    return selected
