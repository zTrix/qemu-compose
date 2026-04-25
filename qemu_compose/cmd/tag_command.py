from __future__ import annotations
import argparse
import json
import os
import sys
from typing import List, Optional, Tuple

from qemu_compose.local_store import LocalStore
from qemu_compose.image import list_image, load_image_by_name, resolve_image, resolve_image_by_prefix
from qemu_compose.image.manifest import ImageManifest, RepoTag


def find_image_by_id_or_name(image_root: str, token: str) -> Tuple[Optional[str], List[str]]:
    """
    Resolve an image identifier (ID prefix, name:tag, or name) to a unique image ID.
    Returns (matched_id, all_candidate_ids).
    """
    # First try exact name:tag match via load_image_by_name
    if (found := load_image_by_name(image_root, token)):
        return found.id, [found.id]

    # Try as ID prefix
    matched_id, candidates = resolve_image_by_prefix(image_root, token)
    if matched_id:
        return matched_id, candidates

    return None, []


def update_manifest_repo_tags(manifest_path: str, new_repo_tags: List[RepoTag]) -> None:
    """
    Load manifest.json, replace repo_tags with new_repo_tags, and write back.
    """
    with open(manifest_path, 'r') as f:
        obj = json.load(f)

    obj['repo_tags'] = [f"{rt.repo}:{rt.tag}" for rt in new_repo_tags]

    with open(manifest_path, 'w') as f:
        json.dump(obj, f, indent=2)
        f.write('\n')


def command_tag(source_image: str, target_image: str, force: bool = False) -> int:
    """
    Create a tag TARGET_IMAGE that refers to SOURCE_IMAGE.
    
    If the target tag already exists:
    - Default behavior is to replace it (force=True behavior)
    """
    store = LocalStore()
    image_root = store.image_root

    # Resolve source image to its actual ID
    source_id, source_candidates = find_image_by_id_or_name(image_root, source_image)
    if source_id is None:
        if not source_candidates:
            print(f"Error: source image not found: '{source_image}'", file=sys.stderr)
        else:
            preview = ", ".join(sorted(source_candidates)[:8])
            more = "" if len(source_candidates) <= 8 else f" ... and {len(source_candidates)-8} more"
            print(f"Error: source image '{source_image}' is ambiguous; matches: {preview}{more}", file=sys.stderr)
        return 1

    # Load source manifest
    source_manifest_path = os.path.join(image_root, source_id, "manifest.json")
    source_manifest = ImageManifest.load_file(os.path.join(image_root, source_id))

    # Parse target image name:tag
    target_rt = RepoTag.from_str(target_image)

    # Check if target tag already exists on a different image
    existing_target_id = None
    for image_id in os.listdir(image_root):
        image_dir = os.path.join(image_root, image_id)
        if not os.path.isdir(image_dir):
            continue
        manifest = ImageManifest.load_file(image_dir)
        if manifest.has_repo_tag(target_image) and image_id != source_id:
            existing_target_id = image_id
            break

    if existing_target_id is not None:
        # Tag exists on different image - replace it by removing from old image
        existing_manifest_path = os.path.join(image_root, existing_target_id, "manifest.json")
        existing_manifest = ImageManifest.load_file(os.path.join(image_root, existing_target_id))
        
        # Remove the target tag from the existing image
        new_existing_tags = [rt for rt in existing_manifest.repo_tags if not rt.match_name(target_image)]
        update_manifest_repo_tags(existing_manifest_path, new_existing_tags)

    # Add the new tag to the source image
    if not any(rt.match_name(target_image) for rt in source_manifest.repo_tags):
        new_source_tags = list(source_manifest.repo_tags) + [target_rt]
        update_manifest_repo_tags(source_manifest_path, new_source_tags)
    
    # Print the operation result
    source_id_short = source_manifest.id.split(":")[1][:12] if ":" in source_manifest.id else source_manifest.id[:12]
    print(f"Image: {source_id_short}")
    print(f"Tagged: {target_rt.repo}:{target_rt.tag}")
    
    return 0
