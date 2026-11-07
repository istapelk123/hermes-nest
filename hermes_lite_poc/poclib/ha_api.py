"""HA access with a read-only broker boundary and operator-only writes.
No Supervisor API, SSH, addon management, restart or deletion methods exist here.
"""
import argparse,hashlib,ipaddress,json,os,re,socket,stat,time,urllib.error,urllib.parse,urllib.request
from pathlib import Path
from .policy import private_file
ENTITY=re.compile(r'[a-z_]+\.[a-z0-9_]+')
TARGET=re.compile(r'[a-z0-9][a-z0-9_-]{0,63}')
PROTECTED={'energy','hassio','config','hermes','hermes_poc','hermes_ha_poc'}

def allowed_read(method,path):
    if method!='GET' or not isinstance(path,str) or any(x in path for x in ['%','..','\\','?','#',':','//']):return False
    return path in {'/api/states','/api/config','/api/services'} or (path.startswith('/api/states/') and ENTITY.fullmatch(path[len('/api/states/'):]) is not None)

def validate_base_url(base):
    p=urllib.parse.urlsplit(base)
    if p.scheme not in {'http','https'} or not p.hostname or p.username or p.password or p.query or p.fragment or p.path not in {'','/'}:raise ValueError('HA URL must be a credential-free HTTP(S) origin')
    try:p.port
    except ValueError as exc:raise ValueError('invalid port') from exc
    if p.scheme=='http':
        private=p.hostname in {'homeassistant','homeassistant.local','localhost'}
        try:private=private or ipaddress.ip_address(p.hostname).is_private or ipaddress.ip_address(p.hostname).is_loopback
        except ValueError:pass
        if not private:raise ValueError('unencrypted public HA endpoints are forbidden')
    return base.rstrip('/')

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*_args,**_kwargs):return None

def request_json(base,token,method,path,payload=None,*,read_only=True):
    base=validate_base_url(base)
    if read_only and not allowed_read(method,path):raise ValueError('read broker denied operation')
    if '\r' in token or '\n' in token or not token:raise ValueError('invalid token')
    body=None if payload is None else json.dumps(payload).encode()
    req=urllib.request.Request(base+path,data=body,method=method,headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
    with urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect()).open(req,timeout=10) as response:
        raw=response.read(2*1024*1024+1)
        if len(raw)>2*1024*1024:raise ValueError('HA response too large')
        return json.loads(raw)

def propose(kind,target,payload):
    if kind not in {'automation','dashboard'} or not isinstance(target,str) or TARGET.fullmatch(target) is None or target in PROTECTED:raise ValueError('unsupported proposal target')
    if not isinstance(payload,dict):raise ValueError('proposal payload must be an object')
    core={'kind':kind,'target':target,'payload':payload}
    canonical=json.dumps(core,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
    if len(canonical)>512*1024:raise ValueError('proposal too large')
    return {**core,'sha256':hashlib.sha256(canonical).hexdigest(),'approved':False}

def _operator_gate(proposal,digest):
    if os.name=='nt' or os.geteuid()!=0:raise ValueError('writes require an interactive root/operator command, never the agent uid')
    canonical=propose(proposal['kind'],proposal['target'],proposal['payload'])
    if canonical['sha256']!=digest:raise ValueError('explicit SHA256 approval does not match proposal')
    return canonical

def apply_operator_proposal(proposal,approved_sha256,base,token):
    p=_operator_gate(proposal,approved_sha256)
    if p['kind']=='automation':
        result=request_json(base,token,'POST','/api/config/automation/config/'+p['target'],p['payload'],read_only=False)
        # Read back the exact target before reporting success.
        observed=request_json(base,token,'GET','/api/config/automation/config/'+p['target'],read_only=False)
        if observed!=p['payload']:raise ValueError('automation readback differs; operator inspection required')
        return {'verified':True,'kind':'automation','target':p['target']}
    from websockets.sync.client import connect
    origin=validate_base_url(base);url=('wss' if origin.startswith('https:') else 'ws')+origin[origin.index(':'): ]+'/api/websocket'
    with connect(url,open_timeout=10,close_timeout=5,max_size=2*1024*1024,proxy=None) as ws:
        def receive():return json.loads(ws.recv(timeout=10))
        if receive().get('type')!='auth_required':raise ValueError('unexpected HA websocket handshake')
        ws.send(json.dumps({'type':'auth','access_token':token}))
        if receive().get('type')!='auth_ok':raise ValueError('HA authentication failed')
        ws.send(json.dumps({'id':1,'type':'lovelace/config/save','url_path':p['target'],'config':p['payload']}))
        result=receive()
        if result.get('id')!=1 or not result.get('success'):raise ValueError('HA rejected dashboard save')
        ws.send(json.dumps({'id':2,'type':'lovelace/config','url_path':p['target']}))
        result=receive()
        if result.get('id')!=2 or not result.get('success') or result.get('result')!=p['payload']:raise ValueError('dashboard readback differs')
        return {'verified':True,'kind':'dashboard','target':p['target']}

def broker_read(path,socket_path='/run/hermes/ha.sock'):
    if not allowed_read('GET',path):raise ValueError('unsupported read path')
    if not hasattr(socket,'AF_UNIX'):raise ValueError('Unix broker sockets required')
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
        client.settimeout(12);client.connect(socket_path);client.sendall(json.dumps({'method':'GET','path':path}).encode()+b'\n')
        raw=bytearray()
        while len(raw)<=2*1024*1024:
            chunk=client.recv(65536)
            if not chunk:break
            raw.extend(chunk)
        if len(raw)>2*1024*1024:raise ValueError('broker response too large')
        result=json.loads(raw)
        if not result.get('ok'):raise ValueError('broker could not complete read')
        return result['result']

def main():
    p=argparse.ArgumentParser(description='Read HA through protected Unix broker, or create an offline change proposal')
    sub=p.add_subparsers(dest='command',required=True)
    r=sub.add_parser('read');r.add_argument('path')
    q=sub.add_parser('propose');q.add_argument('kind',choices=['automation','dashboard']);q.add_argument('target');q.add_argument('payload',type=Path)
    a=sub.add_parser('operator-apply');a.add_argument('proposal',type=Path);a.add_argument('--approve-sha256',required=True);a.add_argument('--base-url',required=True)
    args=p.parse_args()
    if args.command=='read':result=broker_read(args.path)
    elif args.command=='propose':result=propose(args.kind,args.target,json.loads(args.payload.read_text()))
    else:
        token_path=private_file('/config/ha-admin-token',root_owned=True)
        result=apply_operator_proposal(json.loads(args.proposal.read_text()),args.approve_sha256,args.base_url,token_path.read_text().strip())
    print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':
    try:main()
    except Exception:raise SystemExit('HA operation refused or failed; no secrets emitted. Inspect the approved target manually.')
