from __future__ import annotations

import json
import sys
import types
from pathlib import Path

try:
    from Crypto.PublicKey import ECC as _ECC  # noqa: F401
except Exception:
    crypto_module = types.ModuleType("Crypto")
    crypto_public_key_module = types.ModuleType("Crypto.PublicKey")
    crypto_public_key_module.ECC = object()
    sys.modules.setdefault("Crypto", crypto_module)
    sys.modules.setdefault("Crypto.PublicKey", crypto_public_key_module)

from qemu_compose.cmd.run_command import command_run


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


def test_run_preserves_named_image_in_config(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    image_id = "1234567890abcdef1234567890abcdef"
    write_manifest(tmp_path / "qemu-compose" / "image" / image_id, image_id, ["repo:latest"])

    configs = []

    class FakeRunner:
        def __init__(self, config, store, cwd):
            configs.append(config)
            self.instance_dir = str(tmp_path / "instance")
            Path(self.instance_dir).mkdir()

        def check_and_lock(self):
            return 0

        def prepare_env(self):
            pass

        def prepare_storage(self):
            return 0

        def execute_script(self, name):
            pass

        def setup_qemu_args(self):
            pass

        def start(self):
            pass

        def interact(self):
            pass

        def is_running(self):
            return False

        def cleanup(self):
            pass

    monkeypatch.setattr("qemu_compose.cmd.run_command.QemuRunner", FakeRunner)

    assert command_run(image_hint="repo:latest", name="vm1") == 0
    assert configs[0].image == "repo:latest"


def test_run_expands_image_prefix_in_config(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    image_id = "abcdef1234567890abcdef1234567890"
    write_manifest(tmp_path / "qemu-compose" / "image" / image_id, image_id, ["repo:latest"])

    configs = []

    class FakeRunner:
        def __init__(self, config, store, cwd):
            configs.append(config)
            self.instance_dir = str(tmp_path / "instance")
            Path(self.instance_dir).mkdir()

        def check_and_lock(self):
            return 0

        def prepare_env(self):
            pass

        def prepare_storage(self):
            return 0

        def execute_script(self, name):
            pass

        def setup_qemu_args(self):
            pass

        def start(self):
            pass

        def interact(self):
            pass

        def is_running(self):
            return False

        def cleanup(self):
            pass

    monkeypatch.setattr("qemu_compose.cmd.run_command.QemuRunner", FakeRunner)

    assert command_run(image_hint="abcdef", name="vm1") == 0
    assert configs[0].image == image_id
