from __future__ import annotations

from pathlib import Path

from qemu_compose.cmd import down_command, stop_command
from qemu_compose.cmd.down_command import command_down
from qemu_compose.cmd.stop_command import command_stop


def write_instance(instance_root: Path, vmid: str, *, name: str, pid: str = "") -> Path:
    instance_dir = instance_root / vmid
    instance_dir.mkdir(parents=True)
    (instance_dir / "name").write_text(name)
    (instance_dir / "qemu.pid").write_text(pid)
    return instance_dir


def test_stop_stops_running_instance_without_removing_it(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    instance_root = tmp_path / "qemu-compose" / "instance"
    vmid = "abc123def456"
    instance_dir = write_instance(instance_root, vmid, name="vm1", pid="1234")
    stopped = []

    monkeypatch.setattr(stop_command, "_is_pid_running", lambda pid: pid == 1234)
    monkeypatch.setattr(stop_command, "stop_pid", lambda pid: stopped.append(pid) or True)

    assert command_stop(identifier="vm1") == 0

    assert instance_dir.exists()
    assert stopped == [1234]
    assert "Stopped instance vm1 (abc123def456)" in capsys.readouterr().out


def test_rm_refuses_running_instance_without_force(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    instance_root = tmp_path / "qemu-compose" / "instance"
    vmid = "abc123def456"
    instance_dir = write_instance(instance_root, vmid, name="vm1", pid="1234")

    monkeypatch.setattr(down_command, "_is_pid_running", lambda pid: pid == 1234)

    assert command_down(identifier="vm1", stop_running=False) == 1

    assert instance_dir.exists()
    assert (
        'Error response: cannot remove vm "vm1": vm is running: '
        "stop the vm before removing or force remove"
    ) in capsys.readouterr().err


def test_rm_force_stops_and_removes_running_instance(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    instance_root = tmp_path / "qemu-compose" / "instance"
    vmid = "abc123def456"
    instance_dir = write_instance(instance_root, vmid, name="vm1", pid="1234")
    stopped = []

    monkeypatch.setattr(down_command, "_is_pid_running", lambda pid: pid == 1234)
    monkeypatch.setattr(down_command, "stop_pid", lambda pid: stopped.append(pid) or True)

    assert command_down(identifier="vm1", force=True, stop_running=False) == 0

    assert not instance_dir.exists()
    assert stopped == [1234]
    assert "Removed instance vm1 (abc123def456)" in capsys.readouterr().out


def test_down_uses_compose_name_to_stop_and_remove_instance(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    instance_root = tmp_path / "qemu-compose" / "instance"
    vmid = "abc123def456"
    instance_dir = write_instance(instance_root, vmid, name="vm1", pid="1234")
    compose_file = tmp_path / "qemu-compose.yml"
    compose_file.write_text("name: vm1\n")
    stopped = []

    monkeypatch.setattr(down_command, "_is_pid_running", lambda pid: pid == 1234)
    monkeypatch.setattr(down_command, "stop_pid", lambda pid: stopped.append(pid) or True)

    assert command_down(config_path=str(compose_file), stop_running=True) == 0

    assert not instance_dir.exists()
    assert stopped == [1234]
    assert "Removed instance vm1 (abc123def456)" in capsys.readouterr().out
