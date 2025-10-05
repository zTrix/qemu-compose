from typing import List
import os
import random

from Crypto.PublicKey import ECC

def new_random_vmid(instance_root:str, charset=None, length=12) -> str:
    if charset is None:
        charset = "23456789abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ"

    while True:
        vmid = "".join(random.choices(charset, k=length))
        path = os.path.join(instance_root, vmid)
        if not os.path.exists(path):
            return vmid

def prepare_ssh_key(instance_dir:str, vmid:str) -> bytes:
    priv_key_path = os.path.join(instance_dir, "ssh-key")
    pub_key_path = os.path.join(instance_dir, "ssh-key.pub")

    # create new key pair using PyCryptodome
    key = ECC.generate(curve='ed25519')
    priv_pem = key.export_key(format='PEM')
    with open(priv_key_path, 'wb') as f:
        f.write(priv_pem.encode('ascii'))

    try:
        os.chmod(priv_key_path, 0o600)
    except Exception:
        pass

    pub_key = key.public_key()
    try:
        pub_str = pub_key.export_key(format='OpenSSH')
    except Exception as exc:
        raise RuntimeError("Unable to export Ed25519 public key in OpenSSH format") from exc

    pub_with_comment = (pub_str.strip() + ' ' + f'qemu-compose-{vmid}\n')
    pub_bytes = pub_with_comment.encode('utf-8')

    with open(pub_key_path, 'wb') as pf:
        pf.write(pub_bytes)

    return pub_bytes


def list_instance_ids(instance_root:str) -> List[str]:
    try:
        return sorted(
            [d for d in os.listdir(instance_root) if os.path.isdir(os.path.join(instance_root, d))]
        )
    except FileNotFoundError:
        return []
