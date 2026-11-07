"""Root-only read broker. The unprivileged agent never receives the HA token."""
import argparse,json,os,socket,socketserver,struct,sys,threading
from pathlib import Path
from .ha_api import allowed_read,request_json,validate_base_url
from .policy import private_file
class BrokerHandler(socketserver.StreamRequestHandler):
    def handle(self):
        self.connection.settimeout(12)
        try:
            if hasattr(socket,'SO_PEERCRED'):
                _pid,uid,_gid=struct.unpack('3i',self.connection.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
                if uid not in {0,10001}:raise ValueError('wrong peer uid')
            raw=self.rfile.readline(4097)
            if len(raw)>4096 or not raw.endswith(b'\n'):raise ValueError('request too large')
            data=json.loads(raw)
            if not isinstance(data,dict) or set(data)!={'method','path'} or not allowed_read(data['method'],data['path']):raise ValueError('read denied')
            token=private_file(self.server.token_file,root_owned=True).read_text(encoding='utf-8').strip()
            result=request_json(self.server.base_url,token,'GET',data['path'])
            response={'ok':True,'result':result}
        except Exception:response={'ok':False,'error':'HA read unavailable or denied'}
        # Never log request bodies, tokens, account IDs or exception strings.
        self.wfile.write(json.dumps(response,separators=(',',':')).encode())

class Broker(socketserver.ThreadingMixIn,socketserver.UnixStreamServer):
    daemon_threads=True
    request_queue_size=8
    _slots=threading.BoundedSemaphore(4)
    def process_request(self,request,address):
        if not self._slots.acquire(blocking=False):
            self.shutdown_request(request);return
        try:super().process_request(request,address)
        except Exception:
            self._slots.release();raise
    def process_request_thread(self,request,address):
        try:super().process_request_thread(request,address)
        finally:self._slots.release()
    def handle_error(self,*_args):pass

def main():
    p=argparse.ArgumentParser();p.add_argument('--base-url',required=True);p.add_argument('--socket',default='/run/hermes/ha.sock');p.add_argument('--token-file',default='/config/ha-read-token');a=p.parse_args()
    if os.name=='nt' or os.geteuid()!=0:raise SystemExit('Broker requires the Linux operator uid')
    base=validate_base_url(a.base_url);private_file(a.token_file,root_owned=True)
    target=Path(a.socket);target.parent.mkdir(parents=True,exist_ok=True);os.chown(target.parent,0,10001);target.parent.chmod(0o750)
    if target.exists():
        if not target.is_socket():raise SystemExit('Refusing to replace non-socket')
        target.unlink()
    with Broker(str(target),BrokerHandler) as server:
        server.base_url=base;server.token_file=a.token_file
        os.chown(target,0,10001);target.chmod(0o660)
        server.serve_forever(poll_interval=.5)
if __name__=='__main__':main()
