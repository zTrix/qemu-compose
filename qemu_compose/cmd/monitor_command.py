from __future__ import annotations

import asyncio
import os
import socket
import sys
from typing import BinaryIO, Optional

from qemu_compose.cmd.ssh_command import (
    _build_name_index,
    _list_vmids,
    _resolve_identifier_with_prefix,
)
from qemu_compose.local_store import LocalStore


async def _read_input(input_stream: BinaryIO) -> bytes:
    """Read stdin without leaving a blocking worker behind on cancellation."""
    try:
        fd = input_stream.fileno()
    except (AttributeError, OSError):
        # In-memory streams are useful to callers and tests and cannot block.
        return input_stream.read(65536)

    loop = asyncio.get_running_loop()
    ready = loop.create_future()

    def read_ready() -> None:
        if ready.done():
            return
        try:
            ready.set_result(os.read(fd, 65536))
        except OSError as error:
            ready.set_exception(error)

    try:
        loop.add_reader(fd, read_ready)
    except (NotImplementedError, PermissionError):
        # epoll cannot watch regular files (for example, redirected stdin),
        # but reading one cannot wait indefinitely for interactive input.
        return input_stream.read(65536)
    try:
        return await ready
    finally:
        loop.remove_reader(fd)


async def _relay_monitor_async(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    input_stream: BinaryIO,
    output_stream: BinaryIO,
) -> None:
    async def copy_input() -> None:
        try:
            while data := await _read_input(input_stream):
                writer.write(data)
                await writer.drain()
            if writer.can_write_eof():
                writer.write_eof()
                await writer.drain()
        except (BrokenPipeError, ConnectionError, OSError):
            pass

    async def copy_output() -> None:
        while data := await reader.read(65536):
            output_stream.write(data)
            output_stream.flush()

    input_task = asyncio.ensure_future(copy_input())
    output_task = asyncio.ensure_future(copy_output())
    try:
        done, _ = await asyncio.wait(
            (input_task, output_task),
            return_when=asyncio.FIRST_COMPLETED,
        )
        if output_task in done:
            await output_task
        else:
            await input_task
            await output_task
    finally:
        for task in (input_task, output_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(input_task, output_task, return_exceptions=True)


async def _relay_socket_async(
    monitor: socket.socket,
    input_stream: BinaryIO,
    output_stream: BinaryIO,
) -> None:
    reader, writer = await asyncio.open_connection(sock=monitor)
    try:
        await _relay_monitor_async(reader, writer, input_stream, output_stream)
    finally:
        writer.close()
        await writer.wait_closed()


def _relay_monitor(
    monitor: socket.socket,
    input_stream: BinaryIO,
    output_stream: BinaryIO,
) -> None:
    """Synchronously expose the asyncio monitor relay to internal callers."""
    asyncio.run(_relay_socket_async(monitor, input_stream, output_stream))


async def _connect_monitor_async(
    socket_path: str,
    input_stream: BinaryIO,
    output_stream: BinaryIO,
) -> None:
    reader, writer = await asyncio.open_unix_connection(socket_path)
    try:
        await _relay_monitor_async(reader, writer, input_stream, output_stream)
    finally:
        writer.close()
        await writer.wait_closed()


def _connect_monitor(
    socket_path: str,
    input_stream: Optional[BinaryIO] = None,
    output_stream: Optional[BinaryIO] = None,
) -> None:
    asyncio.run(
        _connect_monitor_async(
            socket_path,
            input_stream or sys.stdin.buffer,
            output_stream or sys.stdout.buffer,
        )
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
        if not os.path.exists(socket_path):
            print(f"Error: monitor socket not found: {socket_path}", file=sys.stderr)
        else:
            print(f"Error connecting to monitor: {error}", file=sys.stderr)
        return 1
    return 0
