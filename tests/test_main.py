from __future__ import annotations

from qemu_compose import main


def test_rm_dispatches_to_down_without_stopping_unless_forced(monkeypatch):
    calls = []

    def fake_command_down(*, identifier=None, force=False, config_path=None, stop_running=True):
        calls.append((identifier, force, config_path, stop_running))
        return 0

    monkeypatch.setattr("qemu_compose.cmd.down_command.command_down", fake_command_down)

    assert main.command_rm(["vm1"]) == 0
    assert calls == [("vm1", False, None, False)]


def test_rm_short_f_means_force(monkeypatch):
    calls = []

    def fake_command_down(*, identifier=None, force=False, config_path=None, stop_running=True):
        calls.append((identifier, force, config_path, stop_running))
        return 0

    monkeypatch.setattr("qemu_compose.cmd.down_command.command_down", fake_command_down)

    assert main.command_rm(["-f", "vm1"]) == 0
    assert calls == [("vm1", True, None, False)]


def test_down_uses_current_compose_file(monkeypatch):
    calls = []

    def fake_command_down(*, identifier=None, force=False, config_path=None, stop_running=True):
        calls.append((identifier, force, config_path, stop_running))
        return 0

    monkeypatch.setattr("qemu_compose.cmd.down_command.command_down", fake_command_down)
    monkeypatch.setattr(main, "guess_conf_path", lambda path: "qemu-compose.yml")

    assert main.command_down([]) == 0
    assert calls == [(None, False, "qemu-compose.yml", True)]


def test_down_requires_current_compose_file(monkeypatch, capsys):
    monkeypatch.setattr(main, "guess_conf_path", lambda path: None)

    assert main.command_down([]) == 1
    assert "qemu-compose.yml not found" in capsys.readouterr().err
