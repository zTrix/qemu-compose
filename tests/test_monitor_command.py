from __future__ import annotations

import io
import socket
import threading

from qemu_compose.cmd.monitor_command import _relay_monitor, command_monitor


def create_instance(tmp_path, vmid="vm-12345678", name="my-vm"):
    instance_dir = tmp_path / "qemu-compose" / "instance" / vmid
    instance_dir.mkdir(parents=True)
    (instance_dir / "name").write_text(name)
    return instance_dir


def test_monitor_resolves_name_and_connects(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    instance_dir = create_instance(tmp_path)
    connected = []
    monkeypatch.setattr(
        "qemu_compose.cmd.monitor_command._connect_monitor",
        lambda path: connected.append(path),
    )

    assert command_monitor(identifier="my-vm") == 0
    assert connected == [str(instance_dir / "monitor.sock")]


def test_monitor_uses_compose_name_when_identifier_is_omitted(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    instance_dir = create_instance(tmp_path)
    config_path = tmp_path / "qemu-compose.yml"
    config_path.write_text("name: my-vm\n")
    connected = []
    monkeypatch.setattr(
        "qemu_compose.cmd.monitor_command._connect_monitor",
        lambda path: connected.append(path),
    )

    assert command_monitor(config_path=str(config_path)) == 0
    assert connected == [str(instance_dir / "monitor.sock")]


def test_monitor_reports_missing_socket(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    instance_dir = create_instance(tmp_path)

    assert command_monitor(identifier="vm-123") == 1
    assert str(instance_dir / "monitor.sock") in capsys.readouterr().err


def test_monitor_relay_copies_input_and_output():
    client, server = socket.socketpair()
    received = []

    def serve():
        with server:
            server.sendall(b"QEMU monitor\n")
            received.append(server.recv(65536))
            server.sendall(b"OK\n")

    server_thread = threading.Thread(target=serve)
    server_thread.start()
    output = io.BytesIO()
    with client:
        _relay_monitor(client, io.BytesIO(b"info status\n"), output)
    server_thread.join()

    assert received == [b"info status\n"]
    assert output.getvalue() == b"QEMU monitor\nOK\n"
