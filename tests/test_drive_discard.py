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


def _stub_posix_module(name: str) -> None:
    if name in sys.modules:
        return
    try:
        __import__(name)
    except ModuleNotFoundError:
        sys.modules[name] = types.ModuleType(name)


# qemu_runner imports POSIX-only modules at import time.
for _posix_name in ("fcntl", "resource", "pty"):
    _stub_posix_module(_posix_name)
if "termios" not in sys.modules:
    try:
        import termios as _termios  # noqa: F401
    except ModuleNotFoundError:
        _termios_stub = types.ModuleType("termios")
        # tty.setraw() evaluates TCSAFLUSH when the function is defined.
        _termios_stub.TCSAFLUSH = 0
        sys.modules["termios"] = _termios_stub

from qemu_compose.image import DiskSpec
from qemu_compose.instance.qemu_runner import _has_drive_option, drive_param_for


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


def test_drive_keeps_explicit_discard_unmap():
    spec = DiskSpec(
        filename="disk.qcow2",
        format="qcow2",
        opts="if=virtio,discard=unmap",
    )

    param = drive_param_for("/tmp/disk.qcow2", spec)

    assert param.count("discard=") == 1
    assert parse_drive(param)["discard"] == "unmap"


def test_escaped_comma_in_value_is_not_a_discard_option():
    # QEMU encodes a comma inside a value as ",,". This serial value is
    # "vm,discard=ignore", not a discard option.
    opts = "if=virtio,serial=vm,,discard=ignore"
    spec = DiskSpec(filename="disk.qcow2", format="qcow2", opts=opts)

    assert _has_drive_option(opts, "discard") is False
    assert drive_param_for("/tmp/disk.qcow2", spec) == (
        "file=/tmp/disk.qcow2,format=qcow2,if=virtio,serial=vm,,discard=ignore,discard=unmap"
    )


def test_explicit_discard_after_escaped_comma_is_kept():
    opts = "if=virtio,serial=vm,,name,discard=ignore"
    spec = DiskSpec(filename="disk.qcow2", format="qcow2", opts=opts)

    assert _has_drive_option(opts, "discard") is True
    param = drive_param_for("/tmp/disk.qcow2", spec)
    assert param.count("discard=") == 1
    assert param.endswith(",discard=ignore")
