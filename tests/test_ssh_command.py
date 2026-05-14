from __future__ import annotations

import os
from pathlib import Path

from qemu_compose.cmd.ssh_command import command_ssh


def test_ssh_with_identifier(tmp_path, monkeypatch, capsys):
    """Test ssh with explicit identifier works."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    instance_root = tmp_path / "qemu-compose" / "instance"
    vmid = "vm-12345678"
    instance_dir = instance_root / vmid
    instance_dir.mkdir(parents=True)
    (instance_dir / "name").write_text("my-vm")
    (instance_dir / "ssh-key").write_text("fake-key")
    (instance_dir / "cid").write_text("1001")

    # Should resolve by name and return 127 (ssh not found in test env)
    assert command_ssh(identifier="my-vm") == 127


def test_ssh_without_identifier_reads_config_name(tmp_path, monkeypatch, capsys):
    """Test ssh without identifier reads name from qemu-compose.yml."""
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

    # Should resolve by config name and return 127 (ssh not found in test env)
    assert command_ssh(config_path=str(config_path)) == 127


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
