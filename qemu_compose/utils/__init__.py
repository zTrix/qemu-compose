from typing import Optional, List
import os

def is_pid_running(pid: Optional[int]) -> Optional[bool]:
    if pid is None:
        return None
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False

class StreamWrapper:
    def __init__(self, obj):
        self.obj = obj

    def __getattr__(self, name):
        return getattr(self.obj, name)

    def write(self, s):
        if isinstance(s, str):
            s = s.encode()
        self.obj.write(s)


def list_subdirs(root: str) -> List[str]:
    try:
        return [d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))]
    except FileNotFoundError:
        return []

def safe_read(path: str) -> Optional[str]:
    try:
        with open(path, "r") as f:
            return f.read().strip() or None
    except Exception:
        return None   
