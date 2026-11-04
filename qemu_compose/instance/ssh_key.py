from __future__ import annotations

import base64
import os
import struct
from typing import Any


OPENSSH_PRIVATE_KEY_HEADER = b"-----BEGIN OPENSSH PRIVATE KEY-----"
PKCS8_PRIVATE_KEY_HEADER = b"-----BEGIN PRIVATE KEY-----"


def _load_ecc() -> Any:
    try:
        from Crypto.PublicKey import ECC
    except Exception:
        from Cryptodome.PublicKey import ECC
    return ECC


def _ssh_string(value: bytes) -> bytes:
    return struct.pack(">I", len(value)) + value


def export_openssh_ed25519_private_key(seed: bytes, public_key: bytes, comment: str = "") -> bytes:
    """Serialize an Ed25519 key as an unencrypted OpenSSH private key.

    PyCryptodome can only export Ed25519 private keys in PKCS#8 PEM format,
    which OpenSSH's ``ssh -i`` rejects.  Build the ``openssh-key-v1``
    container directly from the 32-byte seed and the 32-byte public key.
    """
    if len(seed) != 32:
        raise ValueError("Ed25519 seed must be 32 bytes")
    if len(public_key) != 32:
        raise ValueError("Ed25519 public key must be 32 bytes")

    key_type = b"ssh-ed25519"
    public_blob = _ssh_string(key_type) + _ssh_string(public_key)
    checkint = int.from_bytes(os.urandom(4), "big")

    private_blob = (
        struct.pack(">II", checkint, checkint)
        + _ssh_string(key_type)
        + _ssh_string(public_key)
        + _ssh_string(seed + public_key)
        + _ssh_string(comment.encode("utf-8"))
    )
    padding_len = 8 - (len(private_blob) % 8)
    private_blob += bytes(range(1, padding_len + 1))

    blob = (
        b"openssh-key-v1\0"
        + _ssh_string(b"none")
        + _ssh_string(b"none")
        + _ssh_string(b"")
        + struct.pack(">I", 1)
        + _ssh_string(public_blob)
        + _ssh_string(private_blob)
    )

    encoded = base64.b64encode(blob).decode("ascii")
    lines = [encoded[i : i + 70] for i in range(0, len(encoded), 70)]
    return (
        "-----BEGIN OPENSSH PRIVATE KEY-----\n"
        + "\n".join(lines)
        + "\n-----END OPENSSH PRIVATE KEY-----\n"
    ).encode("ascii")


def _openssh_private_key_from_ecc(key: Any, comment: str = "") -> bytes:
    if not key.has_private():
        raise ValueError("Cannot export a public key as an SSH private key")
    if key.curve != "Ed25519":
        raise ValueError("Unsupported SSH key type: %s" % key.curve)
    public_key = key.public_key().export_key(format="raw")
    return export_openssh_ed25519_private_key(key.seed, public_key, comment)


def public_key_bytes(key: Any, vmid: str) -> bytes:
    try:
        pub_str = key.public_key().export_key(format="OpenSSH")
    except Exception as exc:
        raise RuntimeError("Unable to export Ed25519 public key in OpenSSH format") from exc
    return (pub_str.strip() + " " + f"qemu-compose-{vmid}" + "\n").encode("utf-8")


def load_private_key(path: str) -> Any:
    ECC = _load_ecc()
    with open(path, "rb") as f:
        return ECC.import_key(f.read())


def _write_private_key(path: str, data: bytes) -> None:
    tmp_path = "%s.tmp.%d" % (path, os.getpid())
    fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def ensure_openssh_private_key(instance_dir: str) -> bool:
    """Convert a legacy PyCryptodome PKCS#8 key to OpenSSH format in place.

    Returns ``True`` when the key file was rewritten.
    """
    private_key_path = os.path.join(instance_dir, "ssh-key")
    try:
        with open(private_key_path, "rb") as f:
            data = f.read()
    except FileNotFoundError:
        return False

    if data.startswith(OPENSSH_PRIVATE_KEY_HEADER):
        return False
    if not data.startswith(PKCS8_PRIVATE_KEY_HEADER):
        return False

    try:
        key = _load_ecc().import_key(data)
        converted = _openssh_private_key_from_ecc(key)
    except Exception as exc:
        raise RuntimeError(
            "Unable to convert legacy SSH key %s to OpenSSH format" % private_key_path
        ) from exc

    _write_private_key(private_key_path, converted)
    return True
