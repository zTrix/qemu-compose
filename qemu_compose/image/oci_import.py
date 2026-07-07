from __future__ import annotations

import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

BOOT_CONTAINER = "container"
BOOT_SYSTEMD = "systemd"
BOOT_MODES = (BOOT_CONTAINER, BOOT_SYSTEMD)


class OciImportError(RuntimeError):
    pass


def require_tools(tools: List[str]) -> None:
    missing = [tool for tool in tools if shutil.which(tool) is None]
    if missing:
        raise OciImportError("missing required command(s): " + ", ".join(missing))


def run_cmd(cmd: List[str], *, env: Optional[Dict[str, str]] = None) -> None:
    res = subprocess.run(cmd, text=True, env=env)
    if res.returncode != 0:
        raise OciImportError("command failed: " + " ".join(cmd))


def parse_digest(value: str) -> str:
    digest = value.strip()
    if not digest.startswith("sha256:"):
        raise OciImportError(f"unsupported image digest: {digest}")
    return digest


def image_id_from_digest(digest: str) -> str:
    return digest.split(":", 1)[1]


def read_json(path: Path) -> Dict[str, Any]:
    with path.open() as f:
        return json.load(f)


def find_descriptor(index: Dict[str, Any], digest: str) -> Dict[str, Any]:
    manifests = index.get("manifests") or []
    for descriptor in manifests:
        if descriptor.get("digest") == digest:
            return descriptor
    if len(manifests) == 1:
        return manifests[0]
    raise OciImportError(f"could not find OCI descriptor for {digest}")


def blob_path(oci_dir: Path, digest: str) -> Path:
    algo, encoded = digest.split(":", 1)
    return oci_dir / "blobs" / algo / encoded


def load_oci_metadata(oci_dir: Path, digest: str) -> Dict[str, Any]:
    index = read_json(oci_dir / "index.json")
    descriptor = find_descriptor(index, digest)
    manifest = read_json(blob_path(oci_dir, descriptor["digest"]))
    config_desc = manifest.get("config") or {}
    config_digest = config_desc.get("digest")
    if not config_digest:
        raise OciImportError("OCI manifest does not contain a config descriptor")
    config = read_json(blob_path(oci_dir, config_digest))
    return {
        "descriptor": descriptor,
        "manifest": manifest,
        "config": config,
    }


def created_timestamp(config: Dict[str, Any]) -> str:
    created = config.get("created")
    if isinstance(created, str) and created:
        return created
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_repo_tag(image: str) -> str:
    last = image.rsplit("/", 1)[-1]
    if ":" in last:
        return image
    return image + ":latest"


def write_container_config(rootfs: Path, image: str, config: Dict[str, Any]) -> None:
    target_dir = rootfs / "etc" / "qemu-compose"
    target_dir.mkdir(parents=True, exist_ok=True)
    image_config = config.get("config") or {}
    payload = {
        "image": image,
        "env": image_config.get("Env") or [],
        "entrypoint": image_config.get("Entrypoint") or [],
        "cmd": image_config.get("Cmd") or [],
        "working_dir": image_config.get("WorkingDir") or "/",
    }
    (target_dir / "container-config.json").write_text(json.dumps(payload, indent=2) + "\n")


def shell_words(values: List[Any]) -> str:
    import shlex

    return " ".join(shlex.quote(str(v)) for v in values if v is not None)


def init_exec_line(values: List[Any]) -> str:
    argv = shell_words(values)
    if not argv:
        argv = "/bin/sh"
    return f"""if command -v setsid >/dev/null 2>&1 && command -v cttyhack >/dev/null 2>&1; then
    exec setsid cttyhack {argv}
fi
exec {argv}"""


def write_init(rootfs: Path, config: Dict[str, Any]) -> None:
    import shlex

    image_config = config.get("config") or {}
    env_lines = []
    for item in image_config.get("Env") or []:
        if not isinstance(item, str) or "=" not in item:
            continue
        key, value = item.split("=", 1)
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            continue
        env_lines.append(f"export {key}={shlex.quote(value)}")

    entrypoint = image_config.get("Entrypoint") or []
    cmd = image_config.get("Cmd") or []
    exec_lines = init_exec_line(list(entrypoint) + list(cmd))

    working_dir = image_config.get("WorkingDir") or "/"
    exports = "\n".join(env_lines)
    init = f"""#!/bin/sh
set -eu

mount -t proc proc /proc 2>/dev/null || true
mount -t sysfs sysfs /sys 2>/dev/null || true
mount -t devtmpfs devtmpfs /dev 2>/dev/null || true
mkdir -p /dev/pts /run /tmp
mount -t devpts devpts /dev/pts 2>/dev/null || true

{exports}
mkdir -p {shlex.quote(str(working_dir))}
cd {shlex.quote(str(working_dir))}
{exec_lines}
"""
    init_path = rootfs / "qemu-compose-init"
    init_path.write_text(init)
    init_path.chmod(0o755)


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def path_exists(rootfs: Path, path: str) -> bool:
    candidate = rootfs / path.lstrip("/")
    return candidate.exists() or candidate.is_symlink()


def systemd_binary_path(rootfs: Path) -> Optional[str]:
    for path in ("/usr/lib/systemd/systemd", "/lib/systemd/systemd"):
        if path_exists(rootfs, path):
            return path
    return None


def systemd_unit_path(rootfs: Path, unit_name: str) -> Optional[str]:
    for directory in ("/usr/lib/systemd/system", "/lib/systemd/system", "/etc/systemd/system"):
        path = f"{directory}/{unit_name}"
        if path_exists(rootfs, path):
            return path
    return None


def enable_systemd_unit(rootfs: Path, unit_name: str, target: str = "multi-user.target") -> bool:
    unit_path = systemd_unit_path(rootfs, unit_name)
    if not unit_path:
        return False

    wants_dir = rootfs / "etc" / "systemd" / "system" / f"{target}.wants"
    wants_dir.mkdir(parents=True, exist_ok=True)
    link_path = wants_dir / unit_name
    try:
        if link_path.exists() or link_path.is_symlink():
            link_path.unlink()
        link_path.symlink_to(unit_path)
    except OSError:
        return False
    return True


def sudo_prefix(use_sudo: bool) -> List[str]:
    if not use_sudo:
        return []
    sudo = shutil.which("sudo")
    if sudo is None:
        raise OciImportError("systemd boot requested, but systemd is missing and sudo was not found")
    return [sudo]


def chroot_run(rootfs: Path, cmd: List[str], *, use_sudo: bool = False) -> None:
    res = subprocess.run([*sudo_prefix(use_sudo), "chroot", str(rootfs), *cmd], text=True)
    if res.returncode != 0:
        raise OciImportError("command failed in rootfs: " + " ".join(cmd))


def mount_chroot_runtime(rootfs: Path, *, use_sudo: bool = False) -> List[Path]:
    mounted: List[Path] = []
    mounts = [
        (["mount", "-t", "proc", "proc"], rootfs / "proc"),
        (["mount", "-t", "sysfs", "sysfs"], rootfs / "sys"),
        (["mount", "-t", "devtmpfs", "devtmpfs"], rootfs / "dev"),
        (["mount", "-t", "devpts", "devpts", "-o", "gid=5,mode=620,ptmxmode=666"], rootfs / "dev" / "pts"),
    ]
    for cmd, target in mounts:
        target.mkdir(parents=True, exist_ok=True)
        if subprocess.run(["mountpoint", "-q", str(target)]).returncode == 0:
            continue
        run_cmd([*sudo_prefix(use_sudo), *cmd, str(target)])
        mounted.append(target)
    return mounted


def unmount_chroot_runtime(mounted: List[Path], *, use_sudo: bool = False) -> None:
    for target in reversed(mounted):
        subprocess.run([*sudo_prefix(use_sudo), "umount", "-l", str(target)], check=False)


def restore_rootfs_write_ownership(rootfs: Path) -> None:
    uid = os.getuid()
    gid = os.getgid()
    res = subprocess.run([*sudo_prefix(True), "chown", "-R", f"{uid}:{gid}", str(rootfs)], text=True)
    if res.returncode != 0:
        raise OciImportError("failed to restore rootfs ownership after Debian/Ubuntu package install")


def install_debian_systemd_packages(rootfs: Path) -> bool:
    if systemd_binary_path(rootfs):
        return True
    if not path_exists(rootfs, "/usr/bin/apt-get"):
        return False
    use_sudo = os.geteuid() != 0

    resolv_conf = Path("/etc/resolv.conf")
    if resolv_conf.exists():
        (rootfs / "etc").mkdir(parents=True, exist_ok=True)
        shutil.copy2(resolv_conf, rootfs / "etc" / "resolv.conf")

    print("Installing systemd packages into Debian/Ubuntu rootfs", flush=True)
    mounted: List[Path] = []
    try:
        mounted = mount_chroot_runtime(rootfs, use_sudo=use_sudo)
        env = "DEBIAN_FRONTEND=noninteractive"
        chroot_run(rootfs, ["env", env, "apt-get", "update"], use_sudo=use_sudo)
        chroot_run(
            rootfs,
            [
                "env",
                env,
                "apt-get",
                "install",
                "-y",
                "--no-install-recommends",
                "systemd",
                "systemd-sysv",
                "systemd-resolved",
                "dbus",
                "iproute2",
                "kmod",
                "udev",
                "openssh-server",
            ],
            use_sudo=use_sudo,
        )
    finally:
        unmount_chroot_runtime(mounted, use_sudo=use_sudo)
        if use_sudo:
            restore_rootfs_write_ownership(rootfs)

    return systemd_binary_path(rootfs) is not None


def configure_systemd_rootfs(rootfs: Path) -> None:
    if not install_debian_systemd_packages(rootfs):
        raise OciImportError("systemd boot requested, but systemd was not found in the image")

    systemd_path = systemd_binary_path(rootfs)
    if systemd_path and systemd_path != "/usr/lib/systemd/systemd":
        compat_path = rootfs / "usr" / "lib" / "systemd" / "systemd"
        compat_path.parent.mkdir(parents=True, exist_ok=True)
        if not compat_path.exists() and not compat_path.is_symlink():
            compat_path.symlink_to(systemd_path)

    write_text(rootfs / "etc" / "fstab", "/dev/vda1 / ext4 rw 0 1\n")

    machine_id = rootfs / "etc" / "machine-id"
    machine_id.parent.mkdir(parents=True, exist_ok=True)
    machine_id.write_text("")

    imds_generator = None
    for path in (
        "/usr/lib/systemd/system-generators/systemd-imds-generator",
        "/lib/systemd/system-generators/systemd-imds-generator",
    ):
        if path_exists(rootfs, path):
            imds_generator = rootfs / path.lstrip("/")
            break
    if imds_generator is not None:
        mask_dir = rootfs / "etc" / "systemd" / "system-generators"
        mask_dir.mkdir(parents=True, exist_ok=True)
        mask_path = mask_dir / "systemd-imds-generator"
        if mask_path.exists() or mask_path.is_symlink():
            mask_path.unlink()
        mask_path.symlink_to("/dev/null")

    if systemd_unit_path(rootfs, "systemd-networkd.service"):
        write_text(
            rootfs / "etc" / "systemd" / "network" / "80-dhcp.network",
            """[Match]
Name=en*
Name=eth*

[Network]
DHCP=yes
""",
        )
        enable_systemd_unit(rootfs, "systemd-networkd.service")

    enable_systemd_unit(rootfs, "systemd-resolved.service")
    enable_systemd_unit(rootfs, "sshd.service")
    enable_systemd_unit(rootfs, "ssh.service")
    enable_systemd_unit(rootfs, "qemu-guest-agent.service")

    if enable_systemd_unit(rootfs, "console-getty.service", target="getty.target"):
        return

    serial_unit = systemd_unit_path(rootfs, "serial-getty@.service")
    if serial_unit:
        wants_dir = rootfs / "etc" / "systemd" / "system" / "getty.target.wants"
        wants_dir.mkdir(parents=True, exist_ok=True)
        link_path = wants_dir / "serial-getty@ttyS0.service"
        if link_path.exists() or link_path.is_symlink():
            link_path.unlink()
        link_path.symlink_to(serial_unit)


def set_root_password_hash(rootfs: Path, password_hash: str, *, allow_empty_password: bool = False) -> None:
    shadow_path = rootfs / "etc" / "shadow"
    if not shadow_path.exists():
        raise OciImportError("root password requested, but /etc/shadow was not found in the image")

    lines = shadow_path.read_text().splitlines()
    updated = False
    for idx, line in enumerate(lines):
        if not line.startswith("root:"):
            continue
        parts = line.split(":")
        if len(parts) < 2:
            raise OciImportError("root password requested, but root shadow entry is malformed")
        parts[1] = password_hash
        lines[idx] = ":".join(parts)
        updated = True
        break

    if not updated:
        raise OciImportError("root password requested, but root user was not found in /etc/shadow")

    shadow_path.write_text("\n".join(lines) + "\n")
    if allow_empty_password:
        ensure_pam_nullok(rootfs)


def set_root_empty_password(rootfs: Path) -> None:
    set_root_password_hash(rootfs, "", allow_empty_password=True)


def hash_root_password(password: str) -> str:
    openssl = shutil.which("openssl")
    if openssl is None:
        raise OciImportError("root password requested, but 'openssl' was not found in PATH")

    res = subprocess.run(
        [openssl, "passwd", "-6", "-stdin"],
        input=password + "\n",
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if res.returncode != 0:
        if res.stderr:
            print(res.stderr, file=sys.stderr, end="")
        raise OciImportError("failed to hash root password with openssl")
    password_hash = res.stdout.strip()
    if not password_hash:
        raise OciImportError("failed to hash root password with openssl")
    return password_hash


def ensure_pam_nullok(rootfs: Path) -> None:
    pam_dir = rootfs / "etc" / "pam.d"
    if not pam_dir.is_dir():
        return

    for pam_file in pam_dir.iterdir():
        if not pam_file.is_file():
            continue
        lines = pam_file.read_text().splitlines()
        changed = False
        new_lines = []
        for line in lines:
            stripped = line.lstrip()
            if (
                stripped.startswith("auth")
                or stripped.startswith("-auth")
            ) and "pam_unix.so" in line and "nullok" not in line.split("#", 1)[0].split():
                line = line + " nullok"
                changed = True
            new_lines.append(line)
        if changed:
            pam_file.write_text("\n".join(new_lines) + "\n")


def make_rootfs_tar(rootfs: Path, tar_path: Path) -> None:
    def normalize_owner(tar_info: tarfile.TarInfo) -> tarfile.TarInfo:
        # Rootless OCI unpack cannot chown files on the host. Normalize the
        # tar stream so the guest image does not inherit the importing user's
        # uid/gid for core filesystem paths.
        tar_info.uid = 0
        tar_info.gid = 0
        tar_info.uname = "root"
        tar_info.gname = "root"
        return tar_info

    with tarfile.open(tar_path, "w") as tf:
        for item in rootfs.iterdir():
            tf.add(item, arcname=item.name, recursive=True, filter=normalize_owner)


def build_qcow2(rootfs: Path, disk_path: Path, disk_size: str) -> None:
    require_tools(["qemu-img", "guestfish"])
    rootfs_tar = disk_path.with_suffix(".rootfs.tar")
    print(f"Packing root filesystem: {rootfs_tar}", flush=True)
    make_rootfs_tar(rootfs, rootfs_tar)
    try:
        print(f"Creating qcow2 disk: {disk_path} ({disk_size})", flush=True)
        run_cmd(["qemu-img", "create", "-f", "qcow2", str(disk_path), disk_size])
        print("Copying root filesystem into qcow2 disk", flush=True)
        run_cmd(
            [
                "guestfish",
                "--format=qcow2",
                "-a",
                str(disk_path),
                "run",
                ":",
                "part-disk",
                "/dev/sda",
                "mbr",
                ":",
                "mkfs",
                "ext4",
                "/dev/sda1",
                ":",
                "mount",
                "/dev/sda1",
                "/",
                ":",
                "tar-in",
                str(rootfs_tar),
                "/",
                "xattrs:true",
                "acls:true",
            ]
        )
    finally:
        try:
            rootfs_tar.unlink()
        except FileNotFoundError:
            pass


def copy_boot_assets(kernel: str, initrd: str, boot_dir: Path) -> None:
    kernel_path = Path(kernel)
    initrd_path = Path(initrd)
    if not kernel_path.is_file():
        raise OciImportError(f"kernel not found: {kernel}")
    if not initrd_path.is_file():
        raise OciImportError(f"initrd not found: {initrd}")
    boot_dir.mkdir(parents=True, exist_ok=True)
    copy_boot_asset(kernel_path, boot_dir / "vmlinuz")
    copy_boot_asset(initrd_path, boot_dir / "initramfs.img")


def copy_boot_asset(source: Path, target: Path) -> None:
    try:
        shutil.copy2(source, target)
        return
    except PermissionError:
        if os.geteuid() == 0:
            raise

    res = subprocess.run([*sudo_prefix(True), "cp", "-a", str(source), str(target)], text=True)
    if res.returncode != 0:
        raise OciImportError(f"failed to copy boot asset: {source}")
    res = subprocess.run([*sudo_prefix(True), "chown", f"{os.getuid()}:{os.getgid()}", str(target)], text=True)
    if res.returncode != 0:
        raise OciImportError(f"failed to restore boot asset ownership: {target}")


def kernel_release_from_image(kernel: str) -> Optional[str]:
    try:
        data = Path(kernel).read_bytes()
    except OSError:
        return None

    match = re.search(rb"Linux version ([0-9A-Za-z_.+-]+)", data)
    if match:
        return match.group(1).decode("ascii", errors="ignore")
    return None


def kernel_release_from_initrd(initrd: str) -> Optional[str]:
    tools = [["lsinitcpio", "-l", initrd], ["lsinitramfs", initrd]]
    for cmd in tools:
        if shutil.which(cmd[0]) is None:
            continue
        for prefix in ([], sudo_prefix(True) if os.geteuid() != 0 and shutil.which("sudo") else []):
            try:
                res = subprocess.run([*prefix, *cmd], text=True, capture_output=True, check=False)
            except OSError:
                continue
            if res.returncode != 0:
                continue
            match = re.search(r"(?:^|/)lib/modules/([^/\s]+)/", res.stdout, re.MULTILINE)
            if match:
                return match.group(1)
    return None


def copy_kernel_modules(
    rootfs: Path,
    kernel: str,
    initrd: Optional[str] = None,
    modules_roots: Optional[List[Path]] = None,
) -> bool:
    release = kernel_release_from_initrd(initrd) if initrd else None
    if not release:
        release = kernel_release_from_image(kernel)
    if not release:
        release = os.uname().release

    if modules_roots is None:
        modules_roots = [Path("/usr/lib/modules"), Path("/lib/modules")]

    source = None
    for root in modules_roots:
        candidate = root / release
        if candidate.is_dir():
            source = candidate
            break

    if source is None:
        print(f"Warning: kernel modules not found for {release}; guest devices may not have drivers", file=sys.stderr)
        return False

    target = rootfs / "usr" / "lib" / "modules" / release
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, symlinks=True, dirs_exist_ok=True)
    return True


def pull_oci_image(image: str, oci_dir: Path, digest_file: Path, platform: str) -> str:
    require_tools(["skopeo", "umoci"])
    platform_parts = platform.split("/")
    if len(platform_parts) < 2:
        raise OciImportError(f"invalid platform: {platform}")
    os_name = platform_parts[0]
    arch = platform_parts[1]
    variant_args: List[str] = []
    if len(platform_parts) > 2 and platform_parts[2]:
        variant_args = ["--override-variant", platform_parts[2]]

    cmd = [
        "skopeo",
        "--override-os",
        os_name,
        "--override-arch",
        arch,
        *variant_args,
        "copy",
        "--format",
        "oci",
        "--digestfile",
        str(digest_file),
        "docker://" + image,
        "oci:" + str(oci_dir) + ":latest",
    ]
    print(f"Pulling OCI image: {image} ({platform})", flush=True)
    run_cmd(cmd)
    return parse_digest(digest_file.read_text())


def unpack_oci_image(oci_dir: Path, bundle_dir: Path) -> None:
    cmd = ["umoci", "unpack"]
    if os.geteuid() != 0:
        cmd.append("--rootless")
    cmd.extend(["--image", str(oci_dir) + ":latest", str(bundle_dir)])
    print("Unpacking OCI image root filesystem", flush=True)
    run_cmd(cmd)


def write_manifest(
    image_dir: Path,
    *,
    image_id: str,
    digest: str,
    image: str,
    metadata: Dict[str, Any],
    boot_mode: str,
) -> None:
    config = metadata["config"]
    if boot_mode == BOOT_CONTAINER:
        append_args = "console=ttyS0 root=/dev/vda1 rw init=/qemu-compose-init disablehooks=encrypt"
    elif boot_mode == BOOT_SYSTEMD:
        append_args = "console=ttyS0 root=/dev/vda1 rw init=/usr/lib/systemd/systemd systemd.unit=multi-user.target disablehooks=encrypt"
    else:
        raise OciImportError(f"unsupported boot mode: {boot_mode}")

    manifest = {
        "id": image_id,
        "architecture": str(config.get("architecture") or ""),
        "os": str(config.get("os") or "linux"),
        "created": created_timestamp(config),
        "repo_tags": [normalize_repo_tag(image)],
        "disks": [["disk.qcow2", "qcow2", "if=virtio"]],
        "qemu_args": [
            "-kernel",
            "{IMAGE_DIR}/boot/vmlinuz",
            "-initrd",
            "{IMAGE_DIR}/boot/initramfs.img",
            "-append",
            append_args,
        ],
        "digest": digest,
        "comment": f"imported from OCI image {image} with {boot_mode} boot",
    }
    with (image_dir / "manifest.json").open("w") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")


def import_oci_image(
    *,
    image_root: str,
    image: str,
    kernel: str,
    initrd: str,
    platform: str,
    disk_size: str,
    force: bool,
    keep_workdir: bool,
    boot_mode: str,
    empty_root_password: bool,
    root_password: Optional[str],
) -> str:
    if boot_mode not in BOOT_MODES:
        raise OciImportError(f"unsupported boot mode: {boot_mode}")

    image_root_path = Path(image_root)
    image_root_path.mkdir(parents=True, exist_ok=True)

    work_parent = Path(tempfile.mkdtemp(prefix=".pull-work-", dir=image_root))
    try:
        oci_dir = work_parent / "oci"
        bundle_dir = work_parent / "bundle"
        digest_file = work_parent / "digest"

        digest = pull_oci_image(image, oci_dir, digest_file, platform)
        image_id = image_id_from_digest(digest)
        final_dir = image_root_path / image_id

        if final_dir.exists() and not force:
            raise OciImportError(f"image already exists: {image_id}")
        if final_dir.exists():
            shutil.rmtree(final_dir)

        unpack_oci_image(oci_dir, bundle_dir)
        rootfs = bundle_dir / "rootfs"
        metadata = load_oci_metadata(oci_dir, digest)
        if boot_mode == BOOT_CONTAINER:
            write_container_config(rootfs, image, metadata["config"])
            write_init(rootfs, metadata["config"])
        elif boot_mode == BOOT_SYSTEMD:
            configure_systemd_rootfs(rootfs)
        if root_password is not None:
            set_root_password_hash(rootfs, hash_root_password(root_password))
        elif empty_root_password:
            set_root_empty_password(rootfs)
        copy_kernel_modules(rootfs, kernel, initrd)

        staged_dir = work_parent / "image"
        staged_dir.mkdir()
        shutil.copytree(oci_dir, staged_dir / "oci")
        copy_boot_assets(kernel, initrd, staged_dir / "boot")
        build_qcow2(rootfs, staged_dir / "disk.qcow2", disk_size)
        write_manifest(staged_dir, image_id=image_id, digest=digest, image=image, metadata=metadata, boot_mode=boot_mode)

        os.rename(staged_dir, final_dir)
        return image_id
    finally:
        if keep_workdir:
            print(f"Kept workdir: {work_parent}", file=sys.stderr)
        else:
            shutil.rmtree(work_parent, ignore_errors=True)
