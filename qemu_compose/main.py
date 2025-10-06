#!/usr/bin/env python3
from typing import List, Optional
import os
import shlex
import sys
import yaml
import logging

from .qemu.machine.machine import AbnormalShutdown
from .local_store import LocalStore
from .instance.qemu_runner import QemuConfig, QemuRunner


logger = logging.getLogger("qemu-compose")

def run(config_path, env_update=None):
    store = LocalStore()
    cwd = os.path.normpath(os.path.abspath(os.path.dirname(config_path)))

    config_obj: dict
    with open(config_path) as f:
        config_obj = yaml.safe_load(f)

    config = QemuConfig.from_dict(config_obj)
    vm = QemuRunner(config, store, cwd)

    if (exit_code := vm.check_and_lock()) > 0:
        return exit_code

    vm.prepare_env(env_update=env_update)

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

def guess_conf_path(p:str | None):
    if p:
        return p
    for f in ["qemu-compose.yml", "qemu-compose.yaml"]:
        if os.path.exists(f):
            return f
    return None

def version(short=False):
    version = "v0.8.0"
    if short:
        print(version, file=sys.stderr)
    else:
        print("qemu-compose version %s" % version, file=sys.stderr)

def cli():
    import argparse
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Define and run QEMU VM with qemu",
        usage="qemu-compose [OPTIONS] COMMAND",
        epilog="""Commands:
  up          Create and start QEMU vm
  ssh         Run ssh with instance key
  ps          List VM instances
  version     Show the qemu-compose version information
  images      List VM images found in local store
  run         Create and run a new VM from an image
""",
    )
    parser.add_argument("-v", "--version", action="store_true", help="Show the qemu-compose version information")
    parser.add_argument("--short", action="store_true", default=False, help="Shows only qemu-compose's version number")
    parser.add_argument('command', type=str, nargs='?', help='command to run')
    parser.add_argument('-f', "--file", type=str, help='Compose configuration files')
    parser.add_argument("--project-directory", type=str, help="Specify an alternate working directory (default: the path of the Compose file)")
    # Parse only known top-level args, leave subcommand options for later
    args, rest = parser.parse_known_args()

    if args.command == "version" or args.version:
        version(short=args.short)
        sys.exit(0)

    if not args.command:
        parser.print_help()
        sys.exit(1)
    elif args.command == "up":
        env_update = None
        if args.project_directory:
            env_update = {"CWD": args.project_directory}

        conf_path = guess_conf_path(args.file)
        if not conf_path:
            print("qemu-compose.yml not found", file=sys.stderr)
            sys.exit(1)
        sys.exit(run(conf_path, env_update=env_update))
    elif args.command == "ssh":
        # Functional helpers scoped to ssh subcommand for clarity.
        def read_text(path: str) -> Optional[str]:
            try:
                with open(path, "r") as f:
                    return f.read().strip()
            except Exception:
                return None

        def build_name_index(root: str) -> dict[str, str]:
            # Map VM name -> VMID for all instances having a name file.
            def name_of(vmid: str) -> Optional[str]:
                return read_text(os.path.join(root, vmid, "name"))

            def collect() -> List[tuple[str, Optional[str]]]:
                return [
                    (d, name_of(d))
                    for d in os.listdir(root)
                    if os.path.isdir(os.path.join(root, d))
                ]

            return {name: vmid for (vmid, name) in collect() if name}

        def list_vmids(root: str) -> List[str]:
            return [d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))]

        def resolve_identifier_with_prefix(
            ident: str,
            ids: List[str],
            name_index: dict[str, str],
        ) -> tuple[Optional[str], List[str]]:
            # Exact matches take precedence
            if ident in ids:
                return ident, [ident]
            if ident in name_index:
                return name_index[ident], [name_index[ident]]

            id_matches = [i for i in ids if i.startswith(ident)]
            candidates = id_matches

            if len(candidates) == 1:
                return candidates[0], candidates
            return None, candidates

        def build_ssh_cmd(root: str, vmid: str, passthrough: List[str]) -> tuple[List[str], Optional[str]]:
            key_path = os.path.join(root, vmid, "ssh-key")
            cid_path = os.path.join(root, vmid, "cid")
            cid_val = read_text(cid_path)

            base: List[str] = [
                "ssh",
                "-S", "none",
                "-o", "StrictHostKeyChecking=no",
                "-o", "UserKnownHostsFile=/dev/null",
                "-i", key_path,
            ]

            destination = f"root@vsock%{cid_val}" if cid_val else "root@vsock%${cid}"
            cmd = base + [destination] + passthrough
            return cmd, cid_val

        # Parse raw argv after the 'ssh' token to avoid mixing with argparse.
        try:
            argv_after_ssh = sys.argv[sys.argv.index("ssh") + 1:]
        except ValueError:
            argv_after_ssh = []

        if not argv_after_ssh:
            print("Usage:  qemu-compose ssh VMID|NAME [COMMAND [ARG...]]", file=sys.stderr)
            sys.exit(1)

        store = LocalStore()
        instance_root = store.instance_root

        name_index = build_name_index(instance_root)
        ids = list_vmids(instance_root)
        # Identifier must be the first token after 'ssh'. Supports unique prefix.
        ident_token = argv_after_ssh[0]
        vmid, candidates = resolve_identifier_with_prefix(ident_token, ids, name_index)

        if vmid is None and not candidates:
            print("Error: no VMID or NAME matches the given prefix, and it must appear immediately after 'ssh'.", file=sys.stderr)
            print("Usage:  qemu-compose ssh VMID|NAME [COMMAND [ARG...]]", file=sys.stderr)
            sys.exit(1)

        if vmid is None and candidates:
            preview = ", ".join(sorted(candidates)[:8])
            more = "" if len(candidates) <= 8 else f" ... and {len(candidates)-8} more"
            print(f"Error: identifier '{ident_token}' is ambiguous; matches: {preview}{more}", file=sys.stderr)
            sys.exit(1)

        key_path = os.path.join(instance_root, vmid, "ssh-key")
        if not os.path.exists(key_path):
            print("Error: instance key not found: %s" % key_path, file=sys.stderr)
            sys.exit(1)

        # Only passthrough args after the identifier are supported.
        passthrough = argv_after_ssh[1:]
        ssh_cmd, cid_val = build_ssh_cmd(instance_root, vmid, passthrough)

        if not cid_val:
            printable = " ".join(shlex.quote(p) for p in ssh_cmd)
            print(printable)
            sys.exit(0)

        try:
            os.execvp(ssh_cmd[0], ssh_cmd)
        except FileNotFoundError:
            print("Error: 'ssh' binary not found in PATH", file=sys.stderr)
            sys.exit(127)
        except OSError as e:
            print(f"Error executing ssh: {e}", file=sys.stderr)
            sys.exit(1)
    elif args.command == "ps":
        import argparse as _argparse
        # Sub-parser for `ps` options to keep scope minimal
        ps_parser = _argparse.ArgumentParser(
            prog="qemu-compose ps",
            add_help=True,
            description="List qemu-compose VM instances",
        )
        ps_parser.add_argument(
            "-a", "--all",
            action="store_true",
            help="Show all the containers, default is only running vm instance",
        )
        # Parse only the args following the "ps" command
        ps_args = ps_parser.parse_args(rest)

        from .cmd.ps_command import command_ps

        sys.exit(command_ps(show_all=ps_args.all))
    elif args.command == "images":
        from .cmd.images_command import command_images
        sys.exit(command_images())
    elif args.command == "run":
        import argparse as _argparse
        run_parser = _argparse.ArgumentParser(
            prog="qemu-compose run",
            add_help=True,
            description="Create an instance overlay from an image and print QEMU command",
        )
        run_parser.add_argument(
            "--name",
            required=False,
            help="Instance name; auto-generated if omitted",
        )
        run_parser.add_argument(
            "-p", "--publish",
            dest="publish",
            action="append",
            default=[],
            help="Publish a port, format: host_ip:host_port:vm_port[/proto] or host_port:vm_port[/proto]; repeatable",
        )
        run_parser.add_argument(
            "-v", "--volume",
            dest="volumes",
            action="append",
            default=[],
            help="Bind-mount a host directory into the guest using virtiofs; format: src:dst[:ro]; repeatable",
        )
        run_parser.add_argument(
            "image",
            type=str,
            help="Image identifier",
        )
        run_args = run_parser.parse_args(rest)

        from .cmd.run_command import command_run
        sys.exit(command_run(image_hint=run_args.image, name=run_args.name, publish=run_args.publish, volumes=run_args.volumes))
    else:
        parser.print_help()
        sys.exit(1)
