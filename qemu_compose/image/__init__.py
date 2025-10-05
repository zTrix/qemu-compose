from typing import List, Any, Optional, Dict
import datetime
import os
import json
from dataclasses import dataclass

from qemu_compose.utils.utcdatetime import parse_datetime

@dataclass(frozen=True)
class RepoTag:
    repo: str
    tag: str

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
    disks: List[List[str]]
    qemu_config: Dict[str, Any]
    qemu_args: List[str]
    digest: str
    comment: Optional[str]

    @classmethod
    def load_file(cls, image_dir: str) -> "ImageManifest":
        with open(os.path.join(image_dir, "manifest.json")) as f:
            obj = json.load(f)
        return cls.from_dict(obj)

    @classmethod
    def from_dict(cls, obj: dict) -> "ImageManifest":

        image_id = str(obj.get("id") or "")

        architecture = str(obj.get("architecture") or "")
        os_name = str(obj.get("os") or "")
        created = parse_datetime(obj.get("created"))

        repo_tags_raw = obj.get("repo_tags") or []
        repo_tags = [RepoTag.from_str(t) for t in repo_tags_raw if isinstance(t, str)]

        disks_raw = obj.get("disks") or []
        disks: List[List[str]] = []
        for item in disks_raw:
            if isinstance(item, list):
                disks.append([str(x) for x in item])

        qemu_config_raw = obj.get("qemu_config")
        qemu_config: Dict[str, Any] = qemu_config_raw if isinstance(qemu_config_raw, dict) else {}

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
            qemu_config=qemu_config,
            qemu_args=qemu_args,
            digest=digest,
            comment=comment,
        )
