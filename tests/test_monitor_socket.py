import sys
import types
from pathlib import Path

try:
    from Crypto.PublicKey import ECC as _ECC  # noqa: F401
except Exception:
    crypto_module = types.ModuleType("Crypto")
    crypto_public_key_module = types.ModuleType("Crypto.PublicKey")
    crypto_public_key_module.ECC = object()
    sys.modules.setdefault("Crypto", crypto_module)
    sys.modules.setdefault("Crypto.PublicKey", crypto_public_key_module)

from qemu_compose.instance.qemu_runner import QemuConfig, QemuRunner


class FakeStore:
    def __init__(self, instance_dir: Path):
        self._instance_dir = instance_dir

    def instance_dir(self, vmid: str) -> str:
        return str(self._instance_dir)


def test_monitor_listens_in_instance_directory_by_default(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "qemu_compose.instance.qemu_runner.prepare_ssh_key",
        lambda instance_dir, vmid: b"ssh-ed25519 test",
    )
    runner = QemuRunner(
        QemuConfig(binary="/bin/true", network="none"),
        FakeStore(tmp_path),
        str(tmp_path),
    )
    runner.vmid = "test-vm"
    runner.env = {}
    runner.setup_qemu_args()

    monitor_index = runner.args.index("-monitor")
    assert runner.args[monitor_index + 1] == (
        f"unix:{tmp_path / 'monitor.sock'},server=on,wait=off"
    )


def test_explicit_monitor_overrides_default(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "qemu_compose.instance.qemu_runner.prepare_ssh_key",
        lambda instance_dir, vmid: b"ssh-ed25519 test",
    )
    runner = QemuRunner(
        QemuConfig(
            binary="/bin/true",
            network="none",
            qemu_args=[{"monitor": "stdio"}],
        ),
        FakeStore(tmp_path),
        str(tmp_path),
    )
    runner.vmid = "test-vm"
    runner.env = {}
    runner.setup_qemu_args()

    monitor_index = runner.args.index("-monitor")
    assert runner.args[monitor_index + 1] == "stdio"
