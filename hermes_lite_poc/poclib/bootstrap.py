"""Fixed root PID1 launcher. Agent/supervisor run as uid 10001; no shell commands.
Root is retained only for the optional token broker and process lifecycle.
"""
import json,os,signal,sqlite3,subprocess,sys,time,shutil
from pathlib import Path
from .policy import validate_options,load_activation,check_schema,reject_links
UID=GID=10001

def _drop_agent():
    import resource
    resource.setrlimit(resource.RLIMIT_CORE,(0,0));resource.setrlimit(resource.RLIMIT_NOFILE,(1024,1024))
    os.setgroups([]);os.setgid(GID);os.setuid(UID)

def clean_env(home,timezone):
    return {'PATH':'/opt/venv/bin:/opt/node/bin:/usr/local/bin:/usr/bin:/bin','LANG':'C.UTF-8','LC_ALL':'C.UTF-8','TZ':timezone,'HOME':str(home),'HERMES_HOME':str(home),'HERMES_INSTALL_DIR':'/opt/hermes','PYTHONPATH':'/opt/poc','PYTHONDONTWRITEBYTECODE':'1','PYTHONUNBUFFERED':'1','TMPDIR':str(home/'tmp')}

def prepare_home(home,seed,*,fixture=False):
    home=Path(home);seed=Path(seed);reject_links(home)
    home.mkdir(parents=True,exist_ok=True);home.chmod(0o700)
    if fixture and any((home/p).exists() for p in ['auth.json','.env','whatsapp/session/creds.json','platforms/whatsapp/session/creds.json','vault/vault.key']):raise ValueError('credentials are forbidden in fixture home')
    for name in ['tmp','workspace','logs','memories','sessions']:(home/name).mkdir(exist_ok=True)
    manifest=json.loads((seed/'skills/.bundle-manifest.json').read_text(encoding='utf-8'))
    for item in manifest['files']:
        p=seed/'skills'/item['path']
        import hashlib
        if not p.is_file() or p.is_symlink() or hashlib.sha256(p.read_bytes()).hexdigest()!=item['sha256']:raise ValueError('seed skill integrity failure')
    if not (home/'skills').exists():shutil.copytree(seed/'skills',home/'skills')
    for name in ['config.yaml','SOUL.md','AGENTS.md']:
        dest=home/name
        if not dest.exists():shutil.copyfile(seed/name,dest);dest.chmod(0o600)
    check_schema(home/'state.db')
    if fixture:(home/'.poc-fixture').write_text('synthetic',encoding='utf-8')
    if os.name!='nt' and os.geteuid()==0:
        for item in [home,*home.rglob('*')]:
            if item.is_symlink():raise ValueError('state symlink refused')
            os.chown(item,UID,GID)
            if item.is_file() and (item.name in {'auth.json','.env','creds.json','vault.key','vault.json.enc'}):item.chmod(0o600)


def main():
    if os.name=='nt' or os.geteuid()!=0:raise SystemExit('Use the isolated image; launcher requires Linux uid0')
    os.umask(0o077)
    options_path=Path('/data/options.json');options=validate_options(json.loads(options_path.read_text()) if options_path.exists() else {})
    control=Path('/data/control');reject_links(control);control.mkdir(exist_ok=True);os.chown(control,0,0);control.chmod(0o755)
    if options['mode']=='live':load_activation(control/'activation.json')
    (control/'mode.json').write_text(options['mode'],encoding='utf-8');(control/'mode.json').chmod(0o644)
    home=Path('/data/hermes-fixture' if options['mode']=='fixture' else '/data/hermes')
    prepare_home(home,Path('/opt/poc/seed'),fixture=options['mode']=='fixture')
    env=clean_env(home,options['timezone'])
    # This exact launcher does not leak SUPERVISOR_TOKEN, inherited OAuth, Windows HOME or proxy credentials.
    broker=None;worker=None;stopping=False
    def stop(_signal=None,_frame=None):
        nonlocal stopping
        stopping=True
        for process in [worker,broker]:
            if process is not None and process.poll() is None:
                try:os.killpg(process.pid,signal.SIGTERM)
                except ProcessLookupError:pass
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    try:
        if options['homeassistant_enabled']:
            from .ha_api import validate_base_url
            validate_base_url(options['homeassistant_url'])
            broker=subprocess.Popen([sys.executable,'-m','poclib.ha_broker','--base-url',options['homeassistant_url']],env=env,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
        cmd=[sys.executable,'-m','runtime.supervisor','--data-dir',str(home),'--mode',options['mode'],'--port','8787','--activation-file',str(control/'activation.json'),'--worker-memory-mb',str(options['worker_memory_mb'])]
        worker=subprocess.Popen(cmd,env=env,stdin=subprocess.DEVNULL,start_new_session=True,preexec_fn=_drop_agent)
        while not stopping:
            if worker.poll() is not None:return worker.returncode or 1
            if broker is not None and broker.poll() is not None:return 1
            time.sleep(.25)
        return 0
    finally:
        stop();deadline=time.monotonic()+15
        for process in [worker,broker]:
            if process is None:continue
            try:process.wait(timeout=max(0,deadline-time.monotonic()))
            except subprocess.TimeoutExpired:
                try:os.killpg(process.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                process.wait(timeout=5)
if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception:raise SystemExit('PoC refused startup. Check non-secret policy/configuration; no credential values emitted.')
