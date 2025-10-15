from typing import List, Optional, Dict
import datetime
import os
import json
from dataclasses import dataclass

from qemu_compose.utils.utcdatetime import parse_datetime

@dataclass(frozen=True)
class DiskSpec:
    filename: str
    format: str
    opts: str

    @classmethod
    def from_array(cls, a: List[str]) -> "DiskSpec":
        if len(a) == 0:
            return None
        fmt = a[1] if len(a) > 1 else "qcow2"
        opts = a[2] if len(a) > 2 else ""
        return DiskSpec(filename=a[0], format=fmt, opts=opts)

    @classmethod
    def from_dict(cls, d:Dict[str, str]) -> "DiskSpec":
        return DiskSpec(
            filename=d.get("filename"),
            format=d.get("format"),
            opts=d.get("opts"),
        )

    def to_dict(self):
        return self.__dict__

@dataclass(frozen=True)
class RepoTag:
    repo: str
    tag: str

    def match_name(self, name: str) -> bool:
        if ':' in name:
            r, t = name.split(':', maxsplit=1)
            return self.repo == r and self.tag == t
        else:
            return self.repo == name and self.tag == 'latest'

    @classmethod
    def from_str(cls, s:str) -> "RepoTag":
        if ':' in s:
            r, t = s.split(':', maxsplit=1)
            return RepoTag(repo=r, tag=t)
        else:
            return RepoTag(repo=s, tag='latest')

@dataclass(frozen=True)
class ImageManifest:
    id: str
    architecture: str
    os: str
    created: datetime.datetime
    repo_tags: List[RepoTag]
    disks: List[DiskSpec]
    qemu_args: List[str]
    digest: str
    comment: Optional[str]

    @classmethod
    def load_file(cls, image_dir: str) -> "ImageManifest":
        with open(os.path.join(image_dir, "manifest.json")) as f:
            obj = json.load(f)
        return cls.from_dict(obj)
    
    def has_repo_tag(self, name: str) -> bool:
        for rt in self.repo_tags:
            if rt.match_name(name):
                return True
        return False

    @classmethod
    def from_dict(cls, obj: dict) -> "ImageManifest":

        image_id = str(obj.get("id") or "")

        architecture = str(obj.get("architecture") or "")
        os_name = str(obj.get("os") or "")
        created = parse_datetime(obj.get("created"))

        repo_tags_raw = obj.get("repo_tags") or []
        repo_tags = [RepoTag.from_str(t) for t in repo_tags_raw if isinstance(t, str)]

        disks_raw = obj.get("disks") or []
        disks: List[DiskSpec] = []
        for item in disks_raw:
            if isinstance(item, list):
                ds = DiskSpec.from_array(item)
                if ds:
                    disks.append(ds)

        qemu_args_raw = obj.get("qemu_args") or []
        qemu_args = [str(a) for a in qemu_args_raw if isinstance(a, (str, int, float))]

        digest = str(obj.get("digest") or "")
        comment_val = obj.get("comment")
        comment = str(comment_val) if isinstance(comment_val, (str, int, float)) else None

        return cls(
            id=image_id,
            architecture=architecture,
            os=os_name,
            created=created,
            repo_tags=repo_tags,
            disks=disks,
            qemu_args=qemu_args,
            digest=digest,
            comment=comment,
        )
