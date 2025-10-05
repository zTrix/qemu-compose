from __future__ import annotations
from typing import Optional

import os
import sys
import logging

from qemu_compose.local_store import LocalStore
from qemu_compose.image import resolve_image
from qemu_compose.instance.qemu_runner import QemuRunner, QemuConfig
from qemu_compose.qemu.machine.machine import AbnormalShutdown

logger = logging.getLogger("qemu-compose.cmd.run_command")

def command_run(*, image_hint: str, name: Optional[str]) -> int:
    store = LocalStore()

    resolved_id, prefix_matches = resolve_image(store.image_root, image_hint)

    # Resolve image id: exact, unique prefix, or repo_tag
    if resolved_id is None:
        if prefix_matches:
            preview = ", ".join(sorted(set(prefix_matches))[:8])
            more = "" if len(set(prefix_matches)) <= 8 else f" ... and {len(set(prefix_matches))-8} more"
            print(f"Error: image identifier '{image_hint}' is ambiguous; matches: {preview}{more}", flush=True, file=sys.stderr)
        else:
            print(f"Error: image not found: {image_hint}", flush=True, file=sys.stderr)
        return 1

    cwd = os.getcwd()

    config = QemuConfig(name=name, image=resolved_id)
    vm = QemuRunner(config, store, cwd)

    if (exit_code := vm.check_and_lock()) > 0:
        return exit_code

    vm.prepare_env()

    if (exit_code := vm.prepare_storage()) > 0:
        return exit_code

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
