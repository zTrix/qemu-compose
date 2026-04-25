
import os
from typing import Set

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

    def get_allocated_cids(self) -> Set[int]:
        """获取所有已分配的 CID（从所有 instance 的 cid 文件中读取）"""
        allocated = set()
        try:
            for instance_id in os.listdir(self.instance_root):
                cid_path = os.path.join(self.instance_root, instance_id, "cid")
                try:
                    with open(cid_path, "r") as f:
                        cid_str = f.read().strip()
                        if cid_str:
                            allocated.add(int(cid_str))
                except (FileNotFoundError, ValueError, IOError):
                    # 忽略没有 cid 文件或 cid 无效的 instance
                    pass
        except FileNotFoundError:
            pass
        return allocated
