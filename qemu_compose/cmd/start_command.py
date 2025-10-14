from __future__ import annotations
from typing import Optional, List, Tuple, Dict

import os
import sys
import logging

from qemu_compose.local_store import LocalStore
from qemu_compose.instance.qemu_runner import QemuRunner, QemuConfig
from qemu_compose.qemu.machine.machine import AbnormalShutdown
from qemu_compose.utils import safe_read

logger = logging.getLogger("qemu-compose.cmd.start_command")


def _list_vmids(root: str) -> List[str]:
    try:
        return [d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))]
    except FileNotFoundError:
        return []


def _build_name_index(root: str) -> Dict[str, str]:
    def name_of(vmid: str) -> Optional[str]:
        return safe_read(os.path.join(root, vmid, "name"))

    pairs: List[Tuple[str, Optional[str]]] = [
        (vmid, name_of(vmid)) for vmid in _list_vmids(root)
    ]
    return {name: vmid for (vmid, name) in pairs if name}


def _resolve_identifier(token: str, ids: List[str], name_index: Dict[str, str]) -> Tuple[Optional[str], List[str]]:
    # Exact id
    if token in ids:
        return token, [token]
    # Exact name
    if token in name_index:
        return name_index[token], [name_index[token]]

    # Unique prefix among ids
    matches = [i for i in ids if i.startswith(token)]
    if len(matches) == 1:
        return matches[0], matches
    return None, matches


def command_start(*, identifier: str = None, config_path: Optional[str] = None) -> int:
    store = LocalStore()
    instance_root = store.instance_root

    vmid = candidates = None

    if identifier:
        ids = _list_vmids(instance_root)
        name_index = _build_name_index(instance_root)

        vmid, candidates = _resolve_identifier(identifier, ids, name_index)

    if config_path:
        config = QemuConfig.load_yaml(config_path)

        if not vmid and config.name:
            vmid, candidates = _resolve_identifier(config.name, ids, name_index)
            
    if vmid is None and not candidates:
        print("Error: instance not found: %s" % identifier, file=sys.stderr, flush=True)
        return 1

    if vmid is None and candidates:
        preview = ", ".join(sorted(candidates)[:8])
        more = "" if len(candidates) <= 8 else f" ... and {len(candidates)-8} more"
        print(f"Error: identifier '{identifier}' is ambiguous; matches: {preview}{more}", file=sys.stderr, flush=True)
        return 1

    config.instance = vmid

    try:
        instance_config = QemuConfig.load_json(store.instance_dir(vmid))
        merged_dict = instance_config.to_dict() | config.to_dict()
        config = QemuConfig.from_dict(merged_dict)
    except Exception:
        logger.exception("merge config exception")

    cwd = os.getcwd()
    vm = QemuRunner(config, store, cwd)

    if (exit_code := vm.check_and_lock()) > 0:
        return exit_code

    vm.prepare_env()

    # Important: do NOT call vm.prepare_storage() for existing instances

    vm.execute_script('before_script')
    vm.setup_qemu_args()

    try:
        vm.start()
        vm.interact()
        vm.execute_script('after_script')
    except KeyboardInterrupt:
        logger.warning("Keyboard interrupt, shutting down vm...")
    finally:
        try:
            if vm is not None and vm.is_running():
                vm.shutdown(hard=True)
        except AbnormalShutdown:
            logger.error('abnormal shutdown exception')
        finally:
            if vm is not None:
                vm.cleanup()
    return 0
