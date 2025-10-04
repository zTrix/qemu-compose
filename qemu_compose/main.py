#!/usr/bin/env python3
from typing import List, Optional, Set
import os
import shlex
import base64
import re
import sys
import yaml
import logging
import shutil
import threading
import tty
import subprocess
import signal
import fcntl
from functools import partial
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

from .qemu.machine import QEMUMachine
from .qemu.machine.machine import AbnormalShutdown
from .jsonlisp import default_env, interp
from .local_store import LocalStore
from .vsock import get_available_guest_cid

from .zio import zio, write_debug, select_ignoring_useless_signal, ttyraw
from .utils.names_gen import generate_unique_name
from .utils.hostnames import to_valid_hostname


logger = logging.getLogger("qemu-compose")

class HttpServer:
    def __init__(self, listen:str, port:int, root:str):
        self.listen = listen
        self.port = port
        self.root = root

    def start(self):
        http_handler = partial(SimpleHTTPRequestHandler, directory=self.root)
        server = ThreadingHTTPServer((self.listen, self.port), http_handler)
        server_thread = threading.Thread(target=server.serve_forever)
        server_thread.daemon = True
        server_thread.start()

class StreamWrapper:
    def __init__(self, obj):
        self.obj = obj

    def __getattr__(self, name):
        return getattr(self.obj, name)

    def write(self, s):
        if isinstance(s, str):
            s = s.encode()
        self.obj.write(s)

class Terminal(object):
    def __init__(self, fd, log_path=None):
        self.fd = fd

        if isinstance(log_path, str):
            self.debug_file = open(log_path, "wb") if log_path else None
        else:
            self.debug_file = log_path

        self.io = zio(fd, print_write=False, logfile=sys.stdout, debug=self.debug_file, timeout=3600)

        self.term_feed_running = False
        self.term_feed_drain_thread = None

        if not os.isatty(0):
            raise Exception('qemu-compose.Terminal must run in a UNIX 98 style pty/tty')
        else:
            signal.signal(signal.SIGWINCH, self.handle_resize)

    def handle_resize(self, signum, frame):
        height, width = os.get_terminal_size(0)
        logger.info("try set terminal window size to %dx%d" % (width, height))
        # TODO: use qmp to set console window size

    def term_feed_loop(self):
        logger.info('Terminal.term_feed_loop started...')
        while self.term_feed_running:
            r, _, _ = select_ignoring_useless_signal([0], [], [], 0.2)

            if 0 in r:
                data = os.read(0, 1024)
                if data:
                    logger.info('Terminal.term_feed_loop received(%d) -> %s' % (len(data), data))
                    self.io.write(data)

        logger.info('Terminal.term_feed_loop finished.')

    def run_batch(self, cmds:List, env_variables=None):
        if not isinstance(cmds, list):
            raise ValueError("cmds must be a list")
        
        current_tty_mode = tty.tcgetattr(0)[:]
        ttyraw(0)

        try:
            self.term_feed_running = True
            self.term_feed_drain_thread = threading.Thread(target=self.term_feed_loop)
            self.term_feed_drain_thread.daemon = True
            self.term_feed_drain_thread.start()
            
            io = self.io

            if self.debug_file:
                write_debug(self.debug_file, b'run_batch: cmds = %r' % cmds)

            transpiled_cmds = ['begin'] + cmds

            env = default_env()

            env['read_until'] = io.read_until
            env['write'] = io.write
            env['writeline'] = io.writeline
            env['wait'] = io.read_until_timeout
            env['RegExp'] = lambda x: re.compile(x.encode())
            env['interact'] = self.interact

            if env_variables:
                env.update(env_variables)

            interp(transpiled_cmds, env)

        finally:
            tty.tcsetattr(0, tty.TCSAFLUSH, current_tty_mode)

    def interact(self, buffered:Optional[bytes]=None, raw_mode=False):

        self.term_feed_running = False
        if self.term_feed_drain_thread is not None:
            self.term_feed_drain_thread.join()

        self.io.interactive(raw_mode=raw_mode, buffered=buffered)

def extract_format_or_default(mapping:dict, key:str, env:dict, default=None):
    value = mapping.get(key) if mapping else key
    if value:
        # FIXME: format has security issues
        return str(value).format(**env)
    return default




def run(config_path, log_path=None, env_update=None):
    cid = get_available_guest_cid(1000)
    if cid is None:
        raise Exception("no available guest cid found, please make sure vhost_vsock module loaded")

    store = LocalStore()
    vmid = store.new_random_vmid()
    instance_dir = store.instance_dir(vmid)
    lock_fd: Optional[int] = None
    
    if True:
        # Acquire exclusive lock on instance_dir before any launch
        #  lock early to prevent prune procedure removing contents before qemu starts
        flags = os.O_RDONLY
        if hasattr(os, 'O_DIRECTORY'):
            flags |= os.O_DIRECTORY
        lock_fd = os.open(instance_dir, flags)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)

    if log_path:
        debug_file = open(log_path, "wb")
        logging.basicConfig(level=logging.DEBUG, stream=StreamWrapper(debug_file))
    else:
        debug_file = None

    config: dict
    with open(config_path) as f:
        config = yaml.safe_load(f)

    binary = config.get('binary', shutil.which('qemu-system-x86_64'))
    if not binary:
        raise Exception('qemu binary not found')
    
    name = config.get('name')

    # Collect existing VM names for duplicate detection and auto-generation
    existing_names = {}
    for entry in os.listdir(store.instance_root):
        entry_path = os.path.join(store.instance_root, entry)
        if not os.path.isdir(entry_path):
            continue
        name_path = os.path.join(entry_path, "name")
        if not os.path.exists(name_path):
            continue
        try:
            with open(name_path, "r") as nf:
                existing_name = nf.read().strip()
            if existing_name:
                existing_names[existing_name] = entry
        except OSError:
            # Ignore unreadable name files
            pass

    # Check duplicate VM name after locking instance_dir but before launch
    if name:
        if name in existing_names:
            print(
                f"Error: creating vm storage: the vm name {name} is already in use by {existing_names.get(name)}. You have to remove that instance to be able to reuse that name: that name is already in use",
                file=sys.stderr,
            )
            # the same as podman
            return 125
    else:
        name = generate_unique_name(existing_names)

    cwd = os.path.normpath(os.path.abspath(os.path.dirname(config_path)))
    term_size = os.get_terminal_size()

    env = {
        'CWD': cwd,
        'GATEWAY_IP': '10.0.2.2',   # qemu user network default gateway ip
        'TERM_ROWS': term_size.lines,
        'TERM_COLS': term_size.columns,
        'ID': vmid,
        'STORAGE_PATH': store.data_dir,
        'IMAGE_ROOT': store.image_root,
        'INSTANCE_ROOT': store.instance_root,
    }

    if config.get('env'):
        for k in config.get('env'):
            env[k] = config.get('env')[k]

    logger.info("change directory to %s" % env['CWD'])
    os.chdir(env['CWD'])
    
    http_port = None
    if config.get('http_serve'):
        http_serve_config:dict = config.get('http_serve')
        http_listen = extract_format_or_default(http_serve_config, 'listen', env, default='0.0.0.0')
        http_port = int(extract_format_or_default(http_serve_config, 'port', env, default=8888))
        http_root = extract_format_or_default(http_serve_config, 'root', env, default=env['CWD'])

        http_server = HttpServer(http_listen, http_port, http_root)
        http_server.start()
        logger.info('HTTP server started on %s:%d, serving %s' % (http_listen, http_port, http_root))

    if http_port is not None:
        env['HTTP_PORT'] = http_port
        access_ip = extract_format_or_default(config.get('http_serve'), 'access_ip', env, default=env['GATEWAY_IP']) if config.get('http_serve') else env['GATEWAY_IP']
        env['HTTP_HOST'] = access_ip

    if env_update:
        env.update(env_update)

    if config.get('before_script'):
        for line in config.get('before_script'):
            command = extract_format_or_default(None, line, env)
            if command:
                subprocess.run(command.strip(), shell=True, check=True)

    default_args = {
        'cpu': 'max',
        'machine': 'type=q35,hpet=off',
        'accel': 'kvm',
        'm': '1G',
        'smp': str(os.cpu_count()),
    }

    for block in config.get('args'):
        for key in block:
            val = extract_format_or_default(block, key, env)
            if key in default_args:
                default_args[key] = val

    args = []
    for key in default_args:
        args.append('-' + key)
        args.append(default_args[key])

    for block in config.get('args'):
        for key in block:
            val = extract_format_or_default(block, key, env)
            if key in default_args:
                continue
            args.append('-' + key)
            if val is not None:
                args.append(val)

    hostname = None
    if name:
        args.append('-name')
        args.append(name)
        hostname = to_valid_hostname(name)

    if hostname:
        # https://systemd.io/CREDENTIALS/
        args.append('-smbios')
        args.append('type=11,value=io.systemd.credential:system.hostname=' + hostname)

    # add user network
    args.append('-netdev')
    # https://man.archlinux.org/man/qemu.1.en#hostname=name
    args.append('user,id=user.qemu-compose%s' % (',hostname=' + hostname if hostname else '',))
    args.append('-device')
    args.append('virtio-net,netdev=user.qemu-compose')

    if cid:
        args.append("-device")
        args.append("vhost-vsock-pci,id=vhost-vsock-pci0,guest-cid=%d" % cid)

    store.prepare_ssh_key(vmid)

    with open(store.instance_ssh_key_pub_path(vmid), 'rb') as pf:
        pub_bytes = pf.read()

    pub_b64 = base64.b64encode(pub_bytes).decode('ascii')
    args.append('-smbios')
    args.append(f'type=11,value=io.systemd.credential.binary:ssh.authorized_keys.root={pub_b64}')

    vm = QEMUMachine(binary, args=args, name=name)
    vm.add_monitor_null()
    vm.set_qmp_monitor(True)
    vm.set_console(console_chardev='socket', device_type='isa-serial')

    try:
        vm.launch()

        term = Terminal(vm.console_file, debug_file)

        try:
            pid = vm.get_pid()
        except Exception:
            pid = None
        try:
            with open(os.path.join(instance_dir, "qemu.pid"), "w") as f:
                f.write("%s" % (str(pid) if pid is not None else ""))
            with open(os.path.join(instance_dir, "cid"), "w") as f:
                f.write(str(cid))
            with open(os.path.join(instance_dir, "name"), "w") as f:
                f.write(str(name) if name is not None else "")
            with open(os.path.join(instance_dir, "instance-id"), "w") as f:
                f.write(str(vmid))
        except Exception as e:
            logger.warning("failed to write instance metadata: %s", e)

        boot_commands = config.get('boot_commands')
        if boot_commands:
            term.run_batch(boot_commands, env_variables=env)
        else:
            term.interact(raw_mode=True)

        if config.get('after_script'):
            for line in config.get('after_script'):
                command = extract_format_or_default(None, line, env)
                if command:
                    subprocess.run(command.strip(), shell=True, check=True)

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
                vm._load_io_log()
                logger.info('vm.process_io_log = %r' % (vm.get_log(), ))
            try:
                if lock_fd is not None:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                    os.close(lock_fd)
            except Exception as e:
                logger.warning("failed to unlock instance dir: %s", e)
    return 0

def guess_conf_path(p:str | None):
    if p:
        return p
    for f in ["qemu-compose.yml", "qemu-compose.yaml"]:
        if os.path.exists(f):
            return f
    return None

def version(short=False):
    version = "v0.6.2"
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
  version     Show the qemu-compose version information
""",
    )
    parser.add_argument("-v", "--version", action="store_true", help="Show the qemu-compose version information")
    parser.add_argument("--short", action="store_true", default=False, help="Shows only qemu-compose's version number")
    parser.add_argument('command', type=str, nargs='?', help='command to run')
    parser.add_argument('-f', "--file", type=str, help='Compose configuration files')
    parser.add_argument("--log-path", type=str, help="detailed log path")
    parser.add_argument("--project-directory", type=str, help="Specify an alternate working directory (default: the path of the Compose file)")
    # Accept unknown args so we can forward them to subcommands like `ssh`
    args, _ = parser.parse_known_args()

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
        sys.exit(run(conf_path, log_path=args.log_path, env_update=env_update))
    elif args.command == "ssh":
        # Implement: qemu-compose ssh [OPTIONS] VMID COMMAND [ARG...]
        # Find tokens after 'ssh' and detect VMID as the first token that
        # matches an existing instance id. Everything else is passed to ssh.
        # Use the raw argv slice after the literal 'ssh' to avoid
        # argparse consuming options that belong to ssh (e.g. '-f').
        try:
            argv_after_ssh = sys.argv[sys.argv.index("ssh") + 1:]
        except ValueError:
            argv_after_ssh = []

        if not argv_after_ssh:
            print("Usage:  qemu-compose ssh [OPTIONS] VMID COMMAND [ARG...]", file=sys.stderr)
            sys.exit(1)

        store = LocalStore()
        instance_root = store.instance_root

        vmid = None
        vmid_index = None
        for i, tok in enumerate(argv_after_ssh):
            # Treat the first token that corresponds to an existing instance id as VMID
            inst_dir = os.path.join(instance_root, tok)
            if os.path.isdir(inst_dir):
                vmid = tok
                vmid_index = i
                break

        if not vmid:
            print("Error: VMID not found. Existing instances live under %s" % instance_root, file=sys.stderr)
            print("Usage:  qemu-compose ssh [OPTIONS] VMID COMMAND [ARG...]", file=sys.stderr)
            sys.exit(1)

        key_path = os.path.join(instance_root, vmid, "ssh-key")
        if not os.path.exists(key_path):
            print("Error: instance key not found: %s" % key_path, file=sys.stderr)
            sys.exit(1)

        # Defaults come first; user-specified options can override them later
        ssh_cmd: List[str] = [
            "ssh",
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-i", key_path,
        ]

        # Append default destination using vsock CID
        cid_path = os.path.join(instance_root, vmid, "cid")
        cid_val: str | None = None
        try:
            if os.path.exists(cid_path):
                with open(cid_path, "r") as cf:
                    cid_val = cf.read().strip()
        except Exception:
            cid_val = None

        if cid_val:
            ssh_cmd.append(f"root@vsock%{cid_val}")
        else:
            # Fallback to a placeholder if cid is unknown
            ssh_cmd.append("root@vsock%${cid}")

        # Pass-through args: everything except the VMID token
        passthrough: List[str] = argv_after_ssh[:vmid_index] + argv_after_ssh[vmid_index + 1:]
        if not passthrough:
            # No destination/command provided; print the constructed ssh command
            # so users can see defaults and compose their own invocation.
            printable = " ".join(shlex.quote(p) for p in ssh_cmd)
            print(printable)
            sys.exit(0)

        ssh_cmd.extend(passthrough)

        try:
            # Replace current process to preserve exit code and TTY behavior
            os.execvp(ssh_cmd[0], ssh_cmd)
        except FileNotFoundError:
            print("Error: 'ssh' binary not found in PATH", file=sys.stderr)
            sys.exit(127)
        except OSError as e:
            print(f"Error executing ssh: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        parser.print_help()
        sys.exit(1)
