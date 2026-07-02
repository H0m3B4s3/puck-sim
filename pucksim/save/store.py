"""Save-slot management on disk (under ``./saves/``).

Simplified vs. HoopR's ``hoopsim/save/store.py`` (60 lines): HoopR's version keys saves under a
per-session ``uid`` subfolder (``saves/{uid}/{slot}.json``) because its web layer supports multiple
concurrent browser sessions. Per DESIGN.md's explicit decision ("Local single-user app... No
accounts, auth, or database"), PuckSim has no session/uid concept at all -- this module uses a
flat ``saves/{slot}.pucksim.json`` layout with no extra directory layer. The ``.pucksim.json``
suffix matches ``.gitignore``'s ``*.pucksim.json`` pattern so save files never get accidentally
committed regardless of where ``saves_dir()`` resolves to.

``saves_dir()`` resolves ``config.SAVE_DIR_NAME`` ("saves") relative to the current working
directory (matching ``config.py``'s own comment: "created under the current working directory"),
mirroring HoopR's ``os.path.join(os.getcwd(), SAVE_DIR_NAME)`` exactly minus the uid segment.
"""
from __future__ import annotations

import os
import re
from typing import List

from pucksim.config import AUTOSAVE_SLOT, SAVE_DIR_NAME
from pucksim.models.world import World
from pucksim.save.serialize import load_world, save_world

_SUFFIX = ".pucksim.json"
_SLUG = re.compile(r"[^a-zA-Z0-9_-]+")


def saves_dir() -> str:
    """The saves directory (``./saves`` relative to the current working directory), created if
    it doesn't already exist."""
    path = os.path.join(os.getcwd(), SAVE_DIR_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def _slug(slot: str) -> str:
    return _SLUG.sub("_", slot.strip()) or "save"


def slot_path(slot: str) -> str:
    return os.path.join(saves_dir(), _slug(slot) + _SUFFIX)


def list_saves() -> List[str]:
    """Slot names (without the ``.pucksim.json`` suffix) present in ``saves_dir()``."""
    out = []
    for fname in sorted(os.listdir(saves_dir())):
        if fname.endswith(_SUFFIX):
            out.append(fname[: -len(_SUFFIX)])
    return out


def exists(slot: str) -> bool:
    return os.path.exists(slot_path(slot))


def save_game(world: World, slot: str) -> str:
    """Save ``world`` to ``slot``, returning the path written."""
    path = slot_path(slot)
    save_world(world, path)
    return path


def load_game(slot: str) -> World:
    return load_world(slot_path(slot))


def autosave(world: World) -> None:
    save_game(world, AUTOSAVE_SLOT)


def delete_save(slot: str) -> None:
    path = slot_path(slot)
    if os.path.exists(path):
        os.remove(path)
