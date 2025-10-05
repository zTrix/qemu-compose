from __future__ import annotations
from typing import Iterable, List, Optional, Tuple, Any
import os

from qemu_compose.local_store import LocalStore
from qemu_compose.utils.human_readable import human_readable_size, humanize_age
from qemu_compose.image import ImageManifest, RepoTag

def _list_subdirs(root: str) -> List[str]:
    try:
        return [d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))]
    except FileNotFoundError:
        return []



def _short_image_id(digest: Optional[str]) -> str:
    if not digest:
        return "<none>"
    if digest.startswith("sha256:"):
        return digest.split(":", 1)[1][:12]
    # Fallback: first 12 chars
    return digest[:12]

def _file_size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _size_from_manifest(image_dir: str, manifest: ImageManifest) -> int:
    disks = manifest.disks
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

    manifest = ImageManifest.load_file(dir_path)

    created_human = humanize_age(manifest.created_dt)
    image_id_short = _short_image_id(manifest.digest)

    size_bytes = _size_from_manifest(dir_path, manifest)
    size_human = human_readable_size(size_bytes)

    def to_row(repo_tag: RepoTag) -> Tuple[str, str, str, str, str]:
        return (repo_tag.repo or "<none>", repo_tag.tag or "<none>", image_id_short, created_human, size_human)

    return [to_row(t) for t in manifest.repo_tags]


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
