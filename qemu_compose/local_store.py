
import random
import string
import os

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
