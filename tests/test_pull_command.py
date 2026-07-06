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
    init_exec_line,
    make_rootfs_tar,
    normalize_repo_tag,
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


def test_configure_systemd_rootfs_requires_systemd(tmp_path):
    rootfs = tmp_path / "rootfs"
    rootfs.mkdir()

    try:
        configure_systemd_rootfs(rootfs)
    except OciImportError as e:
        assert "systemd boot requested" in str(e)
    else:
        raise AssertionError("expected OciImportError")
