"""Consistent DATA snapshots. Credentials/WhatsApp are deliberately never imported.
Production requires a root/operator approval and encryption key. Fixture archives
are plaintext only because they contain synthetic data. Whole-addon HA backups
are the separate recovery mechanism for paired/authenticated production state.
"""
import argparse,gzip,hashlib,io,json,os,sqlite3,tarfile,tempfile
from pathlib import Path,PurePosixPath
from .policy import SCHEMA,check_schema,reject_links,load_activation
LIMIT=256*1024*1024
MAGIC=b'HERMESPOC1\n'

def _allowed(name):
    p=PurePosixPath(name)
    if p.is_absolute() or '..' in p.parts or '\\' in name or ':' in name or p.as_posix()!=name:return False
    return name in {'SOUL.md','state.db','memories/MEMORY.md','memories/USER.md'} or (len(p.parts)>=2 and p.parts[0]=='sessions' and p.suffix in {'.json','.jsonl','.md'})

def _authorize(home,approval,key):
    home=home.resolve();test_root=Path(__file__).resolve().parents[2]/'.test-work'
    test_home=home.is_relative_to(test_root)
    container_fixture=False
    if home==Path('/data/hermes-fixture') and os.name!='nt':
        control=Path('/data/control/mode.json')
        if control.is_file() and not control.is_symlink():
            st=control.stat()
            container_fixture=st.st_uid==0 and not st.st_mode&0o022 and control.read_text().strip()=='fixture'
    marker=home/'.poc-fixture'
    if (test_home or container_fixture) and marker.is_file() and not marker.is_symlink() and marker.stat().st_size<=64 and marker.read_text().strip()=='synthetic':return True
    raise ValueError('PoC DATA export is restricted to the fixed fixture boundary; production migration is disabled')

def create_snapshot(home,destination,*,approval=None,encryption_key=None):
    home=Path(home);destination=Path(destination);reject_links(home)
    fixture=_authorize(home,approval,encryption_key)
    if destination.exists():raise ValueError('never overwrite a backup')
    if destination.resolve().is_relative_to(home.resolve()):raise ValueError('backup must be outside the source home')
    destination.parent.mkdir(parents=True,exist_ok=True)
    data={}
    for path in sorted(home.rglob('*')):
        if not path.is_file():continue
        name=path.relative_to(home).as_posix()
        if not _allowed(name) or name=='state.db':continue
        if path.stat().st_size>LIMIT:raise ValueError('snapshot exceeds size budget')
        data[name]=path.read_bytes()
        if sum(map(len,data.values()))>LIMIT:raise ValueError('snapshot exceeds size budget')
    db=home/'state.db'
    if db.exists():
        check_schema(db)
        with tempfile.TemporaryDirectory(prefix='poc-db-',dir=destination.parent) as t:
            target=Path(t)/'state.db'
            src=sqlite3.connect(db.resolve().as_uri()+'?mode=ro',uri=True)
            dst=sqlite3.connect(target)
            try:src.backup(dst);dst.commit()
            finally:dst.close();src.close()
            check_schema(target)
            if target.stat().st_size>LIMIT:raise ValueError('database exceeds size budget')
            data['state.db']=target.read_bytes()
    if sum(map(len,data.values()))>LIMIT:raise ValueError('snapshot exceeds size budget')
    manifest={'format':'hermes-poc-data-v1','schema':SCHEMA,'fixture':fixture,'credentials_included':False,'files':{k:hashlib.sha256(v).hexdigest() for k,v in data.items()}}
    output=io.BytesIO()
    with tarfile.open(fileobj=output,mode='w:gz') as archive:
        for name,content in [*data.items(),('manifest.json',json.dumps(manifest,sort_keys=True).encode())]:
            member=tarfile.TarInfo(name);member.size=len(content);member.mode=0o600;archive.addfile(member,io.BytesIO(content))
    payload=output.getvalue()
    if encryption_key is not None or not fixture:
        from cryptography.fernet import Fernet
        payload=MAGIC+Fernet(encryption_key).encrypt(payload)
    destination.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(destination,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'wb') as stream:stream.write(payload)
    return manifest

def restore_snapshot(archive_path,destination,*,encryption_key=None):
    path=Path(archive_path);destination=Path(destination)
    if destination.exists() and any(destination.iterdir()):raise ValueError('restore destination must be empty')
    reject_links(destination)
    if path.stat().st_size>LIMIT*2:raise ValueError('archive exceeds size budget')
    payload=path.read_bytes();encrypted=payload.startswith(MAGIC)
    if encrypted:
        if encryption_key is None:raise ValueError('encryption key required')
        from cryptography.fernet import Fernet
        payload=Fernet(encryption_key).decrypt(payload[len(MAGIC):])
    files={};total=0;previous_end=0;metadata=0
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(payload)) as compressed:
            expanded=compressed.read(LIMIT+1024*1024+1)
        if len(expanded)>LIMIT+1024*1024:raise ValueError('archive payload/metadata budget exceeded')
        with tarfile.open(fileobj=io.BytesIO(expanded),mode='r:') as archive:
            for item in archive:
                if len(files)>=2048:raise ValueError('archive entry budget exceeded')
                metadata+=max(0,item.offset_data-previous_end);previous_end=item.offset_data+((item.size+511)//512)*512
                if metadata>1024*1024:raise ValueError('archive metadata budget exceeded')
                if not item.isfile() or item.name in files or (item.name!='manifest.json' and not _allowed(item.name)):raise ValueError('unsafe or duplicate archive member')
                total+=item.size
                if total>LIMIT or item.size<0:raise ValueError('expanded archive exceeds size budget')
                files[item.name]=archive.extractfile(item).read()
        manifest=json.loads(files.pop('manifest.json'))
    except (tarfile.TarError,KeyError,json.JSONDecodeError) as exc:raise ValueError('invalid data snapshot') from exc
    if manifest.get('format')!='hermes-poc-data-v1' or manifest.get('schema')!=SCHEMA:raise ValueError('incompatible snapshot')
    if not manifest.get('fixture') and not encrypted:raise ValueError('production history must be encrypted')
    if manifest.get('credentials_included') is not False:raise ValueError('credential import is not supported')
    if manifest.get('files')!={k:hashlib.sha256(v).hexdigest() for k,v in files.items()}:raise ValueError('snapshot checksum mismatch')
    destination.parent.mkdir(parents=True,exist_ok=True)
    # Validate and stage everything before publishing the destination.
    with tempfile.TemporaryDirectory(prefix='poc-restore-',dir=destination.parent) as t:
        staging=Path(t)/'home';staging.mkdir()
        for name,content in files.items():
            p=staging/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(content);p.chmod(0o600)
        if (staging/'state.db').exists():check_schema(staging/'state.db')
        if manifest.get('fixture'):(staging/'.poc-fixture').write_text('synthetic',encoding='utf-8')
        if destination.exists():destination.rmdir()
        staging.replace(destination)
    return manifest

def main():
    p=argparse.ArgumentParser(description='Synthetic fixture data backup/restore; never migrates credentials')
    p.add_argument('operation',choices=['backup','restore']);p.add_argument('source',type=Path);p.add_argument('destination',type=Path)
    a=p.parse_args()
    # CLI intentionally offers no production approval/key flags in the PoC.
    if a.operation=='backup':create_snapshot(a.source,a.destination)
    else:restore_snapshot(a.source,a.destination)
if __name__=='__main__':main()
