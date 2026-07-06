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


DEFAULT_PULL_PROXIES = {
    "ALL_PROXY": "socks5h://10.3.6.10:1080",
    "HTTP_PROXY": "http://10.3.6.10:8123",
    "HTTPS_PROXY": "http://10.3.6.10:8123",
}


class OciImportError(RuntimeError):
    pass


def require_tools(tools: List[str]) -> None:
    missing = [tool for tool in tools if shutil.which(tool) is None]
    if missing:
        raise OciImportError("missing required command(s): " + ", ".join(missing))


def run_cmd(cmd: List[str], *, env: Optional[Dict[str, str]] = None) -> None:
    res = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    if res.returncode != 0:
        if res.stdout:
            print(res.stdout, file=sys.stderr, end="")
        if res.stderr:
            print(res.stderr, file=sys.stderr, end="")
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
    argv = shell_words(list(entrypoint) + list(cmd))
    if not argv:
        argv = "/bin/sh"

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
exec {argv}
"""
    init_path = rootfs / "qemu-compose-init"
    init_path.write_text(init)
    init_path.chmod(0o755)


def make_rootfs_tar(rootfs: Path, tar_path: Path) -> None:
    with tarfile.open(tar_path, "w") as tf:
        for item in rootfs.iterdir():
            tf.add(item, arcname=item.name, recursive=True)


def build_qcow2(rootfs: Path, disk_path: Path, disk_size: str) -> None:
    require_tools(["qemu-img", "guestfish"])
    rootfs_tar = disk_path.with_suffix(".rootfs.tar")
    make_rootfs_tar(rootfs, rootfs_tar)
    try:
        run_cmd(["qemu-img", "create", "-f", "qcow2", str(disk_path), disk_size])
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
    shutil.copy2(kernel_path, boot_dir / "vmlinuz")
    shutil.copy2(initrd_path, boot_dir / "initramfs.img")


def pull_oci_image(image: str, oci_dir: Path, digest_file: Path, platform: str, *, retry_proxy: bool) -> str:
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
    try:
        run_cmd(cmd)
    except OciImportError:
        if not retry_proxy:
            raise
        env = os.environ.copy()
        for key, value in DEFAULT_PULL_PROXIES.items():
            env.setdefault(key, value)
            env.setdefault(key.lower(), value)
        print("Initial pull failed; retrying with configured proxy", file=sys.stderr)
        run_cmd(cmd, env=env)
    return parse_digest(digest_file.read_text())


def unpack_oci_image(oci_dir: Path, bundle_dir: Path) -> None:
    run_cmd(["umoci", "unpack", "--image", str(oci_dir) + ":latest", str(bundle_dir)])


def write_manifest(
    image_dir: Path,
    *,
    image_id: str,
    digest: str,
    image: str,
    metadata: Dict[str, Any],
) -> None:
    config = metadata["config"]
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
            "console=ttyS0 root=/dev/vda1 rw init=/qemu-compose-init",
        ],
        "digest": digest,
        "comment": f"imported from OCI image {image}",
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
    retry_proxy: bool,
) -> str:
    image_root_path = Path(image_root)
    image_root_path.mkdir(parents=True, exist_ok=True)

    work_parent = Path(tempfile.mkdtemp(prefix=".pull-work-", dir=image_root))
    try:
        oci_dir = work_parent / "oci"
        bundle_dir = work_parent / "bundle"
        digest_file = work_parent / "digest"

        digest = pull_oci_image(image, oci_dir, digest_file, platform, retry_proxy=retry_proxy)
        image_id = image_id_from_digest(digest)
        final_dir = image_root_path / image_id

        if final_dir.exists() and not force:
            raise OciImportError(f"image already exists: {image_id}")
        if final_dir.exists():
            shutil.rmtree(final_dir)

        unpack_oci_image(oci_dir, bundle_dir)
        rootfs = bundle_dir / "rootfs"
        metadata = load_oci_metadata(oci_dir, digest)
        write_container_config(rootfs, image, metadata["config"])
        write_init(rootfs, metadata["config"])

        staged_dir = work_parent / "image"
        staged_dir.mkdir()
        shutil.copytree(oci_dir, staged_dir / "oci")
        copy_boot_assets(kernel, initrd, staged_dir / "boot")
        build_qcow2(rootfs, staged_dir / "disk.qcow2", disk_size)
        write_manifest(staged_dir, image_id=image_id, digest=digest, image=image, metadata=metadata)

        os.rename(staged_dir, final_dir)
        return image_id
    finally:
        if keep_workdir:
            print(f"Kept workdir: {work_parent}", file=sys.stderr)
        else:
            shutil.rmtree(work_parent, ignore_errors=True)
