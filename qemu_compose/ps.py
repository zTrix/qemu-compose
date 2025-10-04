from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable, List, Optional


@dataclass(frozen=True)
class InstanceMeta:
    instance_id: str
    name: Optional[str]
    cid: Optional[int]
    pid: Optional[int]


@dataclass(frozen=True)
class Store:
    data_dir: str

    @property
    def instance_root(self) -> str:
        path = os.path.join(self.data_dir, "instance")
        # Do not create directories here to avoid side effects
        return path


def _safe_read(path: str) -> Optional[str]:
    try:
        with open(path, "r") as f:
            return f.read().strip() or None
    except Exception:
        return None


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


def _list_instance_ids(store: Store) -> List[str]:
    try:
        return sorted(
            [d for d in os.listdir(store.instance_root) if os.path.isdir(os.path.join(store.instance_root, d))]
        )
    except FileNotFoundError:
        return []


def _read_instance_meta(store: Store, instance_id: str) -> InstanceMeta:
    # Avoid side effects: do not create directories while reading
    base = os.path.join(store.instance_root, instance_id)
    name = _safe_read(os.path.join(base, "name"))
    cid = _to_int(_safe_read(os.path.join(base, "cid")))
    pid = _to_int(_safe_read(os.path.join(base, "qemu.pid")))
    return InstanceMeta(instance_id=instance_id, name=name, cid=cid, pid=pid)


def _collect_instances(store: Store) -> List[InstanceMeta]:
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
    header = f"{'INSTANCE_ID':12}  {'NAME':20}  {'CID':6}  {'PID':8}  STATUS"
    print(header)
    print("-" * len(header))
    for m in instances:
        print(_format_row(m))


def _default_store() -> Store:
    xdg = os.getenv("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
    return Store(data_dir=os.path.join(xdg, "qemu-compose"))


def command_ps(show_all: bool) -> int:
    store = _default_store()
    instances = _collect_instances(store)
    filtered = _filter_instances(instances, show_all)
    _print_table(filtered)
    return 0
