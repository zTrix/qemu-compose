from __future__ import annotations

import os
import stat

from qemu_compose.utils.unix_socket import (
    SUN_PATH_MAX,
    cleanup_unix_socket_dir,
    unix_socket_path,
    unix_socket_path_fits,
)


def test_short_socket_path_is_kept_in_instance_dir(tmp_path):
    base = tmp_path / "instance" / "vm1"

    assert unix_socket_path(str(base), "monitor.sock") == str(
        base / "monitor.sock"
    )


def test_long_socket_path_moves_to_private_runtime_dir(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))

    base = tmp_path / ("d" * 90) / "instance" / ("e" * 32)
    path = unix_socket_path(str(base), "virtiofs-data-0.sock")

    assert unix_socket_path_fits(path)
    assert not path.startswith(str(base))
    assert os.path.isdir(os.path.dirname(path))
    assert stat.S_IMODE(os.stat(os.path.dirname(path)).st_mode) == 0o700

    # Deterministic: the same instance dir must resolve to the same socket.
    assert path == unix_socket_path(str(base), "virtiofs-data-0.sock")


def test_socket_name_is_truncated_when_still_too_long(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))

    base = tmp_path / "instance" / "vm1"
    long_name = "x" * (SUN_PATH_MAX * 2) + ".sock"
    path = unix_socket_path(str(base), long_name)

    assert unix_socket_path_fits(path)
    assert path.endswith(".sock")
    assert path != unix_socket_path(str(base), long_name + "y")


def test_runtime_socket_dir_is_removed_on_instance_cleanup(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))

    base = tmp_path / ("d" * 90) / "instance" / ("e" * 32)
    path = unix_socket_path(str(base), "monitor.sock")
    socket_dir = os.path.dirname(path)
    assert os.path.isdir(socket_dir)

    cleanup_unix_socket_dir(str(base))

    assert not os.path.exists(socket_dir)
