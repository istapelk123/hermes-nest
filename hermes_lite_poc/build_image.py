"""Deterministic build input verifier/extractor, no download or installer execution."""
import argparse,hashlib,json,re,tarfile
from pathlib import Path,PurePosixPath
from privacy_build import apply_privacy_patches,seal_bridge_dependencies

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()

def extract_source(archive,destination,expected):
    archive=Path(archive);destination=Path(destination)
    if sha(archive)!=expected:raise ValueError('source archive checksum mismatch')
    if destination.exists():raise ValueError('source destination must not exist')
    with tarfile.open(archive,'r:gz') as t:
        members=t.getmembers();seen=set();total=0
        for m in members:
            p=PurePosixPath(m.name)
            if not m.isfile() or p.is_absolute() or '..' in p.parts or '\\' in m.name or ':' in m.name or p.as_posix()!=m.name or m.name in seen:raise ValueError('unsafe source member')
            seen.add(m.name);total+=m.size
            if total>512*1024*1024:raise ValueError('source expansion exceeds budget')
        destination.mkdir(parents=True)
        for m in members:
            path=destination/m.name;path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(t.extractfile(m).read());path.chmod(m.mode&0o755)

def check_source_schema(root):
    text=(Path(root)/'hermes_state_common.py').read_text(encoding='utf-8')
    match=re.search(r'^SCHEMA_VERSION\s*=\s*(\d+)\s*$',text,re.M)
    if not match or int(match[1])!=32:raise ValueError('build must use Hermes database schema32')
    return int(match[1])

def prepare(root,source_dest):
    root=Path(root);lock=json.loads((root/'build-lock.json').read_text())
    if sha(root/'vendor/node-linux-x64.tar.xz')!=lock['node_sha256']:raise ValueError('Node checksum mismatch')
    if sha(root/'requirements-linux.lock')!=lock['requirements_sha256']:raise ValueError('Python lock checksum mismatch')
    extract_source(root/'vendor/hermes-source.tar.gz',source_dest,lock['source_sha256']);check_source_schema(source_dest)
    project=Path(source_dest)/'pyproject.toml';text=project.read_text(encoding='utf-8')
    old='version = "0.0.0"'
    if text.count(old)!=1:raise ValueError('unexpected upstream package version placeholder')
    # Packaging identity only: no runtime/gateway/database logic changes.
    project.write_text(text.replace(old,'version = "0.22.7"'),encoding='utf-8',newline='\n')
    apply_privacy_patches(source_dest)
    (Path(source_dest)/'POC_BUILD.json').write_text(json.dumps(lock,sort_keys=True),encoding='utf-8')
    return lock

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('input',type=Path);p.add_argument('destination',type=Path);a=p.parse_args();prepare(a.input,a.destination)
