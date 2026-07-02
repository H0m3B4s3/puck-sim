"""Tests for pucksim.save.serialize and pucksim.save.store -- Step 1.13 done-criteria."""
from __future__ import annotations

from pucksim.gen.leaguegen import build_world
from pucksim.save import store
from pucksim.save.serialize import load_world, save_world, world_from_json, world_to_json
from pucksim.sim.season import advance_one_day, generate_schedule, start_season


# ---------------------------------------------------------------------------
# world_to_json / world_from_json round-trip
# ---------------------------------------------------------------------------
def test_world_to_json_from_json_byte_identical_round_trip():
    world = build_world(seed=1)
    text = world_to_json(world)
    restored = world_from_json(text)
    assert restored.to_dict() == world.to_dict()


def test_world_to_json_from_json_round_trip_after_partial_season():
    world = build_world(seed=2)
    start_season(world)
    for _ in range(3):
        if not world.schedule or all(g.played for g in world.schedule):
            break
        advance_one_day(world)

    text = world_to_json(world)
    restored = world_from_json(text)

    assert restored.to_dict() == world.to_dict()
    assert restored.day == world.day
    assert restored.phase == world.phase

    for tid, team in world.teams.items():
        rteam = restored.teams[tid]
        assert rteam.wins == team.wins
        assert rteam.losses == team.losses
        assert rteam.ot_losses == team.ot_losses

    for pid, player in world.players.items():
        rplayer = restored.players[pid]
        assert rplayer.season.to_dict() == player.season.to_dict()

    for g, rg in zip(world.schedule, restored.schedule):
        assert g.played == rg.played
        assert g.home_score == rg.home_score
        assert g.away_score == rg.away_score


# ---------------------------------------------------------------------------
# save_world / load_world file I/O wrappers
# ---------------------------------------------------------------------------
def test_save_world_load_world_round_trip(tmp_path):
    world = build_world(seed=3)
    path = tmp_path / "career.pucksim.json"
    save_world(world, str(path))
    restored = load_world(str(path))
    assert restored.to_dict() == world.to_dict()


# ---------------------------------------------------------------------------
# store.py -- save_game/load_game/autosave/list_saves/delete_save
# ---------------------------------------------------------------------------
def test_save_game_load_game_round_trip(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    world = build_world(seed=4)

    path = store.save_game(world, "my-career")
    assert path == store.slot_path("my-career")
    assert (tmp_path / "saves").is_dir()

    restored = store.load_game("my-career")
    assert restored.to_dict() == world.to_dict()


def test_autosave_uses_configured_slot(tmp_path, monkeypatch):
    from pucksim.config import AUTOSAVE_SLOT

    monkeypatch.chdir(tmp_path)
    world = build_world(seed=5)
    store.autosave(world)

    assert store.exists(AUTOSAVE_SLOT)
    restored = store.load_game(AUTOSAVE_SLOT)
    assert restored.to_dict() == world.to_dict()


def test_list_saves_returns_slot_names_without_suffix(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    world = build_world(seed=6)

    store.save_game(world, "slot-a")
    store.save_game(world, "slot-b")

    saves = store.list_saves()
    assert saves == sorted(["slot-a", "slot-b"])


def test_delete_save_removes_the_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    world = build_world(seed=7)

    store.save_game(world, "to-delete")
    assert store.exists("to-delete")

    store.delete_save("to-delete")
    assert not store.exists("to-delete")
    assert "to-delete" not in store.list_saves()


def test_delete_save_nonexistent_slot_is_a_no_op(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # Should not raise even though nothing was ever saved to this slot.
    store.delete_save("never-existed")


def test_saves_dir_created_relative_to_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    resolved = store.saves_dir()
    assert resolved == str(tmp_path / "saves")
    assert (tmp_path / "saves").is_dir()


def test_slot_path_slugifies_unsafe_characters(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = store.slot_path("My Career #1!")
    assert path.endswith(".pucksim.json")
    assert " " not in path
    assert "#" not in path
    assert "!" not in path
