from __future__ import annotations

import json
import tarfile
from pathlib import Path

from qemu_compose.cmd import pull_command
from qemu_compose.cmd.pull_command import command_pull
from qemu_compose.image import oci_import
from qemu_compose.image.oci_import import (
    BOOT_CONTAINER,
    BOOT_SYSTEMD,
    OciImportError,
    configure_systemd_rootfs,
    copy_kernel_modules,
    ensure_pam_nullok,
    hash_root_password,
    init_exec_line,
    kernel_release_from_initrd,
    kernel_release_from_image,
    make_rootfs_tar,
    normalize_repo_tag,
    set_root_empty_password,
    set_root_password_hash,
    unpack_oci_image,
    write_manifest as write_import_manifest,
)


def write_manifest(image_dir: Path, image_id: str, repo_tags: list[str]) -> None:
    image_dir.mkdir(parents=True, exist_ok=True)
    (image_dir / "manifest.json").write_text(
        json.dumps(
            {
                "id": image_id,
                "architecture": "amd64",
                "os": "linux",
                "created": "2026-05-06T00:00:00Z",
                "repo_tags": repo_tags,
                "disks": [["disk.qcow2", "qcow2", "if=virtio"]],
                "qemu_args": [],
                "digest": f"sha256:{image_id}",
                "comment": None,
            }
        )
    )


def test_normalize_repo_tag_defaults_to_latest():
    assert normalize_repo_tag("alpine") == "alpine:latest"
    assert normalize_repo_tag("alpine:3.20") == "alpine:3.20"
    assert normalize_repo_tag("registry.example.test/ns/app") == "registry.example.test/ns/app:latest"


def test_pull_prints_imported_image(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    image_id = "abc123def456"

    def fake_import(**kwargs):
        assert kwargs["empty_root_password"] is True
        assert kwargs["root_password"] is None
        image_dir = tmp_path / "qemu-compose" / "image" / image_id
        write_manifest(image_dir, image_id, ["alpine:3.20"])
        return image_id

    monkeypatch.setattr(pull_command, "import_oci_image", fake_import)

    assert command_pull(image="alpine:3.20", kernel="/k", initrd="/i") == 0

    out = capsys.readouterr().out
    assert "Pulled: alpine:3.20" in out
    assert f"Image: {image_id}" in out


def test_pull_removes_same_tag_from_old_image(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    image_root = tmp_path / "qemu-compose" / "image"
    old_id = "old123"
    new_id = "new456"
    write_manifest(image_root / old_id, old_id, ["alpine:3.20", "old:keep"])

    def fake_import(**kwargs):
        write_manifest(image_root / new_id, new_id, ["alpine:3.20"])
        return new_id

    monkeypatch.setattr(pull_command, "import_oci_image", fake_import)

    assert command_pull(image="alpine:3.20", kernel="/k", initrd="/i") == 0

    old_manifest = json.loads((image_root / old_id / "manifest.json").read_text())
    assert old_manifest["repo_tags"] == ["old:keep"]


def test_pull_reports_import_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    def fake_import(**kwargs):
        raise OciImportError("missing required command(s): skopeo")

    monkeypatch.setattr(pull_command, "import_oci_image", fake_import)

    assert command_pull(image="alpine:3.20", kernel="/k", initrd="/i") == 1
    assert "missing required command(s): skopeo" in capsys.readouterr().err


def test_unpack_oci_image_uses_rootless_when_not_root(tmp_path, monkeypatch):
    commands = []

    def fake_run_cmd(cmd, **kwargs):
        commands.append(cmd)

    monkeypatch.setattr(oci_import.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(oci_import, "run_cmd", fake_run_cmd)

    unpack_oci_image(tmp_path / "oci", tmp_path / "bundle")

    assert commands == [
        [
            "umoci",
            "unpack",
            "--rootless",
            "--image",
            str(tmp_path / "oci") + ":latest",
            str(tmp_path / "bundle"),
        ]
    ]


def test_rootfs_tar_normalizes_owner_to_root(tmp_path):
    rootfs = tmp_path / "rootfs"
    rootfs.mkdir()
    (rootfs / "etc").mkdir()
    (rootfs / "etc" / "issue").write_text("test\n")
    tar_path = tmp_path / "rootfs.tar"

    make_rootfs_tar(rootfs, tar_path)

    with tarfile.open(tar_path) as tf:
        members = {member.name: member for member in tf.getmembers()}

    assert members["etc"].uid == 0
    assert members["etc"].gid == 0
    assert members["etc/issue"].uid == 0
    assert members["etc/issue"].gid == 0


def test_init_exec_line_uses_cttyhack_when_available():
    script = init_exec_line(["/bin/sh"])

    assert "exec setsid cttyhack /bin/sh" in script
    assert "exec /bin/sh" in script


def test_manifest_disables_encrypt_hook(tmp_path):
    image_dir = tmp_path / "image"
    image_dir.mkdir()

    write_import_manifest(
        image_dir,
        image_id="abc123",
        digest="sha256:abc123",
        image="alpine:3.20",
        metadata={
            "config": {
                "architecture": "amd64",
                "os": "linux",
                "created": "2026-05-06T00:00:00Z",
            }
        },
        boot_mode=BOOT_CONTAINER,
    )

    manifest = json.loads((image_dir / "manifest.json").read_text())
    append_idx = manifest["qemu_args"].index("-append") + 1
    assert "disablehooks=encrypt" in manifest["qemu_args"][append_idx]


def test_systemd_manifest_boots_systemd(tmp_path):
    image_dir = tmp_path / "image"
    image_dir.mkdir()

    write_import_manifest(
        image_dir,
        image_id="abc123",
        digest="sha256:abc123",
        image="archlinux:latest",
        metadata={
            "config": {
                "architecture": "amd64",
                "os": "linux",
                "created": "2026-05-06T00:00:00Z",
            }
        },
        boot_mode=BOOT_SYSTEMD,
    )

    manifest = json.loads((image_dir / "manifest.json").read_text())
    append_idx = manifest["qemu_args"].index("-append") + 1
    append_args = manifest["qemu_args"][append_idx]
    assert "init=/usr/lib/systemd/systemd" in append_args
    assert "systemd.unit=multi-user.target" in append_args
    assert "init=/qemu-compose-init" not in append_args


def test_configure_systemd_rootfs_enables_vm_units(tmp_path):
    rootfs = tmp_path / "rootfs"
    unit_dir = rootfs / "usr" / "lib" / "systemd" / "system"
    unit_dir.mkdir(parents=True)
    (rootfs / "usr" / "lib" / "systemd" / "systemd").write_text("")
    for unit in [
        "systemd-networkd.service",
        "systemd-resolved.service",
        "serial-getty@.service",
        "sshd.service",
    ]:
        (unit_dir / unit).write_text("")
    generator_dir = rootfs / "usr" / "lib" / "systemd" / "system-generators"
    generator_dir.mkdir(parents=True)
    (generator_dir / "systemd-imds-generator").write_text("")

    configure_systemd_rootfs(rootfs)

    assert (rootfs / "etc" / "fstab").read_text() == "/dev/vda1 / ext4 rw 0 1\n"
    assert (rootfs / "etc" / "machine-id").read_text() == ""
    assert (rootfs / "etc" / "systemd" / "network" / "80-dhcp.network").exists()
    assert (rootfs / "etc" / "systemd" / "system" / "multi-user.target.wants" / "systemd-networkd.service").is_symlink()
    assert (rootfs / "etc" / "systemd" / "system" / "multi-user.target.wants" / "systemd-resolved.service").is_symlink()
    assert (rootfs / "etc" / "systemd" / "system" / "multi-user.target.wants" / "sshd.service").is_symlink()
    assert (rootfs / "etc" / "systemd" / "system" / "getty.target.wants" / "serial-getty@ttyS0.service").is_symlink()
    assert (rootfs / "etc" / "systemd" / "system-generators" / "systemd-imds-generator").is_symlink()


def test_configure_systemd_rootfs_does_not_install_packages_for_arch_layout(tmp_path, monkeypatch):
    rootfs = tmp_path / "rootfs"
    unit_dir = rootfs / "usr" / "lib" / "systemd" / "system"
    unit_dir.mkdir(parents=True)
    (rootfs / "usr" / "lib" / "systemd" / "systemd").write_text("")

    def fail_chroot_run(rootfs, cmd):
        raise AssertionError("Arch-style systemd rootfs should not invoke apt/chroot")

    monkeypatch.setattr(oci_import, "chroot_run", fail_chroot_run)

    configure_systemd_rootfs(rootfs)

    assert (rootfs / "etc" / "fstab").exists()


def test_configure_systemd_rootfs_supports_debian_systemd_layout(tmp_path):
    rootfs = tmp_path / "rootfs"
    unit_dir = rootfs / "lib" / "systemd" / "system"
    unit_dir.mkdir(parents=True)
    (rootfs / "lib" / "systemd" / "systemd").write_text("")
    for unit in [
        "systemd-networkd.service",
        "systemd-resolved.service",
        "serial-getty@.service",
        "ssh.service",
    ]:
        (unit_dir / unit).write_text("")

    configure_systemd_rootfs(rootfs)

    assert (rootfs / "usr" / "lib" / "systemd" / "systemd").is_symlink()
    assert (rootfs / "usr" / "lib" / "systemd" / "systemd").readlink() == Path("/lib/systemd/systemd")
    assert (rootfs / "etc" / "systemd" / "network" / "80-dhcp.network").exists()
    assert (
        rootfs / "etc" / "systemd" / "system" / "multi-user.target.wants" / "systemd-networkd.service"
    ).readlink() == Path("/lib/systemd/system/systemd-networkd.service")
    assert (rootfs / "etc" / "systemd" / "system" / "multi-user.target.wants" / "ssh.service").is_symlink()
    assert (
        rootfs / "etc" / "systemd" / "system" / "getty.target.wants" / "serial-getty@ttyS0.service"
    ).readlink() == Path("/lib/systemd/system/serial-getty@.service")


def test_configure_systemd_rootfs_requires_systemd(tmp_path):
    rootfs = tmp_path / "rootfs"
    rootfs.mkdir()

    try:
        configure_systemd_rootfs(rootfs)
    except OciImportError as e:
        assert "systemd boot requested" in str(e)
    else:
        raise AssertionError("expected OciImportError")


def test_set_root_empty_password_unlocks_shadow_and_pam(tmp_path):
    rootfs = tmp_path / "rootfs"
    shadow = rootfs / "etc" / "shadow"
    shadow.parent.mkdir(parents=True)
    shadow.write_text("root:!:20000:0:99999:7:::\nuser:x:20000:0:99999:7:::\n")
    pam = rootfs / "etc" / "pam.d" / "system-auth"
    pam.parent.mkdir(parents=True)
    pam.write_text("auth       [success=1 default=bad]     pam_unix.so          try_first_pass\n")

    set_root_empty_password(rootfs)

    assert shadow.read_text().splitlines()[0] == "root::20000:0:99999:7:::"
    assert "nullok" in pam.read_text()


def test_ensure_pam_nullok_is_idempotent(tmp_path):
    rootfs = tmp_path / "rootfs"
    pam = rootfs / "etc" / "pam.d" / "system-auth"
    pam.parent.mkdir(parents=True)
    pam.write_text("auth required pam_unix.so nullok\n")

    ensure_pam_nullok(rootfs)

    assert pam.read_text() == "auth required pam_unix.so nullok\n"


def test_kernel_release_from_image_reads_linux_version(tmp_path):
    kernel = tmp_path / "vmlinuz"
    kernel.write_bytes(b"prefix Linux version 6.18.37-1-lts (builder@example) suffix")

    assert kernel_release_from_image(str(kernel)) == "6.18.37-1-lts"


def test_kernel_release_from_initrd_uses_lsinitcpio(tmp_path, monkeypatch):
    initrd = tmp_path / "initramfs.img"
    initrd.write_text("")

    def fake_which(tool):
        return "/usr/bin/" + tool if tool == "lsinitcpio" else None

    def fake_run(cmd, **kwargs):
        class Result:
            returncode = 0
            stdout = "usr/lib/modules/7.0.14-arch1-1/kernel/drivers/block/virtio_blk.ko.zst\n"

        assert cmd == ["lsinitcpio", "-l", str(initrd)]
        return Result()

    monkeypatch.setattr(oci_import.shutil, "which", fake_which)
    monkeypatch.setattr(oci_import.subprocess, "run", fake_run)

    assert kernel_release_from_initrd(str(initrd)) == "7.0.14-arch1-1"


def test_copy_kernel_modules_copies_matching_module_tree(tmp_path):
    kernel = tmp_path / "vmlinuz"
    kernel.write_bytes(b"Linux version 6.18.37-1-lts (builder@example)")
    modules_root = tmp_path / "modules-root"
    module_dir = modules_root / "6.18.37-1-lts"
    module_dir.mkdir(parents=True)
    (module_dir / "modules.dep").write_text("kernel/drivers/net/virtio_net.ko.zst:\n")
    net_dir = module_dir / "kernel" / "drivers" / "net"
    net_dir.mkdir(parents=True)
    (net_dir / "virtio_net.ko.zst").write_text("module")
    rootfs = tmp_path / "rootfs"

    assert copy_kernel_modules(rootfs, str(kernel), modules_roots=[modules_root]) is True
    assert (rootfs / "usr" / "lib" / "modules" / "6.18.37-1-lts" / "modules.dep").exists()
    assert (
        rootfs
        / "usr"
        / "lib"
        / "modules"
        / "6.18.37-1-lts"
        / "kernel"
        / "drivers"
        / "net"
        / "virtio_net.ko.zst"
    ).exists()


def test_copy_kernel_modules_prefers_initrd_release(tmp_path, monkeypatch):
    kernel = tmp_path / "vmlinuz"
    kernel.write_bytes(b"")
    initrd = tmp_path / "initramfs.img"
    initrd.write_text("")
    modules_root = tmp_path / "modules-root"
    module_dir = modules_root / "7.0.14-arch1-1"
    module_dir.mkdir(parents=True)
    (module_dir / "modules.dep").write_text("")
    rootfs = tmp_path / "rootfs"

    monkeypatch.setattr(oci_import, "kernel_release_from_initrd", lambda initrd_path: "7.0.14-arch1-1")
    monkeypatch.setattr(oci_import.os, "uname", lambda: type("Uname", (), {"release": "6.18.37-1-lts"})())

    assert copy_kernel_modules(rootfs, str(kernel), str(initrd), modules_roots=[modules_root]) is True
    assert (rootfs / "usr" / "lib" / "modules" / "7.0.14-arch1-1" / "modules.dep").exists()
    assert not (rootfs / "usr" / "lib" / "modules" / "6.18.37-1-lts").exists()


def test_copy_kernel_modules_warns_when_matching_modules_missing(tmp_path, capsys):
    kernel = tmp_path / "vmlinuz"
    kernel.write_bytes(b"Linux version 6.18.37-1-lts (builder@example)")
    rootfs = tmp_path / "rootfs"

    assert copy_kernel_modules(rootfs, str(kernel), modules_roots=[tmp_path / "missing"]) is False

    assert "kernel modules not found for 6.18.37-1-lts" in capsys.readouterr().err


def test_set_root_password_hash_updates_shadow_without_nullok(tmp_path):
    rootfs = tmp_path / "rootfs"
    shadow = rootfs / "etc" / "shadow"
    shadow.parent.mkdir(parents=True)
    shadow.write_text("root:!:20000:0:99999:7:::\n")
    pam = rootfs / "etc" / "pam.d" / "system-auth"
    pam.parent.mkdir(parents=True)
    pam.write_text("auth required pam_unix.so\n")

    set_root_password_hash(rootfs, "$6$hash")

    assert shadow.read_text().splitlines()[0] == "root:$6$hash:20000:0:99999:7:::"
    assert pam.read_text() == "auth required pam_unix.so\n"


def test_hash_root_password_generates_sha512_hash():
    password_hash = hash_root_password("testpass")

    assert password_hash.startswith("$6$")
