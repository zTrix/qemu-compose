from __future__ import annotations

import json
import os
import sys
from typing import List

from qemu_compose.image.manifest import ImageManifest
from qemu_compose.image.oci_import import OciImportError, import_oci_image, normalize_repo_tag
from qemu_compose.local_store import LocalStore


def _remove_repo_tag_from_other_images(image_root: str, keep_image_id: str, repo_tag: str) -> None:
    for image_id in os.listdir(image_root):
        if image_id == keep_image_id:
            continue
        image_dir = os.path.join(image_root, image_id)
        manifest_path = os.path.join(image_dir, "manifest.json")
        if not os.path.isfile(manifest_path):
            continue

        manifest = ImageManifest.load_file(image_dir)
        if not manifest.has_repo_tag(repo_tag):
            continue

        new_tags: List[str] = []
        for item in manifest.repo_tags:
            tag_value = f"{item.repo}:{item.tag}"
            if not item.match_name(repo_tag):
                new_tags.append(tag_value)

        with open(manifest_path) as f:
            obj = json.load(f)
        obj["repo_tags"] = new_tags
        with open(manifest_path, "w") as f:
            json.dump(obj, f, indent=2)
            f.write("\n")


def command_pull(
    *,
    image: str,
    kernel: str,
    initrd: str,
    platform: str = "linux/amd64",
    disk_size: str = "2G",
    force: bool = False,
    keep_workdir: bool = False,
    boot_mode: str = "container",
) -> int:
    store = LocalStore()
    repo_tag = normalize_repo_tag(image)

    try:
        image_id = import_oci_image(
            image_root=store.image_root,
            image=image,
            kernel=kernel,
            initrd=initrd,
            platform=platform,
            disk_size=disk_size,
            force=force,
            keep_workdir=keep_workdir,
            boot_mode=boot_mode,
        )
    except OciImportError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    _remove_repo_tag_from_other_images(store.image_root, image_id, repo_tag)

    print(f"Pulled: {repo_tag}")
    print(f"Image: {image_id}")
    return 0
