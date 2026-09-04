from __future__ import annotations

import json
import sys
import types
from pathlib import Path

# Allow tests to run even when pycryptodome is not importable (same shim as
# test_run_command.py). qemu_runner -> qemu_compose.instance needs Crypto.ECC.
try:
    from Crypto.PublicKey import ECC as _ECC  # noqa: F401
except Exception:
    crypto_module = types.ModuleType("Crypto")
    crypto_public_key_module = types.ModuleType("Crypto.PublicKey")
    crypto_public_key_module.ECC = object()
    sys.modules.setdefault("Crypto", crypto_module)
    sys.modules.setdefault("Crypto.PublicKey", crypto_public_key_module)

import qemu_compose.instance.qemu_runner as qemu_runner_module
from qemu_compose.image import load_image_by_id
from qemu_compose.instance.qemu_runner import QemuRunner, QemuConfig
from qemu_compose.local_store import LocalStore


OLD_ID = "62a028ff7613df38926339ca5fab3fa97da198757ba3c41e641f4b5d498d64e3"
NEW_ID = "7764bc3a7613df38926339ca5fab3fa97da198757ba3c41e641f4b5d498d64e3"
TAG = "devbox:archlinux"
VMID = "9713de74ffaf46b2a062e8223e2d4ba2"


def write_manifest(image_root: Path, image_id: str, repo_tags: list[str]) -> None:
    """Create an image store entry (mirrors qemu_compose/image/oci_import.py)."""
    image_dir = image_root / image_id
    image_dir.mkdir(parents=True, exist_ok=True)
    (image_dir / "manifest.json").write_text(
        json.dumps(
            {
                "id": image_id,
                "architecture": "x86_64",
                "os": "linux",
                "created": "2026-05-06T00:00:00Z",
                "repo_tags": repo_tags,
                "disks": [["disk.qcow2", "qcow2", "if=virtio"]],
                "qemu_args": [
                    "-kernel",
                    "{IMAGE_DIR}/boot/vmlinuz",
                    "-initrd",
                    "{IMAGE_DIR}/boot/initramfs.img",
                    "-append",
                    "console=ttyS0 root=/dev/vda1 rw",
                ],
                "digest": f"sha256:{image_id}",
                "comment": None,
            }
        )
    )


def make_runner(tmp_path: Path, *, config_image: str, instance: str | None,
                recorded_image_id: str | None = None) -> QemuRunner:
    store = LocalStore()
    if instance is not None:
        instance_dir = Path(store.instance_dir(instance))
        if recorded_image_id is not None:
            (instance_dir / "image-id").write_text(recorded_image_id)
    config = QemuConfig(
        name=instance or "fresh-vm",
        image=config_image,
        instance=instance,
        binary="/bin/true",  # QemuRunner only stores the binary; never launches it
    )
    return QemuRunner(config, store, str(tmp_path))


def test_existing_instance_keeps_recorded_image_when_tag_moved(tmp_path, monkeypatch):
    """Bug from NETWORK_BUG_REPORT.md: reboot after the base image tag was rebuilt
    must NOT switch an existing instance to the newer image/kernel. The instance
    rootfs (and its overlay backing file) belong to the originally recorded image."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    image_root = tmp_path / "qemu-compose" / "image"
    # Old build: recorded on the instance at creation, tag later removed from it.
    write_manifest(image_root, OLD_ID, ["devbox:archlinux@sha256:abcdef"])
    # New build: tag now points here (e.g. devbox:archlinux rebuilt Sep 3).
    write_manifest(image_root, NEW_ID, [TAG])

    monkeypatch.setattr(qemu_runner_module, "get_available_guest_cid", lambda *a, **k: 2000)

    vm = make_runner(tmp_path, config_image=TAG, instance=VMID, recorded_image_id=OLD_ID)

    assert vm.check_and_lock() == 0
    assert vm.image_manifest is not None
    assert vm.image_manifest.id == OLD_ID, (
        "restart must boot the recorded creation image, not the re-resolved tag build"
    )


def test_new_instance_still_resolves_current_tag(tmp_path, monkeypatch):
    """Instance creation (no recorded image yet) still resolves the repo tag to the
    current build in the store."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    image_root = tmp_path / "qemu-compose" / "image"
    write_manifest(image_root, OLD_ID, [])
    write_manifest(image_root, NEW_ID, [TAG])

    monkeypatch.setattr(qemu_runner_module, "get_available_guest_cid", lambda *a, **k: 2000)

    vm = make_runner(tmp_path, config_image=TAG, instance=None)

    assert vm.check_and_lock() == 0
    assert vm.image_manifest is not None
    assert vm.image_manifest.id == NEW_ID


def test_explicit_image_id_in_config_overrides_recorded(tmp_path, monkeypatch):
    """A user explicitly pinning an image id in the compose file always wins, even for
    an existing instance (e.g. re-pointing to the image that matches the rootfs)."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    image_root = tmp_path / "qemu-compose" / "image"
    write_manifest(image_root, OLD_ID, [])
    write_manifest(image_root, NEW_ID, [TAG])

    monkeypatch.setattr(qemu_runner_module, "get_available_guest_cid", lambda *a, **k: 2000)

    # Recorded = OLD_ID, but the compose file now points at NEW_ID explicitly.
    vm = make_runner(tmp_path, config_image=NEW_ID, instance=VMID, recorded_image_id=OLD_ID)

    assert vm.check_and_lock() == 0
    assert vm.image_manifest is not None
    assert vm.image_manifest.id == NEW_ID


def test_missing_recorded_image_falls_back_to_tag(tmp_path, monkeypatch, capsys):
    """Legacy/no recorded image, or a recorded image removed from the store, falls
    back to normal tag resolution (with a warning) instead of failing hard."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    image_root = tmp_path / "qemu-compose" / "image"
    write_manifest(image_root, NEW_ID, [TAG])

    monkeypatch.setattr(qemu_runner_module, "get_available_guest_cid", lambda *a, **k: 2000)

    # Recorded image was deleted from the store; only the tagged new build remains.
    vm = make_runner(tmp_path, config_image=TAG, instance=VMID, recorded_image_id=OLD_ID)

    assert vm.check_and_lock() == 0
    assert vm.image_manifest is not None
    assert vm.image_manifest.id == NEW_ID
    assert OLD_ID in capsys.readouterr().err


def _runner_with_vmid(tmp_path: Path, *, config_image: str = TAG) -> tuple[QemuRunner, LocalStore]:
    store = LocalStore()
    vm = make_runner(tmp_path, config_image=config_image, instance=VMID)
    vm.vmid = VMID
    return vm, store


def test_image_id_recorded_on_first_boot_and_not_rewritten_on_reboot(tmp_path, monkeypatch):
    """image/image-id must be recorded once (first boot) and must NOT be rewritten by
    an ordinary reboot: that rewrite is what silently moved the record onto a newer
    tag build and caused the kernel/rootfs mismatch in NETWORK_BUG_REPORT.md."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    image_root = tmp_path / "qemu-compose" / "image"
    write_manifest(image_root, OLD_ID, [TAG])
    write_manifest(image_root, NEW_ID, [])
    store = LocalStore()
    inst_dir = Path(store.instance_dir(VMID))
    (inst_dir / "name").write_text(VMID)

    vm, _ = _runner_with_vmid(tmp_path)
    vm.image_manifest = load_image_by_id(store.image_root, OLD_ID)

    # First boot: record the resolved creation image.
    vm._record_instance_metadata("100")
    assert (inst_dir / "image").read_text() == TAG
    assert (inst_dir / "image-id").read_text() == OLD_ID
    id_mtime = (inst_dir / "image-id").stat().st_mtime_ns

    # Reboot: restart is pinned back to the recorded image -> file must not change.
    vm.image_manifest = load_image_by_id(store.image_root, OLD_ID)
    vm._record_instance_metadata("101")
    assert (inst_dir / "image-id").read_text() == OLD_ID
    assert (inst_dir / "image-id").stat().st_mtime_ns == id_mtime
    assert (inst_dir / "image").read_text() == TAG

    # Deliberate explicit-id switch to another build -> record follows reality.
    vm.image_manifest = load_image_by_id(store.image_root, NEW_ID)
    vm._record_instance_metadata("102")
    assert (inst_dir / "image-id").read_text() == NEW_ID
