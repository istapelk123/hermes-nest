"""Small fail-closed validation; no agent imports or side effects."""
import json,os,re,sqlite3,stat
from pathlib import Path
SCHEMA=32
MODEL='gpt-6.1-sol'
PROVIDER='openai-codex'

def validate_options(options):
    if not isinstance(options,dict):raise ValueError('options must be an object')
    allowed={'mode','timezone','provider','model','worker_memory_mb','homeassistant_enabled','homeassistant_url','enable_browser'}
    if set(options)-allowed:raise ValueError('unsupported option')
    result={'mode':'fixture','timezone':'Europe/Amsterdam','provider':PROVIDER,'model':MODEL,'worker_memory_mb':1536,'homeassistant_enabled':False,'homeassistant_url':'http://homeassistant:80','enable_browser':False,**options}
    if result['mode'] not in {'fixture','agent','live'}:raise ValueError('invalid mode')
    if result['provider']!=PROVIDER or result['model']!=MODEL:raise ValueError('this image supports the pinned cloud provider/model only')
    if type(result['worker_memory_mb']) is not int or not 512<=result['worker_memory_mb']<=2048:raise ValueError('worker memory must be 512..2048 MiB')
    if type(result['homeassistant_enabled']) is not bool or type(result['enable_browser']) is not bool:raise ValueError('boolean option required')
    if result['enable_browser']:raise ValueError('browser image is not built/validated in this PoC')
    if not re.fullmatch(r'[A-Za-z_]+(?:/[A-Za-z0-9_+\-]+)*',result['timezone']):raise ValueError('invalid timezone')
    if result['mode']=='fixture' and result['homeassistant_enabled']:raise ValueError('fixture mode must not connect to production HA')
    return result

def validate_activation(value):
    expected={'version':1,'operator_approved':True,'source_gateway_stopped':True,'oauth_policy':'reauthorized','whatsapp_policy':'exclusive-cutover'}
    if not isinstance(value,dict) or set(value)!=set(expected) or any(type(value.get(k)) is not type(v) or value.get(k)!=v for k,v in expected.items()):raise ValueError('live cutover is not explicitly authorized')
    return True

def private_file(path,*,root_owned=False):
    p=Path(path)
    if p.is_symlink() or not p.is_file():raise ValueError('regular file required')
    s=p.stat()
    if os.name!='nt':
        if s.st_mode & 0o077:raise ValueError('secret file permissions must be 0600')
        if root_owned and s.st_uid!=0:raise ValueError('operator file must be root owned')
    return p

def reject_links(root):
    p=Path(root)
    for item in [p,*p.parents]:
        if item.is_symlink():raise ValueError('symbolic link in protected path')
    if p.exists():
        for item in p.rglob('*'):
            if item.is_symlink():raise ValueError('symbolic links are not accepted in state trees')

def check_schema(path,expected=SCHEMA):
    p=Path(path)
    if not p.exists():return None
    if p.is_symlink():raise ValueError('database symlink refused')
    try:
        con=sqlite3.connect(p.resolve().as_uri()+'?mode=ro',uri=True)
        try:
            rows=con.execute('select version from schema_version').fetchall()
            if len(rows)!=1 or type(rows[0][0]) is not int:raise ValueError('invalid schema record')
            version=rows[0][0]
            if version!=expected:raise ValueError(f'database schema {version}; this pinned runtime requires {expected}')
            if con.execute('pragma quick_check').fetchone()[0]!='ok':raise ValueError('database integrity check failed')
            return version
        finally:con.close()
    except sqlite3.Error as exc:raise ValueError('not a valid Hermes state database') from exc

def load_activation(path):
    p=Path(path)
    if p.is_symlink() or not p.is_file():raise ValueError('regular activation file required')
    s=p.stat()
    if os.name!='nt' and (s.st_uid!=0 or s.st_mode & 0o022):raise ValueError('activation must be root owned and not group/world writable')
    if p.stat().st_size>4096:raise ValueError('activation record too large')
    value=json.loads(p.read_text(encoding='utf-8'));validate_activation(value);return value
