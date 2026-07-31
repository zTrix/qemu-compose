from __future__ import annotations

import logging
import json
import os
import subprocess
import sys
from typing import Callable, Optional

import yaml

from qemu_compose.cmd.start_command import _build_name_index, command_start
from qemu_compose.instance.qemu_runner import QemuConfig, QemuRunner
from qemu_compose.local_store import LocalStore
from qemu_compose.instance.lifecycle import run_vm_lifecycle


logger = logging.getLogger("qemu-compose.cmd.up_command")


def _start_detached(config_path: str, project_directory: Optional[str]) -> int:
    read_fd, write_fd = os.pipe()
    command = [
        sys.executable,
        "-m",
        "qemu_compose.instance.supervisor",
        "--config",
        os.path.abspath(config_path),
        "--ready-fd",
        str(write_fd),
    ]
    if project_directory:
        command.extend(["--project-directory", project_directory])

    try:
        subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            pass_fds=(write_fd,),
            start_new_session=True,
        )
    except OSError as exc:
        os.close(read_fd)
        os.close(write_fd)
        print(f"Error: failed to start detached supervisor: {exc}", file=sys.stderr)
        return 1

    os.close(write_fd)
    with os.fdopen(read_fd, "r", encoding="utf-8") as ready_pipe:
        line = ready_pipe.readline()
    if not line:
        print("Error: detached supervisor exited before reporting readiness", file=sys.stderr)
        return 1

    try:
        result = json.loads(line)
    except (json.JSONDecodeError, TypeError):
        print("Error: detached supervisor returned an invalid readiness response", file=sys.stderr)
        return 1
    if result.get("status") != "ready":
        print(f"Error: {result.get('message', 'detached VM failed to start')}", file=sys.stderr)
        return int(result.get("exit_code", 1))

    label = result["instance_id"]
    if result.get("name"):
        label = f"{result['name']} ({label})"
    print(f"Started {label} in detached mode")
    return 0


def command_up(
    *,
    config_path: str,
    project_directory: Optional[str] = None,
    detach: bool = False,
    _detached_worker: bool = False,
    _on_ready: Optional[Callable[[QemuRunner], None]] = None,
) -> int:
    if detach and not _detached_worker:
        return _start_detached(config_path, project_directory)

    store = LocalStore()
    cwd = os.path.normpath(os.path.abspath(os.path.dirname(config_path)))

    with open(config_path) as f:
        config_obj: dict = yaml.safe_load(f)

    config = QemuConfig.from_dict(config_obj)

    if config.name and config.name in _build_name_index(store.instance_root):
        env_update = {"CWD": project_directory} if project_directory else None
        return command_start(
            identifier=config.name,
            config_path=config_path,
            cwd=cwd,
            env_update=env_update,
            _detached_worker=_detached_worker,
            _on_ready=_on_ready,
        )

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

    return run_vm_lifecycle(
        vm,
        detached=_detached_worker,
        on_ready=_on_ready,
    )
