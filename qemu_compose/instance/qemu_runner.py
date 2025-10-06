from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field
import shutil
import os
import sys
import base64
import fcntl
import logging
import subprocess

from qemu_compose.qemu.machine import QEMUMachine
from qemu_compose.local_store import LocalStore
from qemu_compose.instance import prepare_ssh_key
from qemu_compose.utils.hostnames import to_valid_hostname
from qemu_compose.utils.vsock import get_available_guest_cid
from qemu_compose.utils import StreamWrapper
from qemu_compose.image import ImageManifest, load_image_by_id, load_image_by_name, DiskSpec

from .name import check_and_get_name
from .http import HttpServer
from .terminal import Terminal
from . import new_random_vmid


logger = logging.getLogger("qemu-compose.instance.qemu_runner")


def create_overlay(base_path: str, base_format: str, overlay_path: str) -> int:
    cmd = [
        "qemu-img", "create",
        "-b", base_path,
        "-F", base_format,
        "-f", "qcow2",
        overlay_path,
    ]
    try:
        res = subprocess.run(cmd, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            print(res.stderr, file=sys.stderr, flush=True)
        return res.returncode
    except FileNotFoundError:
        print("Error: 'qemu-img' binary not found in PATH", file=sys.stderr, flush=True)
        return 127

def drive_param_for(overlay_path: str, spec: DiskSpec) -> str:
    # Build a '-drive' parameter string combining manifest opts with required pieces.
    opts = []
    # Always use qcow2 overlay per requirement
    opts.append(f"file={overlay_path}")
    if spec.format:
        opts.append("format=" + spec.format)
    if spec.opts:
        opts.append(spec.opts)
    return ",".join(opts)


def extract_format_or_default(mapping: Optional[dict], key: str, env: dict, default=None):
    value = mapping.get(key) if mapping else key
    if value:
        # FIXME: format has security issues
        return str(value).format(**env)
    return default


@dataclass(frozen=True)
class HttpServeConfig:
    listen: str
    port: int
    root: str
    access_ip: Optional[str] = None

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "HttpServeConfig":
        return cls(
            listen=d.get("listen", "127.0.0.1"),
            port=int(d.get("port", 8888)),
            root=d.get("root", ""),
            access_ip=d.get("access_ip")
        )

@dataclass(frozen=True)
class QemuConfig:
    name: Optional[str] = None
    binary: Optional[str] = None
    network: Optional[str] = None     # could be "none", "user", etc, default set to "user" when left None
    image: Optional[str] = None
    env: Dict[str, str] = field(default_factory=dict)
    qemu_args: List[Dict[str, str]] = field(default_factory=list)
    ports: List[str] = field(default_factory=list)
    volumes: List[str] = field(default_factory=list)
    boot_commands: List[Dict[str, Any]] = field(default_factory=list)
    before_script: List[str] = field(default_factory=list)
    after_script: List[str] = field(default_factory=list)
    http_serve: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "QemuConfig":
        return cls(
            name=d.get("name"),
            binary=d.get("binary"),
            network=d.get("network"),
            image=d.get("image"),
            env=d.get("env", []),
            qemu_args=d.get("qemu_args", []),
            ports=d.get("ports", []),
            volumes=d.get("volumes", []),
            boot_commands=d.get("boot_commands", []),
            before_script=d.get("before_script", []),
            after_script=d.get("after_script", []),
            http_serve=d.get("http_serve", {}),
        )


class QemuRunner(QEMUMachine):
    def __init__(self, config: QemuConfig, store: LocalStore, cwd: str):
        self.config = config
        self.store = store
        self.cwd = cwd

        self.vm_name: Optional[str] = None
        self.lock_fd: Optional[int] = None
        self.cid: Optional[int] = None
        self.vmid: Optional[str] = None
        self.log_file = None
        self.image_manifest: Optional[ImageManifest] = None
        self.storage_overlays: List[Tuple[str, DiskSpec]] = []
        self.virtiofs_children: List[subprocess.Popen] = []

        if config.binary:
            binary = config.binary
        else:
            binary = shutil.which('qemu-system-x86_64')

        if not binary:
            raise FileNotFoundError("QEMU binary not found")
        
        super().__init__(binary=binary)

        self.add_monitor_null()
        self.set_qmp_monitor(True)
        self.set_console(console_chardev='socket', device_type='isa-serial')

    @property
    def instance_dir(self) -> str:
        if self.vmid is None:
            raise ValueError("vmid is not set")
        return self.store.instance_dir(self.vmid)

    def check_and_lock(self) -> int:
        if self.config.image is not None:
            manifest = load_image_by_id(self.store.image_root, self.config.image)

            if manifest is None:
                manifest = load_image_by_name(self.store.image_root, self.config.image)

            if manifest is None:
                print(f"Image '{self.config.image}' not found in local store", file=sys.stderr)
                return 126
            self.image_manifest = manifest

        try:
            self.vm_name = check_and_get_name(self.store.instance_root, self.config.name)
        except ValueError as e:
            print(str(e), file=sys.stderr)
            return 125

        self.cid = get_available_guest_cid(1000)
        if self.cid is None:
            print("no available guest cid found, please make sure vhost_vsock module loaded", file=sys.stderr)
            return 124

        self.vmid = new_random_vmid(self.store.instance_root)

        log_path = os.path.join(self.store.instance_dir(self.vmid), "qemu-compose.log")
        self.log_file = open(log_path, "wb")
        logging.basicConfig(level=logging.INFO, stream=StreamWrapper(self.log_file))

        try:
            instance_dir = self.store.instance_dir(self.vmid)
        except OSError as e:
            print(f"Failed to create instance dir {self.vmid}: {e}", file=sys.stderr)
            return 123
        
        try:
            # Acquire exclusive lock on instance_dir before any launch
            # lock early to prevent prune procedure removing contents before qemu starts
            flags = os.O_RDONLY
            if hasattr(os, 'O_DIRECTORY'):
                flags |= os.O_DIRECTORY
            self.lock_fd = os.open(instance_dir, flags)
            fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(f"Failed to lock instance dir {instance_dir}", file=sys.stderr)
            return 122
        
        return 0

    def prepare_env(self, env_update: Optional[Dict[str, str]] = None):
        term_size = os.get_terminal_size()

        env = {
            'CWD': self.cwd,
            'GATEWAY_IP': '10.0.2.2',   # qemu user network default gateway ip
            'TERM_ROWS': term_size.lines,
            'TERM_COLS': term_size.columns,
            'ID': self.vmid,
            'STORAGE_PATH': self.store.data_dir,
            'IMAGE_ROOT': self.store.image_root,
            'INSTANCE_ROOT': self.store.instance_root,
            'INSTANCE_DIR': self.instance_dir,
        }

        if self.config.image:
            env['IMAGE_TAG'] = self.config.image

        if self.image_manifest is not None:
            env["IMAGE_DIR"] = os.path.join(self.store.image_root, self.image_manifest.id)
            env["IMAGE_ID"] = self.image_manifest.id

        if self.config.env:
            for k in self.config.env:
                env[k] = self.config.env[k]

        logger.info("change directory to %s" % env['CWD'])
        os.chdir(env['CWD'])
        
        http_port = None
        if self.config.http_serve:
            http_serve_config: dict = self.config.http_serve
            http_listen = extract_format_or_default(http_serve_config, 'listen', env, default='0.0.0.0')
            http_port = int(extract_format_or_default(http_serve_config, 'port', env, default=8888))
            http_root = extract_format_or_default(http_serve_config, 'root', env, default=env['CWD'])

            http_server = HttpServer(http_listen, http_port, http_root)
            http_server.start()
            logger.info('HTTP server started on %s:%d, serving %s' % (http_listen, http_port, http_root))

        if http_port is not None:
            env['HTTP_PORT'] = http_port
            access_ip = extract_format_or_default(self.config.http_serve, 'access_ip', env, default=env['GATEWAY_IP']) if self.config.http_serve else env['GATEWAY_IP']
            env['HTTP_HOST'] = access_ip

        if env_update:
            env.update(env_update)

        self.env = env

    def prepare_storage(self):
        if self.image_manifest is None:
            return 0
        
        image_dir = os.path.join(self.store.image_root, self.image_manifest.id)

        self.storage_overlays = []

        for disk_spec in self.image_manifest.disks:
            base_disk_path = os.path.join(image_dir, disk_spec.filename)
            overlay_path = os.path.join(self.instance_dir, disk_spec.filename)
            rc = create_overlay(base_disk_path, disk_spec.format, overlay_path)
            if rc != 0:
                print(f"Failed to create overlay for disk {disk_spec.filename}", file=sys.stderr, flush=True)
                return rc
            self.storage_overlays.append((overlay_path, disk_spec))

        return 0

    def execute_script(self, script_key: str):
        script_target = getattr(self.config, script_key, None)

        if script_target:
            for line in script_target:
                command = extract_format_or_default(None, line, self.env)
                if command:
                    subprocess.run(command.strip(), shell=True, check=True)

    def setup_qemu_args(self):
        # the very default args
        default_args = {
            'cpu': 'max',
            'machine': 'type=q35,hpet=off',
            'accel': 'kvm',
            'm': '1G',
            'smp': str(os.cpu_count()),
        }

        # image provided args override our defaults
        if self.image_manifest is not None and self.image_manifest.qemu_args:
            for a in self.image_manifest.qemu_args:
                if not a.startswith('-'):
                    continue
                if a[1:] in default_args:
                    default_args.pop(a[1:], None)

        # user provided args override image defaults
        for block in self.config.qemu_args:
            for key in block:
                val = extract_format_or_default(block, key, self.env)
                if key in default_args and isinstance(val, str):
                    default_args[key] = val

        args = []

        # vm name first
        if self.vm_name:
            args.append('-name')
            args.append(self.vm_name)

        # then our safe defaults
        for key in default_args:
            args.append('-' + key)
            args.append(default_args[key])

        # then network setup

        hostname = None
        if self.vm_name:
            hostname = to_valid_hostname(self.vm_name)

        if hostname:
            # https://systemd.io/CREDENTIALS/
            args.append('-smbios')
            args.append('type=11,value=io.systemd.credential:system.hostname=' + hostname)

        def parse_port_spec(spec: str) -> Optional[Tuple[str, str, str, str]]:
            # Support forms:
            #  - host_ip:host_port:vm_port
            #  - host_port:vm_port
            # Each of the above may be suffixed with "/tcp" or "/udp"
            proto = 'tcp'
            body, sep, suffix = spec.partition('/')
            if sep:
                proto = suffix.strip().lower() or 'tcp'
                if proto not in ('tcp', 'udp'):
                    proto = 'tcp'
            parts = [p.strip() for p in body.split(':')]
            if len(parts) == 3:
                return proto, parts[0], parts[1], parts[2]
            if len(parts) == 2:
                return proto, '', parts[0], parts[1]
            return None

        def format_hostfwd(item: Tuple[str, str, str, str]) -> str:
            proto, host_ip, host_port, vm_port = item
            return f",hostfwd={proto}:{host_ip}:{host_port}-:{vm_port}"

        def hostfwd_segments(ports: List[str]) -> str:
            return ''.join(
                map(
                    format_hostfwd,
                    filter(None, map(parse_port_spec, ports))
                )
            )

        # Bind-mount style volumes implemented via virtio-fs. Spec format:
        #   src:dst[:ro]
        # Examples:
        #   /host/path:/mnt/data
        #   /host/path:/mnt/readonly:ro
        def parse_volume_spec(spec: str) -> Optional[Tuple[str, str, bool]]:
            parts = [p.strip() for p in spec.split(':')]
            if len(parts) < 2:
                return None
            src = parts[0]
            dst = parts[1]
            ro = any(p.lower() == 'ro' for p in parts[2:]) if len(parts) > 2 else False
            if not src or not dst:
                return None
            return src, dst, ro

        def volume_tag_for(dst: str, idx: int) -> str:
            base = os.path.basename(dst) or f"vol{idx}"
            sanitized = ''.join(ch if ch.isalnum() or ch in ('-', '_') else '_' for ch in base)
            return f"{sanitized}-{idx}"

        def start_virtiofsd(shared_dir: str, socket_path: str, read_only: bool) -> Optional[subprocess.Popen]:
            virtiofsd = shutil.which('virtiofsd')
            if virtiofsd is None:
                logger.warning("virtiofsd not found; volume '%s' will not be available", shared_dir)
                return None
            cmd = [
                virtiofsd,
                '--shared-dir', shared_dir,
                '--socket-path', socket_path,
                '--cache', 'never',
                '--allow-direct-io',
                '--allow-mmap',
                '--thread-pool-size', '8',
                '--sandbox', 'chroot',
            ]
            if read_only:
                cmd.append('--readonly')
            try:
                proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                return proc
            except Exception as e:
                logger.warning("failed to start virtiofsd for %s: %s", shared_dir, e)
                return None

        if self.config.network is None or self.config.network.lower() == 'user':
            # add user network
            args.append('-netdev')
            # https://man.archlinux.org/man/qemu.1.en#hostname=name
            base = 'user,id=user.qemu-compose%s' % (',hostname=' + hostname if hostname else '',)
            netdev_opts = base + hostfwd_segments(self.config.ports or [])
            args.append(netdev_opts)
            args.append('-device')
            args.append('virtio-net,netdev=user.qemu-compose')

        if self.cid:
            args.append("-device")
            args.append("vhost-vsock-pci,id=vhost-vsock-pci0,guest-cid=%d" % self.cid)

        assert self.vmid is not None
        pub_bytes = prepare_ssh_key(self.instance_dir, self.vmid)
        pub_b64 = base64.b64encode(pub_bytes).decode('ascii')

        args.append('-smbios')
        args.append(f'type=11,value=io.systemd.credential.binary:ssh.authorized_keys.root={pub_b64}')

        # storage disks
        for overlay_path, spec in self.storage_overlays:
            drive_param = drive_param_for(overlay_path, spec)
            args.append('-drive')
            args.append(drive_param)

        # volumes via virtio-fs and fstab entries
        fstab_entries: List[str] = []
        for i, vol_spec in enumerate(self.config.volumes or []):
            parsed = parse_volume_spec(vol_spec)
            if not parsed:
                continue
            src, dst, ro = parsed
            tag = volume_tag_for(dst, i)
            socket_path = os.path.join(self.instance_dir, f"virtiofs-{tag}.sock")
            child = start_virtiofsd(src, socket_path, ro)
            if child is not None:
                self.virtiofs_children.append(child)
            args.append('-chardev')
            args.append(f"socket,id=char{i},path={socket_path}")
            args.append('-device')
            args.append(f"vhost-user-fs-pci,chardev=char{i},tag={tag}")
            ro_suffix = ',ro' if ro else ''
            fstab_entries.append(f"{tag} {dst} virtiofs defaults{ro_suffix} 0 0")

        if fstab_entries:
            try:
                fstab_str = "\n".join(fstab_entries)
                fstab_b64 = base64.b64encode(fstab_str.encode('utf-8')).decode('ascii')
                args.append('-smbios')
                args.append(f'type=11,value=io.systemd.credential.binary:fstab.extra={fstab_b64}')
            except Exception as e:
                logger.warning("failed to encode fstab entries: %s", e)

        # image provided args append after defaults
        if self.image_manifest is not None and self.image_manifest.qemu_args:
            for arg in self.image_manifest.qemu_args:
                val = extract_format_or_default(None, arg, self.env)
                args.append(val)

        # user provided args append after defaults
        for block in self.config.qemu_args:
            for key in block:
                val = extract_format_or_default(block, key, self.env)
                if key in default_args:
                    continue
                args.append('-' + key)
                if val is not None:
                    args.append(val)

        self.add_args(*args)

    def start(self):
        self.launch()

        self.term = Terminal(self.console_file, self.log_file)

        try:
            pid = self.get_pid()
        except Exception:
            pid = None
        try:
            with open(os.path.join(self.instance_dir, "qemu.pid"), "w") as f:
                f.write("%s" % (str(pid) if pid is not None else ""))
            with open(os.path.join(self.instance_dir, "cid"), "w") as f:
                f.write(str(self.cid))
            with open(os.path.join(self.instance_dir, "name"), "w") as f:
                f.write(str(self.vm_name) if self.vm_name is not None else "")
            with open(os.path.join(self.instance_dir, "instance-id"), "w") as f:
                f.write(str(self.vmid))
        except Exception as e:
            logger.warning("failed to write instance metadata: %s", e)

    def interact(self):
        boot_commands = self.config.boot_commands
        if boot_commands:
            self.term.run_batch(boot_commands, env_variables=self.env)
        else:
            self.term.interact(raw_mode=True)

    def cleanup(self):
        self._load_io_log()
        logger.info('vm.process_io_log = %r' % (self.get_log(), ))

        try:
            if self.lock_fd is not None:
                fcntl.flock(self.lock_fd, fcntl.LOCK_UN)
                os.close(self.lock_fd)
        except Exception as e:
            logger.warning("failed to unlock instance dir: %s", e)
