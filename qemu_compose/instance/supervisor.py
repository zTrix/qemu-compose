from __future__ import annotations

import argparse
import json
import os
import traceback


def _send(fd: int, payload: dict) -> None:
    data = (json.dumps(payload) + "\n").encode("utf-8")
    os.write(fd, data)


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--config", required=True)
    parser.add_argument("--project-directory")
    parser.add_argument("--ready-fd", required=True, type=int)
    args = parser.parse_args()
    # QEMUMachine launches QEMU with close_fds=False for its socket pairs.
    # Keep the one-shot parent handshake out of the QEMU process itself.
    os.set_inheritable(args.ready_fd, False)

    ready_sent = False
    instance_dir = None

    def ready(vm) -> None:
        nonlocal ready_sent, instance_dir
        instance_dir = vm.instance_dir
        supervisor_path = os.path.join(vm.instance_dir, "supervisor.pid")
        with open(supervisor_path, "w") as f:
            f.write(str(os.getpid()))
        _send(args.ready_fd, {
            "status": "ready",
            "instance_id": vm.vmid,
            "name": vm.vm_name,
            "qemu_pid": vm.get_pid(),
            "supervisor_pid": os.getpid(),
        })
        ready_sent = True

    try:
        from qemu_compose.cmd.up_command import command_up

        result = command_up(
            config_path=args.config,
            project_directory=args.project_directory,
            _detached_worker=True,
            _on_ready=ready,
        )
        if not ready_sent:
            _send(args.ready_fd, {
                "status": "error",
                "exit_code": result or 1,
                "message": "detached VM failed before becoming ready",
            })
        return result
    except BaseException as exc:
        if not ready_sent:
            _send(args.ready_fd, {
                "status": "error",
                "exit_code": 1,
                "message": str(exc) or type(exc).__name__,
                "traceback": traceback.format_exc(),
            })
        return 1
    finally:
        if instance_dir is not None:
            try:
                os.unlink(os.path.join(instance_dir, "supervisor.pid"))
            except FileNotFoundError:
                pass
        os.close(args.ready_fd)


if __name__ == "__main__":
    raise SystemExit(main())
