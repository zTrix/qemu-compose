from __future__ import annotations
from typing import Iterable, List, Tuple

from qemu_compose.local_store import LocalStore
from qemu_compose.image import list_image

def _print_table(rows: List[Tuple[str, str, str, str, str]]) -> None:
    headers = ["REPOSITORY", "TAG", "IMAGE ID", "CREATED", "SIZE"]

    def width(column: int) -> int:
        vals = [headers[column]] + [str(r[column]) for r in rows]
        return max(len(v) for v in vals)

    widths = [width(i) for i in range(len(headers))]

    def fmt_row(items: Iterable[str]) -> str:
        parts = [str(v).ljust(widths[i]) for i, v in enumerate(items)]
        return "  ".join(parts)

    print(fmt_row(headers))
    for r in rows:
        print(fmt_row(r))


def command_images() -> int:
    store = LocalStore()
    image_root = store.image_root
    rows = list_image(image_root)
    _print_table(rows)
    return 0
