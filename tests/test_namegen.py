"""Name pools: deep enough, coherent, and not a current NHL roster.

Playtest report: "Name pool looks shallow, a lot of surname repeats of current NHL names."

Three separate problems behind that, of which the third was the one actually complained about:

1. **Too small.** 223 first and 289 last names against 700+ players per league.
2. **Incoherent pairing.** First and last were drawn from unrelated flat tuples, so leagues were
   full of men called "Miro Gagnon" and "Jean-Sebastien Ovechkin".
3. **It read as a current NHL roster.** An explicit block commented "recognizable hockey name seed
   set" -- McDavid, Crosby, Matthews, Draisaitl, MacKinnon -- plus more seeded through the national
   blocks (Ovechkin, Pastrnak, Selanne, Chara, Kaprizov...).
"""
import re
from collections import Counter

from pucksim.gen import namegen as N
from pucksim.gen.leaguegen import build_world
from pucksim.models.world import World
from pucksim.rng import Rng


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------
def test_every_nationality_has_weights_a_label_and_both_pools():
    assert set(N.NAME_POOLS) == set(N.NATIONALITY_WEIGHTS) == set(N.NATIONALITY_NAMES)
    for code, pools in N.NAME_POOLS.items():
        assert pools["first"], code
        assert pools["last"], code
        assert N.NATIONALITY_WEIGHTS[code] > 0, code


def test_no_pool_contains_a_duplicate():
    """A duplicate inside a tuple silently doubles that name's draw odds."""
    for code, pools in N.NAME_POOLS.items():
        for kind in ("first", "last"):
            counts = Counter(pools[kind])
            repeated = [name for name, n in counts.items() if n > 1]
            assert not repeated, f"{code}/{kind} repeats {repeated}"


def test_the_pools_are_deep_enough_for_a_league():
    """The whole point of the expansion. A 32-team league is 700+ players plus farm systems."""
    first = sum(len(p["first"]) for p in N.NAME_POOLS.values())
    last = sum(len(p["last"]) for p in N.NAME_POOLS.values())
    assert first >= 600, f"only {first} first names"
    assert last >= 1200, f"only {last} last names"
    pairs = sum(len(p["first"]) * len(p["last"]) for p in N.NAME_POOLS.values())
    assert pairs >= 150_000, f"only {pairs} coherent combinations"


def test_names_contain_no_stray_whitespace_or_empty_entries():
    for code, pools in N.NAME_POOLS.items():
        for kind in ("first", "last"):
            for name in pools[kind]:
                assert name and name == name.strip(), f"{code}/{kind}: {name!r}"
                assert not re.search(r"\s\s", name), f"{code}/{kind}: {name!r}"


# ---------------------------------------------------------------------------
# The purge
# ---------------------------------------------------------------------------
# Deliberately NOT an exhaustive list of NHL surnames -- see namegen's docstring on why that goal
# is incoherent. These are names distinctive enough to read as a reference to one specific real
# person, which is the actual complaint.
_MARQUEE = {
    "McDavid", "Crosby", "Matthews", "Draisaitl", "MacKinnon", "Marner", "Makar", "Werenski",
    "Kreider", "Zibanejad", "Marchand", "Hellebuyck", "Bobrovsky", "Caufield", "Tavares",
    "Nylander", "Stamkos", "Toews", "DeBrincat", "Guentzel", "Letang", "Chychrun", "Eichel",
    "Pavelski", "Oettinger", "Landeskog", "Kucherov", "Ovechkin", "Vasilevskiy", "Shesterkin",
    "Malkin", "Panarin", "Kaprizov", "Datsyuk", "Pastrnak", "Necas", "Svechnikov", "Voracek",
    "Slafkovsky", "Chara", "Halak", "Gudas", "Rantanen", "Heiskanen", "Barkov", "Kotkaniemi",
    "Saros", "Koivu", "Selanne", "Forsberg", "Hedman", "Josi", "Pettersson", "Backstrom",
    "Hischier", "Lemieux", "Lafleur", "Vezina", "Plante", "Dionne", "Bourque", "Savard",
    "Sundin", "Salming", "Rinne", "Larionov", "Tarasov", "Gaudreau", "Sekera", "Tatar",
}

# Famous for something other than hockey. A generated league should not contain a US president,
# a novelist or a race-car driver either.
_NON_HOCKEY_FAMOUS = {
    "Coolidge", "Fillmore", "Garfield", "Revere", "Rothschild", "Roddenberry", "Selleck",
    "Earnhardt", "Hawthorne", "Presley", "Orwell", "Tennyson", "Kafka", "Zizka", "Masaryk",
    "Turgenev", "Trudeau", "Longstreet",
}


def test_no_marquee_nhl_name_survives():
    found = [(code, kind, name)
             for code, pools in N.NAME_POOLS.items()
             for kind in ("first", "last")
             for name in pools[kind]
             if name in _MARQUEE]
    assert not found, f"marquee names still in the pools: {found}"


def test_no_name_famous_for_something_other_than_hockey():
    found = [(code, kind, name)
             for code, pools in N.NAME_POOLS.items()
             for kind in ("first", "last")
             for name in pools[kind]
             if name in _NON_HOCKEY_FAMOUS]
    assert not found, f"non-hockey-famous names still in the pools: {found}"


def test_ordinary_high_frequency_surnames_are_deliberately_kept():
    """The counterpart guard. The rule is distinctiveness, not overlap: there is an NHL Smith and
    an NHL Roy, and purging every common surname of every hockey nation would leave pools of
    nothing but rare names, which reads MORE artificial. If someone later 'fixes' that, this
    fails and points them at the docstring."""
    quebec = set(N.NAME_POOLS["CAN-QC"]["last"])
    assert {"Tremblay", "Roy", "Gagnon", "Cote"} <= quebec
    assert "Karlsson" in set(N.NAME_POOLS["SWE"]["last"])
    assert {"Novak", "Novotny"} <= set(N.NAME_POOLS["CZE"]["last"])
    assert "Virtanen" in set(N.NAME_POOLS["FIN"]["last"])


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------
def test_a_name_is_always_drawn_from_one_nationality_pool():
    """The coherence fix. Every generated name must be a valid pairing, not a cross-pool hybrid."""
    rng = Rng(1)
    for _ in range(3000):
        name, code = N.random_name(rng)
        first, last = name.split(" ", 1)
        assert first in N.NAME_POOLS[code]["first"], (name, code)
        assert last in N.NAME_POOLS[code]["last"], (name, code)


def test_nationality_mix_tracks_the_configured_weights():
    rng = Rng(2)
    counts = Counter(N.random_nationality(rng) for _ in range(20_000))
    total = sum(N.NATIONALITY_WEIGHTS.values())
    for code, weight in N.NATIONALITY_WEIGHTS.items():
        expected = weight / total
        actual = counts[code] / 20_000
        assert abs(actual - expected) < 0.02, f"{code}: {actual:.3f} vs expected {expected:.3f}"


def test_canada_and_the_usa_dominate_as_they_do_in_the_real_nhl():
    rng = Rng(3)
    counts = Counter(N.random_nationality(rng) for _ in range(10_000))
    north_american = (counts["CAN"] + counts["CAN-QC"] + counts["USA"]) / 10_000
    assert 0.65 <= north_american <= 0.78, north_american


def test_pool_size_does_not_move_the_rng_stream():
    """Why draws use ``pool[int(rng.random() * len(pool))]`` rather than ``rng.choice(pool)``.
    ``random.choice`` consumes a variable number of bits by sequence length, so under it adding a
    single name shifted every downstream draw -- ratings, ages, everything, since they share one
    Rng. This is what makes future name additions cheap."""
    def stream_after_draw(pool_size):
        rng = Rng(7)
        N._draw(rng, tuple(f"N{i}" for i in range(pool_size)))
        return [rng.random() for _ in range(5)]

    assert stream_after_draw(10) == stream_after_draw(1000)


def test_duplicate_names_are_re_rolled_when_a_used_set_is_given():
    rng = Rng(4)
    used = set()
    for _ in range(400):
        N.random_name(rng, used)
    assert len(used) == 400, f"{400 - len(used)} collisions accepted"


def test_a_collision_re_draws_the_nationality_too():
    """Retrying within one nationality would bias a small pool's nationality upward every time it
    collided -- Latvia has ~75 surnames, so it would collide far more often than Canada."""
    rng = Rng(5)
    saved = (N.NAME_POOLS, N._NAT_CODES, N._NAT_CUMULATIVE, N._NAT_TOTAL)
    try:
        # "XXX" can only ever produce one name, and it is already taken. "YYY" has room. If the
        # retry kept the nationality it drew first, every XXX draw would burn all six attempts and
        # hand back the taken name.
        N.NAME_POOLS = {
            "XXX": {"first": ("Aaa",), "last": ("Bbb",)},
            "YYY": {"first": tuple(f"F{i}" for i in range(50)),
                    "last": tuple(f"L{i}" for i in range(50))},
        }
        N._NAT_CODES = ("XXX", "YYY")
        N._NAT_CUMULATIVE = (1.0, 2.0)
        N._NAT_TOTAL = 2.0

        used = {"Aaa Bbb"}
        returned_taken = sum(1 for _ in range(200)
                             if N.random_name(rng, used)[0] == "Aaa Bbb")
        # If the nationality were held fixed across retries, ~50% of draws (the XXX half) would
        # exhaust all six attempts and hand back the taken name. Re-drawing it makes that
        # 0.5 ** 6, about 1.6%. The threshold sits well between those two, not at zero -- the
        # bounded-retry fallback is allowed to give up occasionally, by design.
        assert returned_taken < 25, f"{returned_taken} of 200 draws returned the used name"
    finally:
        N.NAME_POOLS, N._NAT_CODES, N._NAT_CUMULATIVE, N._NAT_TOTAL = saved


# ---------------------------------------------------------------------------
# End to end through world generation
# ---------------------------------------------------------------------------
def test_a_generated_league_has_no_duplicate_names():
    world = build_world(seed=7)
    names = [p.name for p in world.players.values()]
    duplicates = [n for n, c in Counter(names).items() if c > 1]
    assert not duplicates, f"{len(duplicates)} duplicated names, e.g. {duplicates[:5]}"


def test_every_generated_player_has_a_coherent_nationality():
    world = build_world(seed=7)
    for player in world.players.values():
        assert player.nationality in N.NAME_POOLS, (player.name, player.nationality)
        first, last = player.name.split(" ", 1)
        pools = N.NAME_POOLS[player.nationality]
        assert first in pools["first"] and last in pools["last"], player.name


def test_a_generated_league_is_nationally_mixed():
    world = build_world(seed=7)
    counts = Counter(p.nationality for p in world.players.values())
    assert len(counts) >= 10, f"only {len(counts)} nationalities represented: {counts}"
    assert counts.most_common(1)[0][1] < len(world.players) * 0.5


def test_nationality_survives_a_save_load_round_trip():
    world = build_world(seed=7)
    reloaded = World.from_dict(world.to_dict())
    for pid, player in world.players.items():
        assert reloaded.players[pid].nationality == player.nationality


def test_a_save_written_before_nationality_existed_still_loads():
    world = build_world(seed=7)
    data = world.to_dict()
    for player_data in data["players"].values():
        player_data.pop("nationality", None)
    reloaded = World.from_dict(data)
    assert all(p.nationality == "CAN" for p in reloaded.players.values())


def test_the_used_name_set_is_rebuilt_on_load_rather_than_serialized():
    """It is derived state. A persisted copy could drift out of sync with ``players``; a rebuilt
    one cannot, and old saves get a correct one for free."""
    world = build_world(seed=7)
    data = world.to_dict()
    assert "used_player_names" not in data
    reloaded = World.from_dict(data)
    assert reloaded.used_player_names == {p.name for p in reloaded.players.values()}
