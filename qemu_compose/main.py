#!/usr/bin/env python3

import os
import sys
import argparse

def guess_conf_path(p:str | None):
    if p:
        return p
    for f in ["qemu-compose.yml", "qemu-compose.yaml"]:
        if os.path.exists(f):
            return f
    return None

def version(short=False):
    version = "v1.0.0"
    if short:
        print(version, file=sys.stderr)
    else:
        print("qemu-compose version %s" % version, file=sys.stderr)

def command_down(rest: list[str], config_path: str | None = None) -> int:
    import argparse as _argparse
    down_parser = _argparse.ArgumentParser(
        prog="qemu-compose down",
        add_help=True,
        description="Stop and remove the VM instance defined by qemu-compose.yml in the current directory",
    )
    down_parser.parse_args(rest)
    config_path = guess_conf_path(config_path)
    if not config_path:
        print("qemu-compose.yml not found", file=sys.stderr)
        return 1

    from .cmd.down_command import command_down as _command_down
    return _command_down(config_path=config_path, stop_running=True)


def command_rm(rest: list[str]) -> int:
    import argparse as _argparse
    rm_parser = _argparse.ArgumentParser(
        prog="qemu-compose rm",
        add_help=True,
        description="Remove a stopped VM instance",
    )
    rm_parser.add_argument(
        "identifier",
        type=str,
        help="Instance ID, unique prefix, or assigned name",
    )
    rm_parser.add_argument(
        "-f", "--force",
        action="store_true",
        default=False,
        help="Force removal of a running VM by stopping it first",
    )
    rm_args = rm_parser.parse_args(rest)

    from .cmd.down_command import command_down as _command_down
    return _command_down(identifier=rm_args.identifier, force=rm_args.force, stop_running=False)


def split_global_args(argv: list[str]) -> tuple[list[str], str | None, list[str]]:
    global_args = []
    i = 0

    while i < len(argv):
        arg = argv[i]

        if arg == "--":
            if i + 1 < len(argv):
                return global_args, argv[i + 1], argv[i + 2:]
            return global_args, None, []

        if arg in ("-h", "--help"):
            global_args.append(arg)
            return global_args, None, argv[i + 1:]

        if arg in ("-f", "--file"):
            global_args.append(arg)
            if i + 1 < len(argv):
                global_args.append(argv[i + 1])
                i += 2
                continue
            i += 1
            continue

        if arg.startswith("--file="):
            global_args.append(arg)
            i += 1
            continue

        if arg.startswith("-"):
            global_args.append(arg)
            i += 1
            continue

        return global_args, arg, argv[i + 1:]

    return global_args, None, []

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
  pull        Pull an OCI/Docker image and import it as a QEMU image
  run         Create and run a new VM from an image
  start       Start an existing VM instance by ID or name
  stop        Stop a running VM instance by ID or name
  down        Stop and remove a VM instance
  rm          Remove a VM instance
  tag         Create a tag TARGET_IMAGE that refers to SOURCE_IMAGE
  rmi         Remove an image tag or image by ID
 """,
    )
    parser.add_argument("-v", "--version", action="store_true", help="Show the qemu-compose version information")
    parser.add_argument("--short", action="store_true", default=False, help="Shows only qemu-compose's version number")
    parser.add_argument(
        "-f",
        "--file",
        type=str,
        help="Compose configuration file",
    )

    global_argv, command, rest = split_global_args(sys.argv[1:])
    args = parser.parse_args(global_argv)
    args.command = command

    if args.command == "version" or (args.version and not args.command):
        version(short=args.short)
        sys.exit(0)

    if not args.command:
        parser.print_help()
        sys.exit(1)
    elif args.command == "up":
        import argparse as _argparse
        sub_parser = _argparse.ArgumentParser(
            prog="qemu-compose up",
            add_help=True,
            description="Create and start QEMU vm",
        )
        sub_parser.add_argument(
            "--project-directory",
            type=str,
            help="Specify an alternate working directory (default: the path of the Compose file)",
        )
        sub_args = sub_parser.parse_args(rest)

        conf_path = guess_conf_path(args.file)
        if not conf_path:
            print("qemu-compose.yml not found", file=sys.stderr)
            sys.exit(1)

        from .cmd.up_command import command_up

        sys.exit(command_up(config_path=conf_path, project_directory=sub_args.project_directory))
    elif args.command == "ssh":
        import argparse as _argparse

        ssh_parser = _argparse.ArgumentParser(
            prog="qemu-compose ssh",
            add_help=True,
            description="Run ssh with instance key",
        )
        ssh_parser.add_argument(
            "identifier",
            type=str,
            nargs='?',
            help="Instance ID, unique prefix, or assigned name",
        )
        ssh_parser.add_argument(
            "command",
            nargs=_argparse.REMAINDER,
            help="Command to run on the instance (passthrough)",
        )

        ssh_args = ssh_parser.parse_args(rest)

        from .cmd.ssh_command import command_ssh

        config_path = guess_conf_path(args.file)
        sys.exit(command_ssh(identifier=ssh_args.identifier, passthrough=ssh_args.command, config_path=config_path))
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
    elif args.command == "pull":
        import argparse as _argparse
        pull_parser = _argparse.ArgumentParser(
            prog="qemu-compose pull",
            add_help=True,
            description="Pull an OCI/Docker image and import it as a QEMU qcow2 image",
        )
        pull_parser.add_argument(
            "--kernel",
            required=True,
            help="Kernel image used for direct QEMU boot",
        )
        pull_parser.add_argument(
            "--initrd",
            required=True,
            help="Initramfs image used for direct QEMU boot",
        )
        pull_parser.add_argument(
            "--platform",
            default="linux/amd64",
            help="OCI platform to pull, default: linux/amd64",
        )
        pull_parser.add_argument(
            "--disk-size",
            default="2G",
            help="Virtual size of the generated qcow2 root disk, default: 2G",
        )
        pull_parser.add_argument(
            "--boot",
            choices=["container", "systemd"],
            default="container",
            help="Boot mode for the generated image, default: container",
        )
        password_group = pull_parser.add_mutually_exclusive_group()
        password_group.add_argument(
            "--empty-root-password",
            action="store_true",
            default=None,
            help="Unlock root with an empty password for serial login (default)",
        )
        password_group.add_argument(
            "--root-password",
            help="Set root password for serial login instead of using an empty password",
        )
        pull_parser.add_argument(
            "--force",
            action="store_true",
            default=False,
            help="Replace an existing local image with the same digest",
        )
        pull_parser.add_argument(
            "--keep-workdir",
            action="store_true",
            default=False,
            help="Keep temporary import files for debugging",
        )
        pull_parser.add_argument(
            "image",
            type=str,
            help="Docker/OCI image reference, for example alpine:3.20",
        )
        pull_args = pull_parser.parse_args(rest)
        empty_root_password = pull_args.empty_root_password
        if empty_root_password is None:
            empty_root_password = pull_args.root_password is None

        from .cmd.pull_command import command_pull
        sys.exit(command_pull(
            image=pull_args.image,
            kernel=pull_args.kernel,
            initrd=pull_args.initrd,
            platform=pull_args.platform,
            disk_size=pull_args.disk_size,
            force=pull_args.force,
            keep_workdir=pull_args.keep_workdir,
            boot_mode=pull_args.boot,
            empty_root_password=empty_root_password,
            root_password=pull_args.root_password,
        ))
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
            "--network",
            choices=["user", "none"],
            help="Network mode for the VM; default is user",
        )
        run_parser.add_argument(
            "image",
            type=str,
            help="Image identifier",
        )
        run_args = run_parser.parse_args(rest)

        from .cmd.run_command import command_run
        sys.exit(command_run(
            image_hint=run_args.image,
            name=run_args.name,
            network=run_args.network,
            publish=run_args.publish,
            volumes=run_args.volumes,
        ))
    elif args.command == "start":
        import argparse as _argparse
        start_parser = _argparse.ArgumentParser(
            prog="qemu-compose start",
            add_help=True,
            description="Start an existing VM instance by ID or name",
        )
        start_parser.add_argument(
            "identifier",
            type=str,
            nargs='?',
            help="Instance ID, unique prefix, or assigned name",
        )
        start_args = start_parser.parse_args(rest)

        from .cmd.start_command import command_start
        sys.exit(command_start(identifier=start_args.identifier, config_path=args.file))
    elif args.command == "stop":
        import argparse as _argparse
        stop_parser = _argparse.ArgumentParser(
            prog="qemu-compose stop",
            add_help=True,
            description="Stop a running VM instance by ID or name",
        )
        stop_parser.add_argument(
            "identifier",
            type=str,
            help="Instance ID, unique prefix, or assigned name",
        )
        stop_args = stop_parser.parse_args(rest)

        from .cmd.stop_command import command_stop
        sys.exit(command_stop(identifier=stop_args.identifier))
    elif args.command == "down":
        sys.exit(command_down(rest, config_path=args.file))
    elif args.command == "rm":
        sys.exit(command_rm(rest))
    elif args.command == "tag":
        import argparse as _argparse
        tag_parser = _argparse.ArgumentParser(
            prog="qemu-compose tag",
            add_help=True,
            description="Create a tag TARGET_IMAGE that refers to SOURCE_IMAGE",
        )
        tag_parser.add_argument(
            "source_image",
            type=str,
            help="Source image identifier (ID or name[:tag])",
        )
        tag_parser.add_argument(
            "target_image",
            type=str,
            help="Target image name[:tag]",
        )
        tag_args = tag_parser.parse_args(rest)

        from .cmd.tag_command import command_tag
        sys.exit(command_tag(source_image=tag_args.source_image, target_image=tag_args.target_image))
    elif args.command == "rmi":
        import argparse as _argparse
        rmi_parser = _argparse.ArgumentParser(
            prog="qemu-compose rmi",
            add_help=True,
            description="Remove an image tag or image by ID",
        )
        rmi_parser.add_argument(
            "image",
            type=str,
            help="Image identifier (ID or name[:tag])",
        )
        rmi_args = rmi_parser.parse_args(rest)

        from .cmd.rmi_command import command_rmi
        sys.exit(command_rmi(image=rmi_args.image))
    else:
        parser.print_help()
        sys.exit(1)
