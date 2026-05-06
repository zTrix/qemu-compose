from __future__ import annotations

import json
from pathlib import Path

from qemu_compose.cmd.rmi_command import command_rmi


def write_manifest(image_dir: Path, image_id: str, repo_tags: list[str]) -> None:
    image_dir.mkdir(parents=True, exist_ok=True)
    (image_dir / "manifest.json").write_text(
        json.dumps(
            {
                "id": image_id,
                "architecture": "x86_64",
                "os": "linux",
                "created": "2026-05-06T00:00:00Z",
                "repo_tags": repo_tags,
                "disks": [],
                "qemu_args": [],
                "digest": f"sha256:{image_id}",
                "comment": None,
            }
        )
    )


def test_rmi_by_tag_only_removes_tag_when_multiple_tags(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    image_id = "img-1234567890ab"
    image_dir = tmp_path / "qemu-compose" / "image" / image_id
    write_manifest(image_dir, image_id, ["repo:latest", "repo:v1"])

    assert command_rmi("repo:v1") == 0

    manifest = json.loads((image_dir / "manifest.json").read_text())
    assert manifest["repo_tags"] == ["repo:latest"]
    assert "Untagged: repo:v1" in capsys.readouterr().out


def test_rmi_by_tag_removes_image_when_last_tag(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    image_id = "img-abcdef123456"
    image_dir = tmp_path / "qemu-compose" / "image" / image_id
    write_manifest(image_dir, image_id, ["repo:latest"])

    assert command_rmi("repo:latest") == 0

    assert not image_dir.exists()
    assert f"Deleted: {image_id}" in capsys.readouterr().out


def test_rmi_by_image_id_removes_entire_image(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    image_id = "img-fedcba654321"
    image_dir = tmp_path / "qemu-compose" / "image" / image_id
    write_manifest(image_dir, image_id, ["repo:latest", "repo:v2"])

    assert command_rmi(image_id) == 0

    assert not image_dir.exists()
    assert f"Deleted: {image_id}" in capsys.readouterr().out
