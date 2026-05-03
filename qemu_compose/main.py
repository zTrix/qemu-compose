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
    version = "v0.9.0"
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
  start       Start an existing VM instance by ID or name
  down        Stop and remove a VM instance
  tag         Create a tag TARGET_IMAGE that refers to SOURCE_IMAGE
 """,
    )
    parser.add_argument("-v", "--version", action="store_true", help="Show the qemu-compose version information")
    parser.add_argument("--short", action="store_true", default=False, help="Shows only qemu-compose's version number")
    parser.add_argument('command', type=str, nargs='?', help='command to run')
    
    # Check for subcommand help before parse_known_args
    help_flag = None
    if '--help' in sys.argv:
        help_flag = '--help'
    elif '-h' in sys.argv:
        help_flag = '-h'
    
    if help_flag:
        # Remove from sys.argv temporarily to let subcommand parser handle it
        sys.argv.remove(help_flag)
    
    # Parse only known top-level args, leave subcommand options for later
    args, rest = parser.parse_known_args()
    
    # Restore help flag for subcommand parser
    if help_flag:
        rest.append(help_flag)

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
            "-f", "--file",
            type=str,
            help="Compose configuration files",
        )
        sub_parser.add_argument(
            "--project-directory",
            type=str,
            help="Specify an alternate working directory (default: the path of the Compose file)",
        )
        sub_args = sub_parser.parse_args(rest)

        conf_path = guess_conf_path(sub_args.file)
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
            help="Instance ID, unique prefix, or assigned name",
        )
        ssh_parser.add_argument(
            "command",
            nargs=_argparse.REMAINDER,
            help="Command to run on the instance (passthrough)",
        )

        ssh_args = ssh_parser.parse_args(rest)

        from .cmd.ssh_command import command_ssh

        sys.exit(command_ssh(identifier=ssh_args.identifier, passthrough=ssh_args.command))
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
        start_parser.add_argument(
            "-f", "--file",
            type=str,
            required=False,
            help="Compose configuration file to parse for QEMU args",
        )
        start_args = start_parser.parse_args(rest)

        from .cmd.start_command import command_start
        sys.exit(command_start(identifier=start_args.identifier, config_path=start_args.file))
    elif args.command == "down":
        import argparse as _argparse
        down_parser = _argparse.ArgumentParser(
            prog="qemu-compose down",
            add_help=True,
            description="Stop and remove a VM instance",
        )
        down_parser.add_argument(
            "identifier",
            type=str,
            nargs='?',
            help="Instance ID, unique prefix, or assigned name",
        )
        down_parser.add_argument(
            "-f", "--file",
            type=str,
            required=False,
            help="Compose configuration file to parse for instance name",
        )
        down_parser.add_argument(
            "--force",
            action="store_true",
            default=False,
            help="Force removal without confirmation",
        )
        down_args = down_parser.parse_args(rest)

        config_path = None
        if down_args.file:
            config_path = down_args.file
        else:
            config_path = guess_conf_path(None)

        from .cmd.down_command import command_down
        sys.exit(command_down(identifier=down_args.identifier, force=down_args.force, config_path=config_path))
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
    else:
        parser.print_help()
        sys.exit(1)
