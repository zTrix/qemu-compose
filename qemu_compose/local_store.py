
import random
import string
import os

from Crypto.PublicKey import Ed25519

def build_openssh_pub_from_raw(raw32: bytes) -> str:
    def _pack_ssh_string(b: bytes) -> bytes:
        return struct.pack('>I', len(b)) + b
    blob = _pack_ssh_string(b'ssh-ed25519') + _pack_ssh_string(raw32)
    return 'ssh-ed25519 ' + base64.b64encode(blob).decode('ascii')

class LocalStore:
    def __init__(self, name="qemu-compose"):
        user_data_dir = os.getenv("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
        self.data_dir = os.path.join(user_data_dir, name)
        os.makedirs(self.data_dir, exist_ok=True)

    @property
    def image_root(self):
        path = os.path.join(self.data_dir, "image")
        os.makedirs(path, exist_ok=True)
        return path

    def image_dir(self, image_name):
        path = os.path.join(self.image_root, image_name)
        os.makedirs(path, exist_ok=True)
        return path

    @property
    def instance_root(self):
        path = os.path.join(self.data_dir, "instance")
        os.makedirs(path, exist_ok=True)
        return path
    
    def instance_dir(self, vmid):
        path = os.path.join(self.instance_root, vmid)
        os.makedirs(path, exist_ok=True)
        return path

    def new_random_vmid(self, charset=None, length=12) -> str:
        if charset is None:
            charset = string.ascii_lowercase + string.digits
        while True:
            vmid = ''.join(random.choices(charset, k=length))
            path = os.path.join(self.instance_root, vmid)
            if not os.path.exists(path):
                os.makedirs(path)
                return vmid

    def instance_ssh_key_pub_path(self, vmid:str):
        return os.path.join(instance_dir, "ssh-key.pub")

    def instance_ssh_key_path(self, vmid:str):
        return os.path.join(instance_dir, "ssh-key")

    def prepare_ssh_key(self, vmid:str):
        priv_key_path = self.instance_ssh_key_path(vmid)
        pub_key_path = self.instance_ssh_key_pub_path(vmid)

        # create new key pair using PyCryptodome
        key = Ed25519.generate()
        priv_pem = key.export_key(format='PEM')
        with open(priv_key_path, 'wb') as f:
            f.write(priv_pem)

        try:
            os.chmod(priv_key_path, 0o600)
        except Exception:
            pass

        try:
            pub_str = key.public_key().export_key(format='OpenSSH')
        except Exception:
            raw = key.public_key().export_key(format='Raw')
            pub_str = build_openssh_pub_from_raw(raw)

        pub_with_comment = (pub_str + ' ' + f'qemu-compose-{vmid}')

        if not pub_with_comment.endswith('\n'):
            pub_with_comment += '\n'

        with open(pub_key_path, 'wb') as pf:
            pf.write(pub_with_comment.encode('ascii'))

        return key
