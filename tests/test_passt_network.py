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


def _make_runner(tmp_path, monkeypatch, *, ports=None, passt=None):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.delenv("QEMU_COMPOSE_NO_PASST", raising=False)
    monkeypatch.delenv("QEMU_COMPOSE_PASST_DEBUG", raising=False)
    monkeypatch.setattr(qemu_runner, "prepare_ssh_key", lambda _dir, _vmid: b"key")
    store = LocalStore()
    config = QemuConfig(binary="/bin/true", name="vm1", ports=ports or [], passt=passt)
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
    runner.passt_fd = 123

    assert runner._passt_port_args() == [
        "-t", "127.0.0.1/2222:22",
        "-t", "8080:80",
        "-u", "5353:53",
    ]

    cmd = runner._passt_command()
    assert cmd[0] == "/usr/bin/passt"
    assert cmd[cmd.index("-g") + 1] == "10.0.2.2"
    assert "-D" not in cmd
    assert "-d" not in cmd
    assert cmd[cmd.index("-F") + 1] == "123"
    assert "-s" not in cmd
    assert "-l" not in cmd
    assert "-e" not in cmd
    assert "-t" in cmd
    assert "-u" in cmd


def test_setup_uses_passt_fd_netdev_when_passt_exists(tmp_path, monkeypatch):
    runner = _make_runner(tmp_path, monkeypatch)

    real_which = qemu_runner.shutil.which

    def fake_which(name, *args, **kwargs):
        if name == "passt":
            return "/usr/bin/passt"
        return real_which(name, *args, **kwargs)

    monkeypatch.setattr(qemu_runner.shutil, "which", fake_which)
    # Older passt builds (e.g. Ubuntu 24.04) do not advertise --vhost-user.
    monkeypatch.setattr(
        runner, "_passt_supports_vhost_user", lambda _passt_bin: False
    )

    runner.setup_qemu_args()

    assert runner.using_passt is True
    assert runner.passt_mode == "stream"
    assert runner.passt_socketpair is not None
    assert any(
        arg.startswith("socket,id=user.qemu-compose,fd=")
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


def test_setup_skips_passt_when_env_disables_it(tmp_path, monkeypatch):
    runner = _make_runner(tmp_path, monkeypatch)
    monkeypatch.setenv("QEMU_COMPOSE_NO_PASST", "1")

    real_which = qemu_runner.shutil.which

    def fake_which(name, *args, **kwargs):
        if name == "passt":
            return "/usr/bin/passt"
        return real_which(name, *args, **kwargs)

    monkeypatch.setattr(qemu_runner.shutil, "which", fake_which)

    runner.setup_qemu_args()

    assert runner.using_passt is False
    assert any(arg.startswith("user,id=user.qemu-compose") for arg in runner._args)
    assert not any(
        arg.startswith("socket,id=user.qemu-compose,fd=") for arg in runner._args
    )


def test_config_passt_false_forces_slirp(tmp_path, monkeypatch):
    runner = _make_runner(tmp_path, monkeypatch, passt=False)

    real_which = qemu_runner.shutil.which

    def fake_which(name, *args, **kwargs):
        if name == "passt":
            return "/usr/bin/passt"
        return real_which(name, *args, **kwargs)

    monkeypatch.setattr(qemu_runner.shutil, "which", fake_which)

    runner.setup_qemu_args()

    assert runner.using_passt is False
    assert any(arg.startswith("user,id=user.qemu-compose") for arg in runner._args)
    assert not any(
        arg.startswith("socket,id=user.qemu-compose,fd=") for arg in runner._args
    )


def test_env_disable_overrides_config_passt_true(tmp_path, monkeypatch):
    runner = _make_runner(tmp_path, monkeypatch, passt=True)
    monkeypatch.setenv("QEMU_COMPOSE_NO_PASST", "true")

    real_which = qemu_runner.shutil.which

    def fake_which(name, *args, **kwargs):
        if name == "passt":
            return "/usr/bin/passt"
        return real_which(name, *args, **kwargs)

    monkeypatch.setattr(qemu_runner.shutil, "which", fake_which)

    runner.setup_qemu_args()

    assert runner.using_passt is False


def test_passt_help_detects_vhost_user_support(tmp_path, monkeypatch):
    runner = _make_runner(tmp_path, monkeypatch)

    monkeypatch.setattr(
        qemu_runner.subprocess,
        "run",
        lambda *args, **kwargs: types.SimpleNamespace(
            stdout=b"  --vhost-user\t\tEnable vhost-user mode\n"
        ),
    )
    assert runner._passt_supports_vhost_user("/usr/bin/passt") is True

    monkeypatch.setattr(
        qemu_runner.subprocess,
        "run",
        lambda *args, **kwargs: types.SimpleNamespace(stdout=b"  -s PATH  socket\n"),
    )
    assert runner._passt_supports_vhost_user("/usr/bin/passt") is False


def test_setup_uses_vhost_user_when_passt_supports_it(tmp_path, monkeypatch):
    runner = _make_runner(tmp_path, monkeypatch)

    real_which = qemu_runner.shutil.which

    def fake_which(name, *args, **kwargs):
        if name == "passt":
            return "/usr/bin/passt"
        return real_which(name, *args, **kwargs)

    monkeypatch.setattr(qemu_runner.shutil, "which", fake_which)
    monkeypatch.setattr(
        runner, "_passt_supports_vhost_user", lambda _passt_bin: True
    )

    runner.setup_qemu_args()

    assert runner.using_passt is True
    assert runner.passt_mode == "vhost-user"
    assert runner.passt_socketpair is None
    assert runner.passt_vhost_socket == str(
        tmp_path / "qemu-compose" / "instance" / "abc12345" / "passt-vhost-user.sock"
    )

    # vhost-user bypasses QEMU's net/socket.c entirely.
    assert not any(
        arg.startswith("socket,id=user.qemu-compose,fd=") for arg in runner._args
    )
    assert any(
        arg.startswith("socket,id=qc-passt-vhost,path=") for arg in runner._args
    )
    assert "vhost-user,id=user.qemu-compose,chardev=qc-passt-vhost,vhostforce=on" in runner._args

    # vhost-user requires shared guest RAM even without virtiofs volumes.
    assert "memory-backend-memfd,id=qc-mem,size=1G,share=on" in runner._args
    assert "node,memdev=qc-mem" in runner._args


def test_passt_debug_logging_is_opt_in(tmp_path, monkeypatch):
    runner = _make_runner(tmp_path, monkeypatch)
    runner.passt_binary = "/usr/bin/passt"
    runner.passt_fd = 123

    assert "-d" not in runner._passt_command()

    for value in ("1", "true", "yes", "on"):
        monkeypatch.setenv("QEMU_COMPOSE_PASST_DEBUG", value)
        assert "-d" in runner._passt_command()


def test_passt_command_uses_vhost_user_socket(tmp_path, monkeypatch):
    runner = _make_runner(
        tmp_path, monkeypatch, ports=["8080:80/tcp", "5353:53/udp"]
    )
    runner.passt_binary = "/usr/bin/passt"
    runner.passt_mode = "vhost-user"
    runner.passt_vhost_socket = "/tmp/passt-vhost.sock"

    cmd = runner._passt_command()

    assert cmd[cmd.index("--vhost-user") + 1] == "-s"
    assert cmd[cmd.index("--vhost-user") + 2] == "/tmp/passt-vhost.sock"
    assert "-F" not in cmd
    assert "-t" in cmd
    assert "-u" in cmd
