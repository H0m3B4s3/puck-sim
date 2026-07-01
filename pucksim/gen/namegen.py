"""Procedural name generation from small pooled name lists.

Mirrors the *pattern* of HoopR's ``hoopsim/gen/namegen.py`` (69 lines) --
weighted first/last name pools drawn from the shared, seedable
:class:`~pucksim.rng.Rng` -- but considerably simplified: HoopR loads its
pools from an external ``data/names.json`` and does dedup-retry + rare
generational suffixes (Jr./II/III/IV/V). PuckSim doesn't need that level of
flavor investment for MVP (DEVPLAN.md explicitly scopes gen's name/city/coach
flavor text as illustrative, not final content), so the pools below are
small, inline Python tuples -- plenty of hockey-plausible names for a 32-team
league's worth of generation without an external data file, and no dedup
bookkeeping (exact-duplicate names across a 700+ player league are harmless
cosmetic noise, not a correctness concern).

Determinism note: like HoopR, the pools are part of the reproducibility
surface -- a fixed pool + fixed seed reproduces a league's names exactly, but
editing the pools shifts every draw downstream of the first name pick
(ratings, ages, etc., since they all share one `Rng` stream). Don't edit
these pools and expect old seeds to keep producing identical rosters.
"""
from __future__ import annotations

from pucksim.rng import Rng

FIRST_NAMES = (
    "Connor", "Jack", "Nathan", "Nico", "Tyler", "Ryan", "Cole", "Owen",
    "Mason", "Logan", "Brayden", "Carter", "Dylan", "Hunter", "Wyatt",
    "Elias", "Lucas", "Noah", "Ethan", "Liam", "Aiden", "Jacob", "Gavin",
    "Blake", "Colton", "Riley", "Jaxon", "Cameron", "Parker", "Chase",
    "Miro", "Filip", "Erik", "Viktor", "Anton", "Nikolai", "Sebastian",
    "Oskar", "Henrik", "Gustav", "Mikael", "Lars", "Axel", "Rasmus",
    "Petr", "Jakub", "Tomas", "David", "Marek", "Andrej", "Juraj",
    "Kirill", "Ivan", "Pavel", "Dmitri", "Alexei", "Yegor", "Artemi",
    "Matthew", "Andrew", "Joshua", "Jack", "William", "James", "Zachary",
    "Brady", "Braden", "Trevor", "Spencer", "Tanner", "Austin", "Corey",
    "Marc-Andre", "Jean-Sebastien", "Pierre-Luc", "Alexandre", "Mathieu",
    "Samuel", "Gabriel", "Xavier", "Antoine", "Olivier",
)

LAST_NAMES = (
    "McDavid", "Crosby", "Ovechkin", "Matthews", "Draisaitl", "MacKinnon",
    "Kucherov", "Pastrnak", "Marner", "Hughes", "Rantanen", "Barkov",
    "Point", "Makar", "Werenski", "Hedman", "Karlsson", "Josi", "Fox",
    "Heiskanen", "Nurse", "Chabot", "Weber", "Ellis", "Larkin", "Aho",
    "Kreider", "Zibanejad", "Panarin", "Trocheck", "Bergeron", "Marchand",
    "Rask", "Vasilevskiy", "Shesterkin", "Hellebuyck", "Saros", "Swayman",
    "Novak", "Sorokin", "Fleury", "Bobrovsky", "Price", "Andersen",
    "Gallagher", "Suzuki", "Caufield", "Hutson", "Dach", "Slafkovsky",
    "Nyquist", "Larsson", "Ekholm", "Lindholm", "Pettersson", "Boeser",
    "Hughes", "Miller", "Horvat", "Necas", "Svechnikov", "Teravainen",
    "Jarvis", "Kotkaniemi", "Domi", "Tavares", "Nylander", "Marner",
    "Rielly", "Bunting", "Knies", "Cirelli", "Kucherov", "Stamkos",
    "Perry", "Toews", "Kane", "DeBrincat", "Bertuzzi", "Copp",
    "Zegras", "Terry", "Trouba", "Fiala", "Guentzel", "Malkin",
    "Letang", "Rakell", "Karlsson", "Chychrun", "Schmidt", "Eichel",
    "Karlsson", "Stone", "Pacioretty", "Hague", "Dorofeyev", "Barbashev",
    "Robertson", "Hintz", "Pavelski", "Oettinger", "Wyman", "Lindgren",
    "Meier", "Faksa", "Duchene", "Rantanen", "Landeskog", "Toews",
    "Cale", "Newhook", "Girard", "Byram", "Sturm", "Lehkonen",
)


def random_name(rng: Rng) -> str:
    """Pick a first and last name via ``rng.choice()`` and return "First Last"."""
    first = rng.choice(FIRST_NAMES)
    last = rng.choice(LAST_NAMES)
    return f"{first} {last}"
