from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple

from qemu_compose.local_store import LocalStore
from qemu_compose.utils import safe_read

@dataclass(frozen=True)
class InstanceMeta:
    instance_id: str
    name: Optional[str]
    image: Optional[str]
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
    image = safe_read(os.path.join(base, "image"))
    cid = _to_int(safe_read(os.path.join(base, "cid")))
    pid = _to_int(safe_read(os.path.join(base, "qemu.pid")))
    return InstanceMeta(instance_id=instance_id, name=name, image=image, cid=cid, pid=pid)


def _collect_instances(store: LocalStore) -> List[InstanceMeta]:
    return [_read_instance_meta(store, iid) for iid in _list_instance_ids(store)]


def _filter_instances(instances: Iterable[InstanceMeta], show_all: bool) -> List[InstanceMeta]:
    return [m for m in instances if show_all or _is_pid_running(m.pid)]


def _truncate_instance_id(iid: str, length: int = 12) -> str:
    return iid[:length]


def _column_specs(name_w: int, image_w: int) -> Tuple[int, int, int, int, int]:
    # Fixed widths for deterministic alignment; name and image are dynamic
    return (12, name_w, image_w, 6, 8)


def _format_header(name_w: int, image_w: int) -> str:
    id_w, name_w, image_w, cid_w, pid_w = _column_specs(name_w, image_w)
    return (
        f"{'INSTANCE_ID':{id_w}}  "
        f"{'NAME':{name_w}}  "
        f"{'IMAGE':{image_w}}  "
        f"{'CID':{cid_w}}  "
        f"{'QEMU PID':{pid_w}}  STATUS"
    )


def _format_row(meta: InstanceMeta, name_w: int, image_w: int) -> str:
    status = "running" if _is_pid_running(meta.pid) else "exited"
    name = meta.name or "-"
    image = meta.image or "-"
    cid = "-" if meta.cid is None else str(meta.cid)
    pid = "-" if meta.pid is None else str(meta.pid)
    id_w, name_w, image_w, cid_w, pid_w = _column_specs(name_w, image_w)
    iid = _truncate_instance_id(meta.instance_id, id_w)
    # Left-align strings; right-align numeric-looking fields for clarity
    return (
        f"{iid:<{id_w}}  "
        f"{name:<{name_w}}  "
        f"{image:<{image_w}}  "
        f"{cid:>{cid_w}}  "
        f"{pid:>{pid_w}}  "
        f"{status}"
    )


def _compute_name_width(instances: Iterable[InstanceMeta]) -> int:
    # Ensure at least the header width; adapt to longest name
    names = [m.name or "-" for m in instances]
    longest = max((len(n) for n in names), default=0)
    return max(len("NAME"), longest)


def _compute_image_width(instances: Iterable[InstanceMeta]) -> int:
    images = [m.image or "-" for m in instances]
    longest = max((len(i) for i in images), default=0)
    return max(len("IMAGE"), longest)


def _print_table(instances: Iterable[InstanceMeta]) -> None:
    name_w = _compute_name_width(instances)
    image_w = _compute_image_width(instances)
    header = _format_header(name_w, image_w)
    rows = [
        _format_row(m, name_w, image_w)
        for m in instances
    ]
    lines = [header, "-" * len(header), *rows]
    print("\n".join(lines))


def command_ps(show_all: bool) -> int:
    store = LocalStore()
    instances = _collect_instances(store)
    filtered = _filter_instances(instances, show_all)
    _print_table(filtered)
    return 0
