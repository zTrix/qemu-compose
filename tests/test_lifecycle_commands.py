from __future__ import annotations

import os
from pathlib import Path

from qemu_compose.cmd import down_command, stop_command, up_command
from qemu_compose.cmd.down_command import command_down
from qemu_compose.cmd.stop_command import command_stop
from qemu_compose.cmd.up_command import command_up
from qemu_compose.instance.lifecycle import run_vm_lifecycle


def write_instance(instance_root: Path, vmid: str, *, name: str, pid: str = "") -> Path:
    instance_dir = instance_root / vmid
    instance_dir.mkdir(parents=True)
    (instance_dir / "name").write_text(name)
    (instance_dir / "qemu.pid").write_text(pid)
    return instance_dir


def write_instance_config(instance_dir: Path, vmid: str, *, name: str) -> None:
    (instance_dir / "instance-id").write_text(vmid)
    (instance_dir / "qemu_config.json").write_text(
        '{"name": "%s", "network": "user", "qemu_args": [], "ports": [], '
        '"volumes": [], "boot_commands": [], "before_script": [], '
        '"after_script": [], "http_serve": {}}' % name
    )


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


def test_up_starts_existing_named_instance(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    instance_root = tmp_path / "qemu-compose" / "instance"
    vmid = "abc123def456"
    instance_dir = write_instance(instance_root, vmid, name="vm1")
    write_instance_config(instance_dir, vmid, name="vm1")
    compose_file = tmp_path / "qemu-compose.yml"
    compose_file.write_text("name: vm1\nnetwork: none\n")
    calls = []

    class FakeRunner:
        def __init__(self, config, store, cwd):
            calls.append(("init", config.instance, config.name, config.network, cwd))

        def check_and_lock(self):
            calls.append(("check_and_lock",))
            return 0

        def prepare_env(self, env_update=None):
            calls.append(("prepare_env", env_update))

        def prepare_storage(self):
            calls.append(("prepare_storage",))
            return 0

        def execute_script(self, name):
            calls.append(("execute_script", name))

        def setup_qemu_args(self):
            calls.append(("setup_qemu_args",))

        def start(self):
            calls.append(("start",))

        def interact(self):
            calls.append(("interact",))

        def is_running(self):
            return False

        def cleanup(self):
            calls.append(("cleanup",))

    monkeypatch.setattr("qemu_compose.cmd.start_command.QemuRunner", FakeRunner)

    assert command_up(config_path=str(compose_file), project_directory="/project") == 0

    assert ("init", vmid, "vm1", "none", str(tmp_path)) in calls
    assert ("prepare_env", {"CWD": "/project"}) in calls
    assert ("start",) in calls


def test_up_creates_new_instance_when_name_is_unused(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    compose_file = tmp_path / "qemu-compose.yml"
    compose_file.write_text("name: vm1\nnetwork: none\n")
    calls = []

    class FakeRunner:
        def __init__(self, config, store, cwd):
            self.instance_dir = str(tmp_path / "new-instance")
            Path(self.instance_dir).mkdir()
            calls.append(("init", config.instance, config.name, cwd))

        def check_and_lock(self):
            calls.append(("check_and_lock",))
            return 0

        def prepare_env(self, env_update=None):
            calls.append(("prepare_env", env_update))

        def prepare_storage(self):
            calls.append(("prepare_storage",))
            return 0

        def execute_script(self, name):
            calls.append(("execute_script", name))

        def setup_qemu_args(self):
            calls.append(("setup_qemu_args",))

        def start(self):
            calls.append(("start",))

        def interact(self):
            calls.append(("interact",))

        def is_running(self):
            return False

        def cleanup(self):
            calls.append(("cleanup",))

    monkeypatch.setattr("qemu_compose.cmd.up_command.QemuRunner", FakeRunner)

    assert command_up(config_path=str(compose_file)) == 0

    assert ("init", None, "vm1", str(tmp_path)) in calls
    assert ("prepare_env", None) in calls
    assert ("start",) in calls


def test_detached_lifecycle_reports_ready_then_waits_and_cleans_up():
    calls = []

    class FakeRunner:
        running = True

        def start(self):
            calls.append("start")

        def interact(self, detached=False):
            calls.append(("interact", detached))

        def start_console_drain(self):
            calls.append("drain")

        def is_running(self):
            if calls and calls[-1] == "ready":
                self.running = False
            return self.running

        def wait(self, timeout=None):
            calls.append(("wait", timeout))

        def execute_script(self, name):
            calls.append(("script", name))

        def cleanup(self):
            calls.append("cleanup")

    runner = FakeRunner()
    assert run_vm_lifecycle(
        runner,
        detached=True,
        on_ready=lambda _vm: calls.append("ready"),
    ) == 0

    assert calls == [
        "start",
        ("interact", True),
        "drain",
        "ready",
        ("wait", None),
        ("script", "after_script"),
        "cleanup",
    ]


def test_stop_prefers_detached_supervisor_pid(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    instance_root = tmp_path / "qemu-compose" / "instance"
    instance_dir = write_instance(instance_root, "abc123def456", name="vm1", pid="1234")
    (instance_dir / "supervisor.pid").write_text("4321")
    stopped = []

    monkeypatch.setattr(stop_command, "_is_pid_running", lambda pid: pid in (1234, 4321))
    monkeypatch.setattr(stop_command, "stop_pid", lambda pid: stopped.append(pid) or True)

    assert command_stop(identifier="vm1") == 0
    assert stopped == [4321]


def test_detached_parent_waits_for_worker_readiness(monkeypatch, tmp_path, capsys):
    compose_file = tmp_path / "qemu-compose.yml"
    compose_file.write_text("name: vm1\n")

    def fake_popen(_command, **kwargs):
        write_fd = kwargs["pass_fds"][0]
        os.write(write_fd, (
            '{"status":"ready","instance_id":"abc123","name":"vm1",'
            '"qemu_pid":1234,"supervisor_pid":4321}\n'
        ).encode())
        return object()

    monkeypatch.setattr(up_command.subprocess, "Popen", fake_popen)

    assert command_up(config_path=str(compose_file), detach=True) == 0
    assert "Started vm1 (abc123) in detached mode" in capsys.readouterr().out


def test_detached_parent_propagates_worker_failure(monkeypatch, tmp_path, capsys):
    compose_file = tmp_path / "qemu-compose.yml"
    compose_file.write_text("name: vm1\n")

    def fake_popen(_command, **kwargs):
        write_fd = kwargs["pass_fds"][0]
        os.write(write_fd, b'{"status":"error","exit_code":7,"message":"QEMU failed"}\n')
        return object()

    monkeypatch.setattr(up_command.subprocess, "Popen", fake_popen)

    assert command_up(config_path=str(compose_file), detach=True) == 7
    assert "QEMU failed" in capsys.readouterr().err


def test_detached_real_supervisor_reports_startup_failure(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "store"))
    compose_file = tmp_path / "qemu-compose.yml"
    compose_file.write_text(
        "name: broken-vm\n"
        "binary: /definitely/missing/qemu-system-x86_64\n"
        "network: none\n"
    )

    result = command_up(config_path=str(compose_file), detach=True)

    assert result != 0
    assert "Error:" in capsys.readouterr().err
