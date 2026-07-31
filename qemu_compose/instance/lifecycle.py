from __future__ import annotations

import logging
import signal
import time
from typing import Callable, Optional

from qemu_compose.qemu.machine.machine import AbnormalShutdown

from .qemu_runner import QemuRunner


logger = logging.getLogger("qemu-compose.instance.lifecycle")


def run_vm_lifecycle(
    vm: QemuRunner,
    *,
    detached: bool = False,
    on_ready: Optional[Callable[[QemuRunner], None]] = None,
) -> int:
    """Run a prepared VM and consistently apply hooks and cleanup."""
    stop_requested = False
    old_handlers = {}

    def request_stop(_signum, _frame):
        nonlocal stop_requested
        stop_requested = True

    if detached:
        for sig in (signal.SIGTERM, signal.SIGINT):
            old_handlers[sig] = signal.signal(sig, request_stop)

    started = False
    try:
        vm.start()
        started = True
        if detached:
            if on_ready is not None:
                on_ready(vm)
            vm.interact(detached=True)
        else:
            vm.interact()

        if detached:
            vm.start_console_drain()

            while vm.is_running() and not stop_requested:
                time.sleep(0.2)

            if stop_requested and vm.is_running():
                vm.shutdown(timeout=15)
            elif not vm.is_running():
                vm.wait(timeout=None)

        vm.execute_script("after_script")
        return 0
    except KeyboardInterrupt:
        logger.warning("Keyboard interrupt, shutting down vm...")
        return 0
    finally:
        if not detached or (started and vm.is_running()):
            try:
                if vm.is_running():
                    vm.shutdown(hard=not detached)
            except AbnormalShutdown:
                logger.error("abnormal shutdown exception")
        vm.cleanup()
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)
