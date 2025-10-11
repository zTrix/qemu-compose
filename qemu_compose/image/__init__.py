from typing import List, Optional, Tuple
import os

from qemu_compose.utils.human_readable import humanize_age, human_readable_size
from qemu_compose.utils import list_subdirs

from .manifest import ImageManifest, RepoTag, DiskSpec



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
        return sum(_file_size(os.path.join(image_dir, f.filename)) for f in disks if isinstance(f, DiskSpec))
    return 0

def _rows_for_image(image_root: str, image_id: str) -> List[Tuple[str, str, str, str, str]]:
    dir_path = os.path.join(image_root, image_id)

    manifest = ImageManifest.load_file(dir_path)

    created_human = humanize_age(manifest.created)
    image_id_short = _short_image_id(manifest.digest)

    size_bytes = _size_from_manifest(dir_path, manifest)
    size_human = human_readable_size(size_bytes)

    def to_row(repo_tag: RepoTag) -> Tuple[str, str, str, str, str]:
        return (repo_tag.repo or "<none>", repo_tag.tag or "<none>", image_id_short, created_human, size_human)

    return [to_row(t) for t in manifest.repo_tags]


def list_image(image_root: str) -> List[Tuple[str, str, str, str, str]]:
    return [row for image_id in list_subdirs(image_root) for row in _rows_for_image(image_root, image_id)]

def load_image_by_id(image_root: str, image_id: str) -> Optional[ImageManifest]:
    dir_path = os.path.join(image_root, image_id)
    if not os.path.exists(dir_path) or not os.path.isdir(dir_path):
        return None
    return ImageManifest.load_file(dir_path)

def load_image_by_name(image_root: str, name: str) -> Optional[ImageManifest]:
    for image_id in list_subdirs(image_root):
        dir_path = os.path.join(image_root, image_id)
        if not os.path.exists(dir_path) or not os.path.isdir(dir_path):
            continue

        manifest = ImageManifest.load_file(dir_path)

        if manifest.has_repo_tag(name):
            return manifest
    return None

def resolve_image_by_prefix(image_root: str, token: str) -> Tuple[Optional[str], List[str]]:
    ids = list_subdirs(image_root)
    if token in ids:
        return token, [token]

    matches = [i for i in ids if i.startswith(token)]
    if len(matches) == 1:
        return matches[0], matches

    return None, matches

def resolve_image(image_root: str, token: str):
    if (found := load_image_by_name(image_root, token)):
        return found.id, [found.id]
    
    return resolve_image_by_prefix(image_root, token)
