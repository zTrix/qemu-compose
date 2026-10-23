from __future__ import annotations

import sys
import types

try:
    from Crypto.PublicKey import ECC as _ECC  # noqa: F401
except Exception:
    crypto_module = types.ModuleType("Crypto")
    crypto_public_key_module = types.ModuleType("Crypto.PublicKey")
    crypto_public_key_module.ECC = object()
    sys.modules.setdefault("Crypto", crypto_module)
    sys.modules.setdefault("Crypto.PublicKey", crypto_public_key_module)

import qemu_compose.instance.qemu_runner as qemu_runner
from qemu_compose.instance.qemu_runner import QemuConfig, QemuRunner
from qemu_compose.local_store import LocalStore


def _make_runner(tmp_path, monkeypatch, *, ports=None):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(qemu_runner, "prepare_ssh_key", lambda _dir, _vmid: b"key")
    store = LocalStore()
    config = QemuConfig(binary="/bin/true", name="vm1", ports=ports or [])
    runner = QemuRunner(config, store, str(tmp_path))
    runner.vmid = "abc12345"
    runner.vm_name = "vm1"
    runner.cid = 1000
    runner.env = {"ID": runner.vmid, "CWD": str(tmp_path)}
    return runner


def test_passt_port_arguments_and_slirp_compatible_addresses(tmp_path, monkeypatch):
    runner = _make_runner(
        tmp_path,
        monkeypatch,
        ports=["127.0.0.1:2222:22", "8080:80/tcp", "5353:53/udp"],
    )
    runner.passt_binary = "/usr/bin/passt"
    runner.passt_socket = str(tmp_path / "passt.sock")

    assert runner._passt_port_args() == [
        "-t", "127.0.0.1/2222:22",
        "-t", "8080:80",
        "-u", "5353:53",
    ]

    cmd = runner._passt_command()
    assert cmd[0] == "/usr/bin/passt"
    assert cmd[cmd.index("-g") + 1] == "10.0.2.2"
    assert cmd[cmd.index("-D") + 1] == "10.0.2.3"
    assert "-e" in cmd
    assert "-t" in cmd
    assert "-u" in cmd


def test_setup_uses_passt_stream_netdev_when_passt_exists(tmp_path, monkeypatch):
    runner = _make_runner(tmp_path, monkeypatch)

    real_which = qemu_runner.shutil.which

    def fake_which(name, *args, **kwargs):
        if name == "passt":
            return "/usr/bin/passt"
        return real_which(name, *args, **kwargs)

    monkeypatch.setattr(qemu_runner.shutil, "which", fake_which)

    runner.setup_qemu_args()

    assert runner.using_passt is True
    assert any(
        arg.startswith("stream,id=user.qemu-compose,addr.type=unix,addr.path=")
        for arg in runner._args
    )
    assert not any(arg.startswith("user,id=user.qemu-compose") for arg in runner._args)


def test_setup_falls_back_to_qemu_user_network_without_passt(tmp_path, monkeypatch):
    runner = _make_runner(tmp_path, monkeypatch, ports=["2222:22"])

    real_which = qemu_runner.shutil.which

    def fake_which(name, *args, **kwargs):
        if name == "passt":
            return None
        return real_which(name, *args, **kwargs)

    monkeypatch.setattr(qemu_runner.shutil, "which", fake_which)

    runner.setup_qemu_args()

    assert runner.using_passt is False
    assert any(
        arg.startswith("user,id=user.qemu-compose") and "hostfwd=tcp::2222-:22" in arg
        for arg in runner._args
    )
