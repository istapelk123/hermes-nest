"""Build-time fetch of a pinned public Node distribution; never at runtime."""
import hashlib,json,os,urllib.request
from pathlib import Path
root=Path(__file__).resolve().parent
lock=json.loads((root/'build-lock.json').read_text())
version=lock['node_version']
url=f'https://nodejs.org/dist/v{version}/node-v{version}-linux-x64.tar.xz'
target=root/'vendor/node-linux-x64.tar.xz'
if target.exists():
    if hashlib.sha256(target.read_bytes()).hexdigest()!=lock['node_sha256']:raise SystemExit('Existing Node checksum mismatch')
else:
    target.parent.mkdir(exist_ok=True)
    temporary=target.with_suffix('.download')
    digest=hashlib.sha256();size=0
    with urllib.request.urlopen(url,timeout=60) as response, temporary.open('xb') as output:
        while chunk:=response.read(1024*1024):
            size+=len(chunk)
            if size>128*1024*1024:raise SystemExit('Node download exceeds size bound')
            digest.update(chunk);output.write(chunk)
    if digest.hexdigest()!=lock['node_sha256']:raise SystemExit('Downloaded Node checksum mismatch')
    os.replace(temporary,target)
