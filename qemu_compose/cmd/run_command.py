from __future__ import annotations
from typing import Optional, List

import os
import sys
import logging

from qemu_compose.local_store import LocalStore
from qemu_compose.image import load_image_by_name, resolve_image
from qemu_compose.instance.qemu_runner import QemuRunner, QemuConfig
from qemu_compose.qemu.machine.machine import AbnormalShutdown

logger = logging.getLogger("qemu-compose.cmd.run_command")

def command_run(
    *,
    image_hint: str,
    name: Optional[str],
    network: Optional[str] = None,
    publish: Optional[List[str]] = None,
    volumes: Optional[List[str]] = None,
) -> int:
    store = LocalStore()

    matched_by_name = load_image_by_name(store.image_root, image_hint) is not None
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

    config_image = image_hint if matched_by_name else resolved_id
    config = QemuConfig(
        name=name,
        image=config_image,
        network=network,
        ports=list(publish or []),
        volumes=list(volumes or []),
    )
    vm = QemuRunner(config, store, cwd)

    if (exit_code := vm.check_and_lock()) > 0:
        return exit_code

    config.save_to(vm.instance_dir)

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
