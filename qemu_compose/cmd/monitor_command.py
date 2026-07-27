from __future__ import annotations

import os
import socket
import sys
import threading
from typing import BinaryIO, Optional

from qemu_compose.cmd.ssh_command import (
    _build_name_index,
    _list_vmids,
    _resolve_identifier_with_prefix,
)
from qemu_compose.local_store import LocalStore


def _relay_monitor(
    monitor: socket.socket,
    input_stream: BinaryIO,
    output_stream: BinaryIO,
) -> None:
    def copy_input() -> None:
        try:
            while data := input_stream.read(65536):
                monitor.sendall(data)
            monitor.shutdown(socket.SHUT_WR)
        except (BrokenPipeError, OSError):
            pass

    input_thread = threading.Thread(target=copy_input, daemon=True)
    input_thread.start()

    while data := monitor.recv(65536):
        output_stream.write(data)
        output_stream.flush()


def _connect_monitor(
    socket_path: str,
    input_stream: Optional[BinaryIO] = None,
    output_stream: Optional[BinaryIO] = None,
) -> None:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as monitor:
        monitor.connect(socket_path)
        _relay_monitor(
            monitor,
            input_stream or sys.stdin.buffer,
            output_stream or sys.stdout.buffer,
        )


def command_monitor(
    *,
    identifier: Optional[str] = None,
    config_path: Optional[str] = None,
) -> int:
    store = LocalStore()
    instance_root = store.instance_root
    ids = _list_vmids(instance_root)
    name_index = _build_name_index(instance_root)
    vmid = None
    candidates = []

    if identifier:
        vmid, candidates = _resolve_identifier_with_prefix(identifier, ids, name_index)
    elif config_path:
        import yaml

        try:
            with open(config_path) as config_file:
                config = yaml.safe_load(config_file)
            config_name = config.get("name") if config else None
            if not config_name:
                print("Error: config file does not specify a name", file=sys.stderr)
                return 1
            vmid, candidates = _resolve_identifier_with_prefix(config_name, ids, name_index)
        except Exception as error:
            print(f"Error: failed to read config file: {error}", file=sys.stderr)
            return 1
    else:
        print("Error: identifier is required", file=sys.stderr)
        return 1

    if vmid is None and not candidates:
        print("Error: no VMID or NAME matches the given prefix.", file=sys.stderr)
        return 1
    if vmid is None:
        preview = ", ".join(sorted(candidates)[:8])
        more = "" if len(candidates) <= 8 else f" ... and {len(candidates)-8} more"
        print(f"Error: identifier '{identifier}' is ambiguous; matches: {preview}{more}", file=sys.stderr)
        return 1

    socket_path = os.path.join(instance_root, vmid, "monitor.sock")
    try:
        _connect_monitor(socket_path)
    except FileNotFoundError:
        print(f"Error: monitor socket not found: {socket_path}", file=sys.stderr)
        return 1
    except ConnectionRefusedError:
        print(f"Error: monitor is not accepting connections: {socket_path}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    except OSError as error:
        print(f"Error connecting to monitor: {error}", file=sys.stderr)
        return 1
    return 0
