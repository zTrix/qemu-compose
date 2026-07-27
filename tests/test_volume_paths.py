from __future__ import annotations

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

from qemu_compose.instance.qemu_runner import resolve_volume_spec


def test_relative_volume_source_resolves_from_compose_directory(tmp_path, monkeypatch):
    compose_dir = tmp_path / "project"
    process_dir = tmp_path / "elsewhere"
    compose_dir.mkdir()
    process_dir.mkdir()
    monkeypatch.chdir(process_dir)

    assert resolve_volume_spec("./data:/mnt/data", str(compose_dir)) == (
        str(compose_dir / "data"),
        "/mnt/data",
        False,
    )


def test_absolute_volume_source_is_preserved(tmp_path):
    source = tmp_path / "data"

    assert resolve_volume_spec(f"{source}:/mnt/data:ro", "/unused") == (
        str(source),
        "/mnt/data",
        True,
    )


def test_parent_relative_volume_source_is_normalized(tmp_path):
    compose_dir = tmp_path / "project" / "compose"
    compose_dir.mkdir(parents=True)

    assert resolve_volume_spec("../data:/mnt/data", str(compose_dir)) == (
        str(tmp_path / "project" / "data"),
        "/mnt/data",
        False,
    )
