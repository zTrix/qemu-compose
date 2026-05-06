from __future__ import annotations

import os
import shutil
import sys
from typing import List, Optional, Tuple

from qemu_compose.image import load_image_by_name, resolve_image_by_prefix
from qemu_compose.image.manifest import ImageManifest, RepoTag
from qemu_compose.local_store import LocalStore
from qemu_compose.cmd.tag_command import update_manifest_repo_tags


def find_image_by_id_or_name(image_root: str, token: str) -> Tuple[Optional[str], List[str]]:
    if found := load_image_by_name(image_root, token):
        return found.id, [found.id]

    matched_id, candidates = resolve_image_by_prefix(image_root, token)
    if matched_id:
        return matched_id, candidates

    return None, candidates


def remove_image_dir(image_root: str, image_id: str) -> None:
    shutil.rmtree(os.path.join(image_root, image_id))


def remove_repo_tag(image_root: str, image_id: str, target: str, manifest: ImageManifest) -> None:
    manifest_path = os.path.join(image_root, image_id, "manifest.json")
    new_repo_tags = [repo_tag for repo_tag in manifest.repo_tags if not repo_tag.match_name(target)]
    update_manifest_repo_tags(manifest_path, new_repo_tags)


def command_rmi(image: str) -> int:
    store = LocalStore()
    image_root = store.image_root

    matched_id, candidates = find_image_by_id_or_name(image_root, image)
    if matched_id is None:
        if candidates:
            preview = ", ".join(sorted(set(candidates))[:8])
            more = "" if len(set(candidates)) <= 8 else f" ... and {len(set(candidates)) - 8} more"
            print(f"Error: image identifier '{image}' is ambiguous; matches: {preview}{more}", file=sys.stderr)
        else:
            print(f"Error: image not found: {image}", file=sys.stderr)
        return 1

    manifest = ImageManifest.load_file(os.path.join(image_root, matched_id))
    removing_by_tag = any(repo_tag.match_name(image) for repo_tag in manifest.repo_tags)

    if removing_by_tag and len(manifest.repo_tags) > 1:
        remove_repo_tag(image_root, matched_id, image, manifest)
        print(f"Untagged: {RepoTag.from_str(image).repo}:{RepoTag.from_str(image).tag}")
        return 0

    remove_image_dir(image_root, matched_id)
    print(f"Deleted: {matched_id}")
    return 0
