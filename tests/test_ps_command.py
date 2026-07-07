from __future__ import annotations

import json
from pathlib import Path

from qemu_compose.cmd.ps_command import command_ps


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


def write_instance_meta(instance_dir: Path, *, name: str, image: str, image_id: str, pid: str = "") -> None:
    instance_dir.mkdir(parents=True, exist_ok=True)
    (instance_dir / "name").write_text(name)
    (instance_dir / "image").write_text(image)
    (instance_dir / "image-id").write_text(image_id)
    (instance_dir / "qemu.pid").write_text(pid)
    (instance_dir / "cid").write_text("")


def test_ps_shows_image_tag_when_repo_tag_still_exists(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    image_id = "1234567890abcdef1234567890abcdef"
    write_manifest(tmp_path / "qemu-compose" / "image" / image_id, image_id, ["repo:latest"])
    write_instance_meta(
        tmp_path / "qemu-compose" / "instance" / "inst-1234567890ab",
        name="vm1",
        image="repo:latest",
        image_id=image_id,
    )

    assert command_ps(show_all=True) == 0

    out = capsys.readouterr().out
    assert "repo:latest" in out


def test_ps_shows_current_repo_tag_when_stored_repo_tag_no_longer_exists(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    image_id = "abcdef1234567890abcdef1234567890"
    write_manifest(tmp_path / "qemu-compose" / "image" / image_id, image_id, ["repo:v2"])
    write_instance_meta(
        tmp_path / "qemu-compose" / "instance" / "inst-abcdef123456",
        name="vm2",
        image="repo:latest",
        image_id=image_id,
    )

    assert command_ps(show_all=True) == 0

    out = capsys.readouterr().out
    assert "repo:v2" in out
    assert "repo:latest" not in out


def test_ps_shows_current_repo_tag_when_stored_image_is_id(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    image_id = "fedcba1234567890fedcba1234567890"
    write_manifest(tmp_path / "qemu-compose" / "image" / image_id, image_id, ["repo:latest"])
    write_instance_meta(
        tmp_path / "qemu-compose" / "instance" / "inst-fedcba123456",
        name="vm3",
        image=image_id,
        image_id=image_id,
    )

    assert command_ps(show_all=True) == 0

    out = capsys.readouterr().out
    assert "repo:latest" in out
    assert image_id[:12] not in out


def test_ps_shows_short_image_id_when_manifest_has_no_repo_tags(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    image_id = "0123456789abcdef0123456789abcdef"
    write_manifest(tmp_path / "qemu-compose" / "image" / image_id, image_id, [])
    write_instance_meta(
        tmp_path / "qemu-compose" / "instance" / "inst-0123456789ab",
        name="vm4",
        image=image_id,
        image_id=image_id,
    )

    assert command_ps(show_all=True) == 0

    out = capsys.readouterr().out
    assert image_id[:12] in out
