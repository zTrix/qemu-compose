from __future__ import annotations

import json
from pathlib import Path

from qemu_compose.image import list_image, load_image_by_name, resolve_image_by_prefix


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


def test_image_store_ignores_dot_prefixed_workdirs(tmp_path):
    image_root = tmp_path / "image"
    image_id = "abcdef1234567890"
    write_manifest(image_root / image_id, image_id, ["repo:latest"])
    (image_root / ".pull-work-ghnw6tht" / "bundle" / "rootfs").mkdir(parents=True)

    rows = list_image(str(image_root))
    resolved_id, prefix_matches = resolve_image_by_prefix(str(image_root), ".pull")
    manifest = load_image_by_name(str(image_root), "repo:latest")

    assert len(rows) == 1
    assert rows[0][0] == "repo"
    assert rows[0][1] == "latest"
    assert rows[0][2] == image_id[:12]
    assert rows[0][4] == "0.0B"
    assert resolved_id is None
    assert prefix_matches == []
    assert manifest is not None
    assert manifest.id == image_id
