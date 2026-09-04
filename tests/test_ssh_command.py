from __future__ import annotations

import os
from pathlib import Path

from qemu_compose.cmd.ssh_command import command_ssh


def _patch_exec(monkeypatch, exc=None):
    """Replace os.execvp so tests never actually launch a real ssh process.

    command_ssh() ends with os.execvp('ssh', ...), which replaces the whole
    process with the ssh client. When OpenSSH is installed (unlike when these
    tests were first written) that would dial the vsock and kill pytest with a
    255. Capturing argv also lets the tests assert the exact command built.
    """
    captured = {}

    def fake_execvp(file, argv):
        captured["file"] = file
        captured["argv"] = list(argv)
        if exc is not None:
            raise exc

    monkeypatch.setattr("os.execvp", fake_execvp)
    return captured


def test_ssh_with_identifier(tmp_path, monkeypatch):
    """Resolving by name builds the expected ssh command; missing ssh returns 127."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    instance_root = tmp_path / "qemu-compose" / "instance"
    vmid = "vm-12345678"
    instance_dir = instance_root / vmid
    instance_dir.mkdir(parents=True)
    (instance_dir / "name").write_text("my-vm")
    (instance_dir / "ssh-key").write_text("fake-key")
    (instance_dir / "cid").write_text("1001")

    # Simulate an environment without the ssh binary, deterministically.
    captured = _patch_exec(monkeypatch, exc=FileNotFoundError())

    assert command_ssh(identifier="my-vm") == 127

    assert captured["file"] == "ssh"
    argv = captured["argv"]
    assert argv[0] == "ssh"
    assert "-i" in argv
    assert os.path.join(instance_root, vmid, "ssh-key") in argv
    assert "root@vsock%1001" in argv


def test_ssh_without_identifier_reads_config_name(tmp_path, monkeypatch):
    """Reading name from qemu-compose.yml builds the expected ssh command."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    instance_root = tmp_path / "qemu-compose" / "instance"
    vmid = "vm-12345678"
    instance_dir = instance_root / vmid
    instance_dir.mkdir(parents=True)
    (instance_dir / "name").write_text("ubuntu__cloudimg")
    (instance_dir / "ssh-key").write_text("fake-key")
    (instance_dir / "cid").write_text("1001")

    config_path = tmp_path / "qemu-compose.yml"
    config_path.write_text("name: ubuntu__cloudimg\n")

    captured = _patch_exec(monkeypatch, exc=FileNotFoundError())

    assert command_ssh(config_path=str(config_path)) == 127

    assert captured["file"] == "ssh"
    argv = captured["argv"]
    assert argv[0] == "ssh"
    assert os.path.join(instance_root, vmid, "ssh-key") in argv
    assert "root@vsock%1001" in argv


def test_ssh_exec_succeeds_returns_zero(tmp_path, monkeypatch):
    """When exec succeeds (process handed off to ssh) command_ssh returns 0."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    instance_root = tmp_path / "qemu-compose" / "instance"
    vmid = "vm-12345678"
    instance_dir = instance_root / vmid
    instance_dir.mkdir(parents=True)
    (instance_dir / "name").write_text("my-vm")
    (instance_dir / "ssh-key").write_text("fake-key")
    (instance_dir / "cid").write_text("1001")

    captured = _patch_exec(monkeypatch)  # fake execvp returns normally

    assert command_ssh(identifier="my-vm") == 0
    assert "root@vsock%1001" in captured["argv"]


def test_ssh_without_identifier_no_config(tmp_path, monkeypatch, capsys):
    """Test ssh without identifier and no config fails."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    assert command_ssh() == 1
    assert "identifier is required" in capsys.readouterr().err


def test_ssh_config_without_name(tmp_path, monkeypatch, capsys):
    """Test ssh with config that has no name fails."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    config_path = tmp_path / "qemu-compose.yml"
    config_path.write_text("env:\n  foo: bar\n")

    assert command_ssh(config_path=str(config_path)) == 1
    assert "does not specify a name" in capsys.readouterr().err


def test_ssh_config_name_no_matching_instance(tmp_path, monkeypatch, capsys):
    """Test ssh with config name that doesn't match any instance fails."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    config_path = tmp_path / "qemu-compose.yml"
    config_path.write_text("name: nonexistent\n")

    assert command_ssh(config_path=str(config_path)) == 1
    assert "no VMID or NAME matches" in capsys.readouterr().err
