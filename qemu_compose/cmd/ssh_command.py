from __future__ import annotations

import os
import shlex
import sys
from typing import List, Optional

from qemu_compose.local_store import LocalStore


def _read_text(path: str) -> Optional[str]:
    try:
        with open(path, "r") as f:
            return f.read().strip()
    except Exception:
        return None


def _list_vmids(root: str) -> List[str]:
    return [d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))]


def _build_name_index(root: str) -> dict[str, str]:
    return {
        name: vmid
        for vmid in _list_vmids(root)
        if (name := _read_text(os.path.join(root, vmid, "name")))
    }


def _resolve_identifier_with_prefix(
    ident: str,
    ids: List[str],
    name_index: dict[str, str],
) -> tuple[Optional[str], List[str]]:
    if ident in ids:
        return ident, [ident]
    if ident in name_index:
        return name_index[ident], [name_index[ident]]

    id_matches = [i for i in ids if i.startswith(ident)]
    if len(id_matches) == 1:
        return id_matches[0], id_matches
    return None, id_matches


def _build_ssh_cmd(root: str, vmid: str, passthrough: List[str]) -> tuple[List[str], Optional[str]]:
    key_path = os.path.join(root, vmid, "ssh-key")
    cid_path = os.path.join(root, vmid, "cid")
    cid_val = _read_text(cid_path)

    base: List[str] = [
        "ssh",
        "-S",
        "none",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-i",
        key_path,
    ]

    destination = f"root@vsock%{cid_val}" if cid_val else "root@vsock%${cid}"
    return base + [destination] + passthrough, cid_val


def command_ssh(*, identifier: str, passthrough: Optional[List[str]] = None) -> int:
    store = LocalStore()
    instance_root = store.instance_root

    name_index = _build_name_index(instance_root)
    ids = _list_vmids(instance_root)
    vmid, candidates = _resolve_identifier_with_prefix(identifier, ids, name_index)

    if vmid is None and not candidates:
        print("Error: no VMID or NAME matches the given prefix.", file=sys.stderr)
        return 1

    if vmid is None and candidates:
        preview = ", ".join(sorted(candidates)[:8])
        more = "" if len(candidates) <= 8 else f" ... and {len(candidates)-8} more"
        print(f"Error: identifier '{identifier}' is ambiguous; matches: {preview}{more}", file=sys.stderr)
        return 1

    key_path = os.path.join(instance_root, vmid, "ssh-key")
    if not os.path.exists(key_path):
        print("Error: instance key not found: %s" % key_path, file=sys.stderr)
        return 1

    ssh_cmd, cid_val = _build_ssh_cmd(instance_root, vmid, passthrough or [])

    if not cid_val:
        print(" ".join(shlex.quote(p) for p in ssh_cmd))
        return 0

    try:
        os.execvp(ssh_cmd[0], ssh_cmd)
    except FileNotFoundError:
        print("Error: 'ssh' binary not found in PATH", file=sys.stderr)
        return 127
    except OSError as e:
        print(f"Error executing ssh: {e}", file=sys.stderr)
        return 1

    return 0
