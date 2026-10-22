from __future__ import annotations

import os
import socket
import threading
from types import SimpleNamespace

from qemu_compose.cmd.attach_command import _relay_attach
from qemu_compose.instance import terminal


def test_detached_interact_ends_boot_command_batch(monkeypatch):
    calls = []
    term = terminal.Terminal.__new__(terminal.Terminal)
    term.io = SimpleNamespace(
        read_until=lambda *_args: None,
        write=lambda *_args: None,
        writeline=lambda *_args: None,
        read_until_timeout=lambda *_args: None,
    )
    term.debug_file = None
    term.term_feed_running = False
    term.term_feed_drain_thread = None

    def fake_default_env():
        return {}

    def fake_interp(_commands, env):
        calls.append("before")
        env["interact"]()
        calls.append("after")

    monkeypatch.setattr(terminal, "default_env", fake_default_env)
    monkeypatch.setattr(terminal, "interp", fake_interp)

    term.run_batch([{"interact": None}], forward_stdin=False)

    assert calls == ["before"]


def test_attach_relay_forwards_input_and_honors_detach_keys():
    client, server = socket.socketpair()
    input_read, input_write = os.pipe()
    output_read, output_write = os.pipe()
    os.write(input_write, b"hello\x10\x11")
    os.close(input_write)

    relay = threading.Thread(
        target=_relay_attach,
        args=(client, input_read, output_write),
    )
    relay.start()
    relay.join(timeout=2)

    assert not relay.is_alive()
    assert server.recv(5) == b"hello"

    client.close()
    server.close()
    os.close(input_read)
    os.close(output_read)
    os.close(output_write)


def test_attach_relay_forwards_vm_output():
    client, server = socket.socketpair()
    input_read, input_write = os.pipe()
    output_read, output_write = os.pipe()

    relay = threading.Thread(
        target=_relay_attach,
        args=(client, input_read, output_write),
    )
    relay.start()
    server.sendall(b"guest console\n")
    server.close()
    relay.join(timeout=2)

    assert not relay.is_alive()
    assert os.read(output_read, 4096) == b"guest console\n"

    client.close()
    os.close(input_read)
    os.close(input_write)
    os.close(output_read)
    os.close(output_write)
