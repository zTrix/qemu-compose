from __future__ import annotations
from typing import Optional, List, Dict, Tuple
import os
import sys
import signal
import shutil
import time
import logging

from qemu_compose.local_store import LocalStore
from qemu_compose.utils import safe_read

logger = logging.getLogger("qemu-compose.cmd.down_command")

SHUTDOWN_TIMEOUT = 15.0


def _list_vmids(root: str) -> List[str]:
    try:
        return [d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))]
    except FileNotFoundError:
        return []


def _build_name_index(root: str) -> Dict[str, str]:
    def name_of(vmid: str) -> Optional[str]:
        return safe_read(os.path.join(root, vmid, "name"))

    pairs: List[Tuple[str, Optional[str]]] = [
        (vmid, name_of(vmid)) for vmid in _list_vmids(root)
    ]
    return {name: vmid for (vmid, name) in pairs if name}


def _resolve_identifier(token: str, ids: List[str], name_index: Dict[str, str]) -> Tuple[Optional[str], List[str]]:
    if token in ids:
        return token, [token]
    if token in name_index:
        return name_index[token], [name_index[token]]

    matches = [i for i in ids if i.startswith(token)]
    if len(matches) == 1:
        return matches[0], matches
    return None, matches


def _to_int(s: Optional[str]) -> Optional[int]:
    try:
        return int(s) if s is not None else None
    except Exception:
        return None


def _is_pid_running(pid: Optional[int]) -> bool:
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def command_down(*, identifier: Optional[str] = None, force: bool = False, config_path: Optional[str] = None) -> int:
    store = LocalStore()
    instance_root = store.instance_root

    if not os.path.exists(instance_root):
        print("Error: no instances found", file=sys.stderr)
        return 1

    ids = _list_vmids(instance_root)
    name_index = _build_name_index(instance_root)

    vmid = None
    candidates = []

    if identifier:
        vmid, candidates = _resolve_identifier(identifier, ids, name_index)
    elif config_path:
        from qemu_compose.instance.qemu_runner import QemuConfig
        config = QemuConfig.load_yaml(config_path)
        if config.name:
            vmid, candidates = _resolve_identifier(config.name, ids, name_index)
        else:
            print("Error: config file does not specify a name", file=sys.stderr)
            return 1
    else:
        print("Error: identifier is required", file=sys.stderr)
        return 1

    if vmid is None and not candidates:
        print(f"Error: instance not found: {identifier}", file=sys.stderr)
        return 1

    if vmid is None and candidates:
        preview = ", ".join(sorted(candidates)[:8])
        more = "" if len(candidates) <= 8 else f" ... and {len(candidates)-8} more"
        print(f"Error: identifier '{identifier}' is ambiguous; matches: {preview}{more}", file=sys.stderr)
        return 1

    instance_dir = store.instance_dir(vmid)

    if not os.path.exists(instance_dir):
        print(f"Error: instance directory not found: {instance_dir}", file=sys.stderr)
        return 1

    pid = _to_int(safe_read(os.path.join(instance_dir, "qemu.pid")))
    name = safe_read(os.path.join(instance_dir, "name"))

    if pid and _is_pid_running(pid):
        instance_label = f"{vmid}" if not name else f"{name} ({vmid})"
        print(f"Stopping instance {instance_label} (pid: {pid})...", flush=True)
        try:
            os.kill(pid, signal.SIGTERM)
            deadline = time.time() + SHUTDOWN_TIMEOUT
            while time.time() < deadline:
                if not _is_pid_running(pid):
                    break
                time.sleep(0.1)
            else:
                logger.warning("Process did not terminate gracefully, sending SIGKILL")
                os.kill(pid, signal.SIGKILL)
                time.sleep(0.5)
        except OSError as e:
            logger.warning("Failed to send signal to process: %s", e)

    try:
        shutil.rmtree(instance_dir)
        instance_label = f"{vmid}" if not name else f"{name} ({vmid})"
        print(f"Removed instance {instance_label}", flush=True)
    except PermissionError as e:
        print(f"Error: permission denied removing instance directory: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error removing instance directory: {e}", file=sys.stderr)
        return 1

    return 0
