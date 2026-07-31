from __future__ import annotations

import os
import select
import socket
import sys
import termios
import tty
from typing import Optional

from qemu_compose.cmd.down_command import _is_pid_running, _to_int, resolve_instance
from qemu_compose.local_store import LocalStore
from qemu_compose.utils import safe_read


DETACH_SEQUENCE = b"\x10\x11"  # Ctrl-p, Ctrl-q


def _relay_attach(sock: socket.socket, input_fd: int, output_fd: int) -> None:
    pending_prefix = False
    input_open = True

    while True:
        readers = [sock]
        if input_open:
            readers.append(input_fd)
        readable, _, _ = select.select(readers, [], [])

        if sock in readable:
            data = sock.recv(65536)
            if not data:
                return
            os.write(output_fd, data)

        if input_open and input_fd in readable:
            data = os.read(input_fd, 65536)
            if not data:
                input_open = False
                if pending_prefix:
                    sock.sendall(DETACH_SEQUENCE[:1])
                    pending_prefix = False
                try:
                    sock.shutdown(socket.SHUT_WR)
                except OSError:
                    pass
                continue

            output = bytearray()
            for byte in data:
                if pending_prefix:
                    if byte == DETACH_SEQUENCE[1]:
                        if output:
                            sock.sendall(output)
                        return
                    output.append(DETACH_SEQUENCE[0])
                    pending_prefix = False
                if byte == DETACH_SEQUENCE[0]:
                    pending_prefix = True
                else:
                    output.append(byte)
            if output:
                sock.sendall(output)


def command_attach(
    *,
    identifier: Optional[str] = None,
    config_path: Optional[str] = None,
) -> int:
    store = LocalStore()
    vmid, _, exit_code = resolve_instance(
        store=store,
        identifier=identifier,
        config_path=config_path,
    )
    if exit_code != 0 or vmid is None:
        return exit_code

    instance_dir = os.path.join(store.instance_root, vmid)
    qemu_pid = _to_int(safe_read(os.path.join(instance_dir, "qemu.pid")))
    if not _is_pid_running(qemu_pid):
        print("Error: instance is not running", file=sys.stderr)
        return 1

    attach_path = os.path.join(instance_dir, "attach.sock")
    if not os.path.exists(attach_path):
        print(
            "Error: instance has no attach socket; it may still be provisioning "
            "or was not started in detached mode",
            file=sys.stderr,
        )
        return 1

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.connect(attach_path)
    except OSError as exc:
        sock.close()
        print(f"Error: failed to attach to instance: {exc}", file=sys.stderr)
        return 1

    input_fd = sys.stdin.fileno()
    output_fd = sys.stdout.fileno()
    old_tty = None
    if os.isatty(input_fd):
        old_tty = termios.tcgetattr(input_fd)
        tty.setraw(input_fd)

    try:
        _relay_attach(sock, input_fd, output_fd)
    except KeyboardInterrupt:
        pass
    finally:
        if old_tty is not None:
            termios.tcsetattr(input_fd, termios.TCSAFLUSH, old_tty)
        sock.close()
    return 0
