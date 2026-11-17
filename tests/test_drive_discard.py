from __future__ import annotations

import sys
import types

# qemu_runner -> qemu_compose.instance imports Crypto; allow running without it.
try:
    from Crypto.PublicKey import ECC as _ECC  # noqa: F401
except Exception:
    crypto_module = types.ModuleType("Crypto")
    crypto_public_key_module = types.ModuleType("Crypto.PublicKey")
    crypto_public_key_module.ECC = object()
    sys.modules.setdefault("Crypto", crypto_module)
    sys.modules.setdefault("Crypto.PublicKey", crypto_public_key_module)

from qemu_compose.image import DiskSpec
from qemu_compose.instance.qemu_runner import drive_param_for


def parse_drive(param: str) -> dict[str, str]:
    return dict(
        part.split("=", 1)
        for part in param.split(",")
        if "=" in part
    )


def test_drive_defaults_to_discard_unmap():
    spec = DiskSpec(filename="disk.qcow2", format="qcow2", opts="if=virtio")

    opts = parse_drive(drive_param_for("/tmp/disk.qcow2", spec))

    assert opts["discard"] == "unmap"


def test_drive_defaults_to_discard_unmap_when_opts_missing():
    spec = DiskSpec(filename="disk.qcow2", format="qcow2", opts=None)

    opts = parse_drive(drive_param_for("/tmp/disk.qcow2", spec))

    assert opts["discard"] == "unmap"


def test_drive_keeps_explicit_discard_policy():
    spec = DiskSpec(
        filename="disk.qcow2",
        format="qcow2",
        opts="if=virtio,discard=ignore",
    )

    param = drive_param_for("/tmp/disk.qcow2", spec)

    assert param.count("discard=") == 1
    assert parse_drive(param)["discard"] == "ignore"
