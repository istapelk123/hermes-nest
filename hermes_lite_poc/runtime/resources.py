"""Owned-group RSS fuse, not virtual-address limits. No external packages."""
import os
from pathlib import Path
import sys


def owned_rss_bytes(group_pid, proc_root=Path('/proc'), page_size=None):
    """Sum resident pages for our isolated pgrp; shared pages count conservatively.

    /proc is required on Linux. Disappearing children are normal. This is a
    sampling fuse, not a cgroup: a burst between samples can exceed the budget.
    """
    if page_size is None:
        page_size = os.sysconf('SC_PAGE_SIZE')
    pages = 0
    for entry in proc_root.iterdir():
        if not entry.name.isdecimal():
            continue
        try:
            stat = (entry / 'stat').read_text(encoding='ascii').rsplit(')', 1)[1].split()
            if int(stat[2]) != group_pid:
                continue
            resident = int((entry / 'statm').read_text(encoding='ascii').split()[1])
            if resident >= 0:
                pages += resident
        except (FileNotFoundError, ProcessLookupError, PermissionError, ValueError, IndexError):
            continue
    return pages * page_size


def configure_cli_limits(resource_module=None):
    """Call before creating threads; both supervisor and workers inherit limits.

    Intentionally NO RLIMIT_AS (breaks V8 reservation), NO RLIMIT_CPU (not a
    service lifetime limit). Native Windows fixture tests cannot apply RLIMIT.
    """
    if resource_module is None:
        if sys.platform != 'linux':
            return False
        import resource as resource_module
    resource_module.setrlimit(resource_module.RLIMIT_CORE, (0, 0))
    _, hard = resource_module.getrlimit(resource_module.RLIMIT_NOFILE)
    bound = 1024 if hard < 0 else min(1024, hard)
    resource_module.setrlimit(resource_module.RLIMIT_NOFILE, (bound, bound))
    return True
