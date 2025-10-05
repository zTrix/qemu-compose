from __future__ import annotations

import json
import os
import shlex
import subprocess
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .local_store import LocalStore
from .utils.names_gen import generate_unique_name


@dataclass(frozen=True)
class ImageManifest:
    image_id: str
    root: str
    manifest: Dict

    @property
    def manifest_path(self) -> str:
        return os.path.join(self.root, self.image_id, "manifest.json")

    @property
    def image_dir(self) -> str:
        return os.path.join(self.root, self.image_id)


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


def _parse_manifest(image_root: str, image_id: str) -> ImageManifest:
    manifest = ImageManifest(image_id=image_id, root=image_root, manifest=_read_json(os.path.join(image_root, image_id, "manifest.json")))
    return manifest


def _instance_paths(store: LocalStore, vmid: str) -> Tuple[str, str]:
    inst_dir = store.instance_dir(vmid)
    disk_path = os.path.join(inst_dir, "instance.qcow2")
    return inst_dir, disk_path


def _find_base_disk(manifest: Dict) -> Optional[str]:
    # Expect manifest["disks"] like: [["disk.qcow2", "qcow2", "if=virtio"], ...]
    disks = manifest.get("disks") or []
    for item in disks:
        if isinstance(item, list) and item:
            # Use the first disk as base
            return item[0]
    return None


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


def _format_qemu_cmd(manifest: ImageManifest, instance_dir: str, overlay_disk: str, name: str) -> List[str]:
    # Minimal runnable qemu command based on manifest hints. We only assemble a base command
    # and echo it for the user to run.
    raw_qemu_args = manifest.manifest.get("qemu_args") or []
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
        "-drive", f"if=virtio,format=qcow2,file={overlay_disk}",
    ]

    # Allow manifest-provided extra args after our safe defaults.
    return base + qemu_args


def command_run(*, image_id: str, name: Optional[str]) -> int:
    store = LocalStore()

    # Resolve name and vmid
    name = _choose_name(name, store.instance_root)
    vmid = store.new_random_vmid()
    inst_dir, overlay_disk = _instance_paths(store, vmid)
    _ensure_dir(inst_dir)

    # Parse manifest
    manifest_obj = _parse_manifest(store.image_root, image_id)
    manifest = manifest_obj.manifest

    # Compute paths
    base_disk_name = _find_base_disk(manifest)
    if not base_disk_name:
        print("Error: no 'disks' entry found in manifest.json", flush=True)
        return 1

    base_disk_path = os.path.join(manifest_obj.image_dir, base_disk_name)

    # Create overlay
    rc = _create_overlay(base_disk_path, overlay_disk)
    if rc != 0:
        return rc

    # Persist minimal instance metadata
    try:
        with open(os.path.join(inst_dir, "name"), "w", encoding="utf-8") as f:
            f.write(name)
        with open(os.path.join(inst_dir, "instance-id"), "w", encoding="utf-8") as f:
            f.write(vmid)
    except Exception:
        pass

    # Build qemu command and print
    cmd = _format_qemu_cmd(manifest_obj, inst_dir, overlay_disk, name)
    print(" ".join(shlex.quote(x) for x in cmd))
    return 0
