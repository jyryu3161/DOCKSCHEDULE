import os
import signal
import psutil


def matches(pid, created):
    if not pid or created is None:
        return False
    try:
        p = psutil.Process(pid)
        return abs(p.create_time()-created) < 0.01 and p.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def stop_tree(pid, created=None):
    """Kill descendants first; never signal a reused PID."""
    if created is not None and not matches(pid, created):
        return
    try:
        p = psutil.Process(pid)
        descendants = p.children(recursive=True)
        for child in reversed(descendants):
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
        p.kill()
        psutil.wait_procs([*descendants, p], timeout=5)
    except psutil.NoSuchProcess:
        pass
