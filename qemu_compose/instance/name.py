from typing import Optional
import os

from qemu_compose.utils.names_gen import generate_unique_name

def check_and_get_name(instance_root: str, name: Optional[str]) -> str:
    # Collect existing VM names for duplicate detection and auto-generation
    existing_names = {}

    for entry in os.listdir(instance_root):
        entry_path = os.path.join(instance_root, entry)
        if not os.path.isdir(entry_path):
            continue

        name_path = os.path.join(entry_path, "name")
        if not os.path.exists(name_path):
            continue
        try:
            with open(name_path, "r") as nf:
                existing_name = nf.read().strip()
            if existing_name:
                existing_names[existing_name] = entry
        except OSError:
            # Ignore unreadable name files
            pass

    # Check duplicate VM name after locking instance_dir but before launch
    if name:
        if name in existing_names:
            raise ValueError(f"The VM name {name} is already in use by {existing_names.get(name)}")
    else:
        name = generate_unique_name(existing_names)

    return name
