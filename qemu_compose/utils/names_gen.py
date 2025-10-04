from __future__ import annotations

from typing import Dict, Any
import random
import string

__all__ = ["generate_unique_name"]


RANDOM_NAME_ADJECTIVES = (
    "agile",
    "brisk",
    "calm",
    "daring",
    "eager",
    "fancy",
    "gentle",
    "happy",
    "jolly",
    "kind",
    "lively",
    "merry",
    "nimble",
    "proud",
    "quick",
    "ready",
    "smart",
    "tidy",
    "upbeat",
    "vivid",
)

RANDOM_NAME_NOUNS = (
    "badger",
    "beacon",
    "clover",
    "comet",
    "falcon",
    "feather",
    "harbor",
    "heron",
    "island",
    "jungle",
    "meadow",
    "nebula",
    "otter",
    "prairie",
    "quartz",
    "ranger",
    "spruce",
    "talon",
    "valley",
    "willow",
)


def generate_unique_name(existing_names: Dict[str, Any]) -> str:
    max_attempts = len(RANDOM_NAME_ADJECTIVES) * len(RANDOM_NAME_NOUNS)
    for _ in range(max_attempts):
        candidate = "-".join(
            (
                random.choice(RANDOM_NAME_ADJECTIVES),
                random.choice(RANDOM_NAME_NOUNS),
            )
        )
        if candidate not in existing_names:
            return candidate

    alphabet = string.ascii_lowercase + string.digits
    while True:
        suffix = "".join(random.choices(alphabet, k=4))
        candidate = "-".join(
            (
                random.choice(RANDOM_NAME_ADJECTIVES),
                random.choice(RANDOM_NAME_NOUNS),
                suffix,
            )
        )
        if candidate not in existing_names:
            return candidate
