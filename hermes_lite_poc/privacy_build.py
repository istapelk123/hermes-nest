"""Audited deterministic build-only privacy patches for the exact pinned source.
No patch is applied to the running Windows installation. Fails on source drift.
"""
import ast,hashlib,json
from pathlib import Path

def apply_privacy_patches(root):
    root=Path(root)
    changes=[
        ('plugins/platforms/whatsapp/adapter.py',
         'self._bridge_log = self._session_path.parent / "bridge.log"',
         'self._bridge_log = Path(os.devnull)  # POC_PRIVACY: raw QR/account output is discarded'),
        ('hermes_logging.py',
         '    log_dir = mkdir_under_hermes_home(home / "logs")\n',
         '    log_dir = mkdir_under_hermes_home(home / "logs")\n    if os.environ.get("HERMES_POC_PRIVATE_LOGS") == "1":\n        # POC_PRIVACY: only the separate structured supervisor event log persists.\n        logging.disable(logging.CRITICAL)\n        return log_dir\n'),
        ('gateway/run_turn.py',
         '    tool_logger = logging.getLogger("hermes.tool_calls")\n',
         '    tool_logger = logging.getLogger("hermes.tool_calls")\n    if os.environ.get("HERMES_POC_PRIVATE_LOGS") == "1":\n        # POC_PRIVACY: tool payloads are history, not diagnostic logs.\n        tool_logger.handlers.clear()\n        tool_logger.addHandler(logging.NullHandler())\n        tool_logger.propagate = False\n        return tool_logger\n')]
    prepared=[]
    for relative,old,new in changes:
        path=root/relative;text=path.read_text(encoding='utf-8')
        if new not in text:
            if text.count(old)!=1:raise ValueError('privacy patch source drift: '+relative)
            text=text.replace(old,new,1)
        ast.parse(text,filename=relative);prepared.append((path,text))
    record={}
    for path,text in prepared:
        path.write_text(text,encoding='utf-8',newline='\n');record[path.relative_to(root).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
    (root/'POC_PRIVACY_PATCHES.json').write_text(json.dumps({'version':1,'files':record},indent=2),encoding='utf-8')
    return record

def seal_bridge_dependencies(root):
    bridge=Path(root)/'scripts/whatsapp-bridge';modules=bridge/'node_modules'
    if not modules.is_dir() or modules.is_symlink():raise ValueError('locked dependency installation required before seal')
    digest=hashlib.sha256((bridge/'package.json').read_bytes()).hexdigest()[:16]
    (modules/'.hermes-pkg-hash').write_text(digest,encoding='utf-8')
    return digest
