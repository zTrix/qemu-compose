from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Iterable, List, Optional, Tuple, Dict, Any

from qemu_compose.local_store import LocalStore
from qemu_compose.utils.human_readable import human_readable_size


def _list_subdirs(root: str) -> List[str]:
    try:
        return [d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))]
    except FileNotFoundError:
        return []


def _read_manifest(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return None


def _split_repository_tag(tag: str) -> Tuple[str, str]:
    if ":" in tag:
        repo, ver = tag.split(":", 1)
        return repo or "<none>", ver or "<none>"
    return tag or "<none>", "latest"


def _short_image_id(digest: Optional[str]) -> str:
    if not digest:
        return "<none>"
    if digest.startswith("sha256:"):
        return digest.split(":", 1)[1][:12]
    # Fallback: first 12 chars
    return digest[:12]


def _parse_created(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    # Accept RFC3339 with trailing 'Z'
    try:
        if s.endswith("Z"):
            # fromisoformat expects +00:00 instead of Z
            return datetime.fromisoformat(s[:-1] + "+00:00")
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _humanize_age(created: Optional[datetime], now: Optional[datetime] = None) -> str:
    if created is None:
        return "<unknown>"
    base = now or datetime.now(timezone.utc)
    # Ensure timezone-aware comparison
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    delta = base - created

    seconds = int(delta.total_seconds())
    if seconds < 60:
        return f"{seconds}s ago"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    if days < 30:
        return f"{days}d ago"
    months = days // 30
    if months < 12:
        return f"{months}mo ago"
    years = months // 12
    return f"{years}y ago"


def _file_size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _size_from_manifest(image_dir: str, manifest: Dict[str, Any]) -> int:
    disks = manifest.get("disks")
    if isinstance(disks, list):
        # Each entry may be [filename, ...] or dict with name
        def file_of(entry: Any) -> Optional[str]:
            if isinstance(entry, list) and entry:
                return entry[0]
            if isinstance(entry, dict):
                name = entry.get("file") or entry.get("name")
                if isinstance(name, str):
                    return name
            return None

        files = [file_of(d) for d in disks]
        return sum(_file_size(os.path.join(image_dir, f)) for f in files if isinstance(f, str))
    return 0

def _rows_for_image(image_root: str, image_id: str) -> List[Tuple[str, str, str, str, str]]:
    dir_path = os.path.join(image_root, image_id)
    manifest = _read_manifest(os.path.join(dir_path, "manifest.json"))
    if not manifest:
        return []

    created_dt = _parse_created(manifest.get("created"))
    created_human = _humanize_age(created_dt)
    image_id_short = _short_image_id(manifest.get("digest"))
    size_bytes = _size_from_manifest(dir_path, manifest)
    size_human = human_readable_size(size_bytes)

    tags: Iterable[str] = manifest.get("repo_tags") or []
    # If no tags present, still emit one row with <none>/<none>
    tag_list = list(tags) if isinstance(tags, list) else []
    tag_list = tag_list if tag_list else ["<none>:<none>"]

    def to_row(tag: str) -> Tuple[str, str, str, str, str]:
        repo, ver = _split_repository_tag(tag)
        return (repo, ver, image_id_short, created_human, size_human)

    return [to_row(t) for t in tag_list]


def _collect_rows(image_root: str) -> List[Tuple[str, str, str, str, str]]:
    return [row for image_id in _list_subdirs(image_root) for row in _rows_for_image(image_root, image_id)]


def _print_table(rows: List[Tuple[str, str, str, str, str]]) -> None:
    headers = ["REPOSITORY", "TAG", "IMAGE ID", "CREATED", "SIZE"]

    def width(column: int) -> int:
        vals = [headers[column]] + [str(r[column]) for r in rows]
        return max(len(v) for v in vals)

    widths = [width(i) for i in range(len(headers))]

    def fmt_row(items: Iterable[str]) -> str:
        parts = [str(v).ljust(widths[i]) for i, v in enumerate(items)]
        return "  ".join(parts)

    print(fmt_row(headers))
    for r in rows:
        print(fmt_row(r))


def command_images() -> int:
    store = LocalStore()
    image_root = store.image_root
    rows = _collect_rows(image_root)
    _print_table(rows)
    return 0

