from __future__ import annotations

import base64
import os
import shutil
import struct
import subprocess

import pytest

from qemu_compose.instance import prepare_ssh_key
from qemu_compose.instance.ssh_key import (
    ensure_openssh_private_key,
    export_openssh_ed25519_private_key,
)

# RFC 8032, section 7.1, test vector 1
ED25519_SEED = bytes.fromhex(
    "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"
)
ED25519_PUBLIC_KEY = bytes.fromhex(
    "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
)


def _public_key_line(public_key: bytes) -> str:
    key_type = b"ssh-ed25519"
    blob = struct.pack(">I", len(key_type)) + key_type
    blob += struct.pack(">I", len(public_key)) + public_key
    return "ssh-ed25519 " + base64.b64encode(blob).decode("ascii")


def _write_private_key(path, data: bytes) -> None:
    path.write_bytes(data)
    os.chmod(path, 0o600)


def _ssh_keygen_public_key(path):
    ssh_keygen = shutil.which("ssh-keygen")
    if not ssh_keygen:
        pytest.skip("ssh-keygen is not installed")

    result = subprocess.run(
        [ssh_keygen, "-y", "-f", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return " ".join(result.stdout.split()[:2])


def test_export_openssh_ed25519_private_key_has_standard_size():
    data = export_openssh_ed25519_private_key(ED25519_SEED, ED25519_PUBLIC_KEY)

    assert data.startswith(b"-----BEGIN OPENSSH PRIVATE KEY-----\n")
    assert data.endswith(b"-----END OPENSSH PRIVATE KEY-----\n")
    # This is the size of the OpenSSH files produced by ssh-keygen.
    assert len(data) == 387


def test_exported_key_is_accepted_by_ssh_keygen(tmp_path):
    key_path = tmp_path / "ssh-key"
    _write_private_key(
        key_path,
        export_openssh_ed25519_private_key(ED25519_SEED, ED25519_PUBLIC_KEY),
    )

    assert _ssh_keygen_public_key(key_path) == _public_key_line(ED25519_PUBLIC_KEY)


def test_prepare_ssh_key_generates_openssh_private_key(tmp_path):
    pytest.importorskip("Crypto.PublicKey.ECC")

    pub_bytes = prepare_ssh_key(str(tmp_path), "a" * 32)
    key_path = tmp_path / "ssh-key"
    private_key = key_path.read_bytes()

    assert private_key.startswith(b"-----BEGIN OPENSSH PRIVATE KEY-----\n")
    assert len(private_key) == 387
    assert os.stat(key_path).st_mode & 0o777 == 0o600
    assert _ssh_keygen_public_key(key_path) == " ".join(pub_bytes.decode().split()[:2])


def test_ensure_openssh_private_key_converts_legacy_pkcs8(tmp_path):
    ECC = pytest.importorskip("Crypto.PublicKey.ECC")

    key = ECC.generate(curve="ed25519")
    public_key = key.public_key().export_key(format="OpenSSH").strip()
    key_path = tmp_path / "ssh-key"
    _write_private_key(key_path, key.export_key(format="PEM").encode("ascii"))

    assert ensure_openssh_private_key(str(tmp_path)) is True

    converted = key_path.read_bytes()
    assert converted.startswith(b"-----BEGIN OPENSSH PRIVATE KEY-----\n")
    assert len(converted) == 387
    assert os.stat(key_path).st_mode & 0o777 == 0o600
    assert _ssh_keygen_public_key(key_path) == public_key

    # Already converted keys are left untouched.
    assert ensure_openssh_private_key(str(tmp_path)) is False
