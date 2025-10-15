from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable, List, Optional

from qemu_compose.local_store import LocalStore
from qemu_compose.utils import safe_read

@dataclass(frozen=True)
class InstanceMeta:
    instance_id: str
    name: Optional[str]
    cid: Optional[int]
    pid: Optional[int]


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


def _list_instance_ids(store: LocalStore) -> List[str]:
    try:
        return sorted(
            [d for d in os.listdir(store.instance_root) if os.path.isdir(os.path.join(store.instance_root, d))]
        )
    except FileNotFoundError:
        return []


def _read_instance_meta(store: LocalStore, instance_id: str) -> InstanceMeta:
    # Avoid side effects: do not create directories while reading
    base = os.path.join(store.instance_root, instance_id)
    name = safe_read(os.path.join(base, "name"))
    cid = _to_int(safe_read(os.path.join(base, "cid")))
    pid = _to_int(safe_read(os.path.join(base, "qemu.pid")))
    return InstanceMeta(instance_id=instance_id, name=name, cid=cid, pid=pid)


def _collect_instances(store: LocalStore) -> List[InstanceMeta]:
    return [_read_instance_meta(store, iid) for iid in _list_instance_ids(store)]


def _filter_instances(instances: Iterable[InstanceMeta], show_all: bool) -> List[InstanceMeta]:
    return [m for m in instances if show_all or _is_pid_running(m.pid)]


def _format_row(meta: InstanceMeta) -> str:
    status = "running" if _is_pid_running(meta.pid) else "exited"
    name = meta.name or "-"
    cid = str(meta.cid) if meta.cid is not None else "-"
    pid = str(meta.pid) if meta.pid is not None else "-"
    return f"{meta.instance_id:12}  {name:20}  {cid:6}  {pid:8}  {status}"


def _print_table(instances: Iterable[InstanceMeta]) -> None:
    header = f"{'INSTANCE_ID':12}  {'NAME':20}  {'CID':6}  {'QEMU PID':8}  STATUS"
    print(header)
    print("-" * len(header))
    for m in instances:
        print(_format_row(m))


def command_ps(show_all: bool) -> int:
    store = LocalStore()
    instances = _collect_instances(store)
    filtered = _filter_instances(instances, show_all)
    _print_table(filtered)
    return 0
