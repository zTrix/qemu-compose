from typing import List
import os
import uuid

from qemu_compose.instance.ssh_key import (
    _load_ecc,
    _openssh_private_key_from_ecc,
    _write_private_key,
    ensure_openssh_private_key,
    load_private_key,
    public_key_bytes,
)


def new_random_vmid(instance_root: str) -> str:
    return uuid.uuid4().bytes.hex()


def prepare_ssh_key(instance_dir: str, vmid: str) -> bytes:
    priv_key_path = os.path.join(instance_dir, "ssh-key")
    pub_key_path = os.path.join(instance_dir, "ssh-key.pub")

    if os.path.exists(priv_key_path):
        # Older qemu-compose versions wrote a PKCS#8 PEM private key, which
        # OpenSSH's "ssh -i" cannot read.  Convert it in place.
        ensure_openssh_private_key(instance_dir)

        if os.path.exists(pub_key_path):
            with open(pub_key_path, "rb") as pf:
                return pf.read()

        # The public key file is missing; derive it from the existing key
        # instead of replacing the pair with a new one.
        key = load_private_key(priv_key_path)
        pub_bytes = public_key_bytes(key, vmid)
        with open(pub_key_path, "wb") as pf:
            pf.write(pub_bytes)
        return pub_bytes

    # create new key pair using PyCryptodome
    key = _load_ecc().generate(curve="ed25519")
    priv_key = _openssh_private_key_from_ecc(key)
    _write_private_key(priv_key_path, priv_key)

    pub_bytes = public_key_bytes(key, vmid)
    with open(pub_key_path, "wb") as pf:
        pf.write(pub_bytes)

    return pub_bytes


def list_instance_ids(instance_root: str) -> List[str]:
    try:
        return sorted(
            [d for d in os.listdir(instance_root) if os.path.isdir(os.path.join(instance_root, d))]
        )
    except FileNotFoundError:
        return []
