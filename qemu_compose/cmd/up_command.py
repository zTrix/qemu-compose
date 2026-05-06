from __future__ import annotations

import logging
import os
from typing import Optional

import yaml

from qemu_compose.instance.qemu_runner import QemuConfig, QemuRunner
from qemu_compose.local_store import LocalStore
from qemu_compose.qemu.machine.machine import AbnormalShutdown


logger = logging.getLogger("qemu-compose.cmd.up_command")


def command_up(*, config_path: str, project_directory: Optional[str] = None) -> int:
    store = LocalStore()
    cwd = os.path.normpath(os.path.abspath(os.path.dirname(config_path)))

    with open(config_path) as f:
        config_obj: dict = yaml.safe_load(f)

    config = QemuConfig.from_dict(config_obj)
    vm = QemuRunner(config, store, cwd)

    if (exit_code := vm.check_and_lock()) > 0:
        return exit_code

    config.save_to(vm.instance_dir)

    env_update = {"CWD": project_directory} if project_directory else None
    vm.prepare_env(env_update=env_update)

    if (exit_code := vm.prepare_storage()) > 0:
        return exit_code

    vm.execute_script("before_script")
    vm.setup_qemu_args()

    try:
        vm.start()
        vm.interact()
        vm.execute_script("after_script")
    except KeyboardInterrupt:
        logger.warning("Keyboard interrupt, shutting down vm...")
    finally:
        try:
            if vm is not None and vm.is_running():
                vm.shutdown(hard=True)
        except AbnormalShutdown:
            logger.error("abnormal shutdown exception")
        finally:
            if vm is not None:
                vm.cleanup()
    return 0
