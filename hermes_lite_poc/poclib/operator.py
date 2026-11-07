"""Manual Linux/root provisioning only; never starts a gateway or copies auth."""
import argparse,json,os
from pathlib import Path
from .bootstrap import prepare_home,UID,GID

def require_operator(acknowledged):
    if acknowledged is not True or os.name=='nt' or os.geteuid()!=0:raise ValueError('explicit Linux root operator authorization required')

def main():
    p=argparse.ArgumentParser(description='Prepare an EMPTY independent live home, without activation or login')
    p.add_argument('action',choices=['prepare-live']);p.add_argument('--operator-authorized',action='store_true');a=p.parse_args()
    require_operator(a.operator_authorized)
    home=Path('/data/hermes');prepare_home(home,Path('/opt/poc/seed'),fixture=False)
    # Initialize this pinned runtime's home provenance BEFORE operator OAuth/pairing
    # populate it; otherwise its nonempty-home guard correctly refuses adoption.
    from runtime.policy import prepare_home as initialize_runtime_home
    initialize_runtime_home(home,'live')
    for item in [home,*home.rglob('*')]:
        if item.is_symlink():raise ValueError('links refused')
        os.chown(item,UID,GID)
    (home/'runtime-meta.json').chmod(0o600)
    print(json.dumps({'prepared':True,'gateway_started':False,'credentials_copied':False,'activation_created':False}))
if __name__=='__main__':
    try:main()
    except Exception:raise SystemExit('Operator preparation refused; no credentials emitted.')
