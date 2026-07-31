from __future__ import annotations

import os
import sys

from qemu_compose.cmd.down_command import (
    _is_pid_running,
    _to_int,
    instance_label,
    resolve_instance,
    stop_pid,
)
from qemu_compose.local_store import LocalStore
from qemu_compose.utils import safe_read


def command_stop(*, identifier: str) -> int:
    store = LocalStore()
    vmid, _, exit_code = resolve_instance(store=store, identifier=identifier)
    if exit_code != 0 or vmid is None:
        return exit_code

    instance_dir = store.instance_dir(vmid)
    if not os.path.exists(instance_dir):
        print(f"Error: instance directory not found: {instance_dir}", file=sys.stderr)
        return 1

    pid = _to_int(safe_read(os.path.join(instance_dir, "qemu.pid")))
    supervisor_pid = _to_int(safe_read(os.path.join(instance_dir, "supervisor.pid")))
    name = safe_read(os.path.join(instance_dir, "name"))

    supervisor_running = _is_pid_running(supervisor_pid)
    qemu_running = _is_pid_running(pid)
    target_pid = supervisor_pid if supervisor_running else pid
    if not target_pid or not _is_pid_running(target_pid):
        print(f"Instance {instance_label(vmid, name)} is not running", flush=True)
        return 0

    shown_pid = pid if qemu_running else supervisor_pid
    print(f"Stopping instance {instance_label(vmid, name)} (pid: {shown_pid})...", flush=True)
    if not stop_pid(target_pid):
        print(f"Error: failed to stop instance {instance_label(vmid, name)}", file=sys.stderr)
        return 1

    print(f"Stopped instance {instance_label(vmid, name)}", flush=True)
    return 0
