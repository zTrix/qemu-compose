from __future__ import annotations

import json
from pathlib import Path

from qemu_compose.cmd import pull_command
from qemu_compose.cmd.pull_command import command_pull
from qemu_compose.image.oci_import import OciImportError, normalize_repo_tag


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
