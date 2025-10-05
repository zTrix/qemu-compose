from __future__ import annotations

import json
import os
import shlex
import subprocess
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from qemu_compose.local_store import LocalStore
from qemu_compose.utils.names_gen import generate_unique_name
from qemu_compose.instance import new_random_vmid
from qemu_compose.image import ImageManifest, DiskSpec

def _read_json(path: str) -> Dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path


def _existing_names(instance_root: str) -> Dict[str, str]:
    def _name_of(d: str) -> Optional[str]:
        p = os.path.join(instance_root, d, "name")
        try:
            with open(p, "r", encoding="utf-8") as f:
                n = f.read().strip()
                return n or None
        except Exception:
            return None

    try:
        entries = [d for d in os.listdir(instance_root) if os.path.isdir(os.path.join(instance_root, d))]
    except FileNotFoundError:
        entries = []

    pairs = [(n, d) for d in entries for n in [_name_of(d)] if n]
    return {n: d for (n, d) in pairs}


def _choose_name(provided: Optional[str], instance_root: str) -> str:
    return provided or generate_unique_name(_existing_names(instance_root))


def _list_image_ids(image_root: str) -> List[str]:
    try:
        return [d for d in os.listdir(image_root) if os.path.isdir(os.path.join(image_root, d))]
    except FileNotFoundError:
        return []


def _resolve_image_by_prefix(image_root: str, token: str) -> Tuple[Optional[str], List[str]]:
    ids = _list_image_ids(image_root)
    if token in ids:
        return token, [token]
    matches = [i for i in ids if i.startswith(token)]
    if len(matches) == 1:
        return matches[0], matches
    return None, matches


def _read_manifest_repo_tags(image_root: str, image_id: str) -> List[str]:
    try:
        manifest = _read_json(os.path.join(image_root, image_id, "manifest.json"))
        tags = manifest.get("repo_tags") or []
        return [str(t) for t in tags if isinstance(t, str)]
    except Exception:
        return []

def _resolve_image_by_repo_tag(image_root: str, token: str) -> Tuple[Optional[str], List[str]]:
    ids = _list_image_ids(image_root)
    matches: List[str] = []
    for i in ids:
        tags = _read_manifest_repo_tags(image_root, i)
        if token in tags:
            matches.append(i)
    if len(matches) == 1:
        return matches[0], matches
    return None, matches


def _instance_paths(store: LocalStore, vmid: str) -> Tuple[str, str]:
    inst_dir = store.instance_dir(vmid)
    return inst_dir, os.path.join(inst_dir, "instance.qcow2")

def _create_overlay(base_path: str, overlay_path: str) -> int:
    cmd = [
        "qemu-img", "create",
        "-b", base_path,
        "-f", "qcow2",
        "-F", "qcow2",
        overlay_path,
    ]
    try:
        res = subprocess.run(cmd, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            print(res.stderr)
        return res.returncode
    except FileNotFoundError:
        print("Error: 'qemu-img' binary not found in PATH", flush=True)
        return 127

def _drive_param_for(overlay_path: str, spec: DiskSpec) -> str:
    # Build a '-drive' parameter string combining manifest opts with required pieces.
    opts = list(spec.opts)
    if not any(o.startswith("if=") for o in opts):
        opts.insert(0, "if=virtio")
    # Always use qcow2 overlay per requirement
    opts.append("format=qcow2")
    opts.append(f"file={overlay_path}")
    return ",".join(opts)


def _format_qemu_cmd(manifest: ImageManifest, instance_dir: str, overlays: List[Tuple[str, DiskSpec]], name: str) -> List[str]:
    # Minimal runnable qemu command based on manifest hints. We only assemble a base command
    # and echo it for the user to run.
    raw_qemu_args = manifest.qemu_args or []
    # Interpolate simple placeholders like {INSTANCE_DIR}
    env = {"INSTANCE_DIR": instance_dir}
    qemu_args = [str(a).format(**env) for a in raw_qemu_args]

    # Provide common defaults if manifest hasn't provided them.
    base: List[str] = [
        "qemu-system-x86_64",
        "-name", name,
        "-m", "1024",
        "-smp", "%d" % (os.cpu_count() or 1),
        "-machine", "type=q35,hpet=off",
        "-accel", "kvm",
        "-nographic",
    ]

    # Add a -drive entry for each overlay
    for overlay_path, spec in overlays:
        base.extend(["-drive", _drive_param_for(overlay_path, spec)])

    # Allow manifest-provided extra args after our safe defaults.
    return base + qemu_args


def command_run(*, image_id: str, name: Optional[str]) -> int:
    store = LocalStore()

    # Resolve name
    name = _choose_name(name, store.instance_root)

    # Resolve image id: exact, unique prefix, or repo_tag
    resolved_id, prefix_matches = _resolve_image_by_prefix(store.image_root, image_id)
    if resolved_id is None:
        resolved_id, tag_matches = _resolve_image_by_repo_tag(store.image_root, image_id)
        if resolved_id is None:
            if prefix_matches or tag_matches:
                preview = ", ".join(sorted(set(prefix_matches + tag_matches))[:8])
                more = "" if len(set(prefix_matches + tag_matches)) <= 8 else f" ... and {len(set(prefix_matches + tag_matches))-8} more"
                print(f"Error: image identifier '{image_id}' is ambiguous; matches: {preview}{more}", flush=True)
            else:
                print(f"Error: image not found: {image_id}", flush=True)
            return 1

    # Parse manifest of the resolved image id
    image_dir = os.path.join(store.image_root, resolved_id)
    manifest = ImageManifest.load_file(image_dir)

    vmid = new_random_vmid(store.instance_root)
    inst_dir, _ = _instance_paths(store, vmid)
    _ensure_dir(inst_dir)

    overlays: List[Tuple[str, DiskSpec]] = []

    for spec in manifest.disks:
        base_disk_path = os.path.join(image_dir, spec.filename)
        overlay_path = os.path.join(inst_dir, spec.filename)
        rc = _create_overlay(base_disk_path, overlay_path)
        if rc != 0:
            return rc
        overlays.append((overlay_path, spec))

    # Persist minimal instance metadata
    try:
        with open(os.path.join(inst_dir, "name"), "w", encoding="utf-8") as f:
            f.write(name)
        with open(os.path.join(inst_dir, "instance-id"), "w", encoding="utf-8") as f:
            f.write(vmid)
    except Exception:
        pass

    # Build qemu command and print
    cmd = _format_qemu_cmd(manifest, inst_dir, overlays, name)
    print(" ".join(shlex.quote(x) for x in cmd))
    return 0
