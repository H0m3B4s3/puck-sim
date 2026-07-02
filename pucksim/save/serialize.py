"""World (de)serialization with a schema-version envelope and migration hook.

Mirrors HoopR's ``hoopsim/save/serialize.py`` (34 lines) near-verbatim -- this pattern is entirely
sport-agnostic (DESIGN.md: "JSON save files with schema versioning + migration hook... matches the
'keep it simple' deployment decision"). ``migrate()`` is an identity no-op for
``schema_version == config.SCHEMA_VERSION`` (currently 1); it exists now purely as a documented
hook so a future schema change has one obvious place to add an upgrade step, without needing to
touch ``World.from_dict()`` itself.
"""
from __future__ import annotations

import json

from pucksim.config import SCHEMA_VERSION
from pucksim.models.world import World


def migrate(data: dict) -> dict:
    """Upgrade an older save dict to the current schema. Identity for the current version.

    Future migrations follow HoopR's pattern: ``while version < SCHEMA_VERSION: ...; version += 1``,
    each step transforming ``data`` in place to match the next schema version's expected shape.
    No such migration exists yet since ``SCHEMA_VERSION`` has never changed.
    """
    version = data.get("schema_version", 1)
    data["schema_version"] = SCHEMA_VERSION if version > SCHEMA_VERSION else version
    return data


def world_to_json(world: World) -> str:
    return json.dumps(world.to_dict())


def world_from_json(text: str) -> World:
    data = migrate(json.loads(text))
    return World.from_dict(data)


def save_world(world: World, path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(world_to_json(world))


def load_world(path: str) -> World:
    with open(path, "r", encoding="utf-8") as fh:
        return world_from_json(fh.read())
