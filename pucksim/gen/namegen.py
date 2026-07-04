"""Procedural name generation from pooled name lists.

Mirrors the *pattern* of HoopR's ``hoopsim/gen/namegen.py`` -- weighted
first/last name pools drawn from the shared, seedable
:class:`~pucksim.rng.Rng` -- but considerably simplified: HoopR loads its
pools from an external ``data/names.json`` and does dedup-retry + rare
generational suffixes (Jr./II/III/IV/V). PuckSim doesn't need that level of
flavor investment for MVP (DEVPLAN.md explicitly scopes gen's name/city/coach
flavor text as illustrative, not final content), so the pools below are
inline Python tuples covering the mix of nationalities common in pro hockey
(North American, Scandinavian, Czech/Slovak, Russian, Finnish, German,
Swiss, French-Canadian) -- wide enough that a 32-team league's worth of
generation (700+ players) doesn't feel like it's drawing from the same
handful of names -- and no dedup bookkeeping (exact-duplicate names across
a league that size are harmless cosmetic noise, not a correctness concern).

Determinism note: like HoopR, the pools are part of the reproducibility
surface -- a fixed pool + fixed seed reproduces a league's names exactly, but
editing the pools shifts every draw downstream of the first name pick
(ratings, ages, etc., since they all share one `Rng` stream). Don't edit
these pools and expect old seeds to keep producing identical rosters.
"""
from __future__ import annotations

from pucksim.rng import Rng

FIRST_NAMES = (
    # North American
    "Connor", "Jack", "Nathan", "Tyler", "Ryan", "Cole", "Owen",
    "Mason", "Logan", "Brayden", "Carter", "Dylan", "Hunter", "Wyatt",
    "Lucas", "Noah", "Ethan", "Liam", "Aiden", "Jacob", "Gavin",
    "Blake", "Colton", "Riley", "Jaxon", "Cameron", "Parker", "Chase",
    "Matthew", "Andrew", "Joshua", "William", "James", "Zachary",
    "Brady", "Braden", "Trevor", "Spencer", "Tanner", "Austin", "Corey",
    "Nolan", "Cooper", "Landon", "Bennett", "Griffin", "Hayden", "Grady",
    "Marcus", "Derek", "Kyle", "Brett", "Shane", "Travis", "Dawson",
    "Keegan", "Reid", "Beau", "Trent", "Garrett", "Colby", "Bryce",
    "Devon", "Jordan", "Curtis", "Adam", "Nick", "Sean", "Justin",
    "Michael", "Christopher", "Daniel", "Anthony", "Kevin", "Brandon",
    "Tyson", "Wade", "Clayton", "Elliot", "Jared", "Peyton", "Deacon",
    # French-Canadian
    "Marc-Andre", "Jean-Sebastien", "Pierre-Luc", "Alexandre", "Mathieu",
    "Samuel", "Gabriel", "Xavier", "Antoine", "Olivier", "Etienne",
    "Nicolas", "Frederic", "Maxime", "Simon", "Louis", "Charles",
    "Philippe", "Vincent", "Jean-Francois", "Guillaume", "Sebastien",
    "Yannick", "Dominic", "Francois",
    # Scandinavian (Swedish/Norwegian/Danish)
    "Erik", "Viktor", "Anton", "Nikolai", "Sebastian", "Oskar", "Henrik",
    "Gustav", "Mikael", "Lars", "Axel", "Rasmus", "Elias", "Filip",
    "Emil", "Fredrik", "Johan", "Magnus", "Niklas", "Robin", "Simon",
    "Jesper", "Anders", "Karl", "Olof", "Per", "Bjorn", "Adam",
    "William", "Hugo", "Leo", "Isak", "Vilhelm", "August",
    # Finnish
    "Miro", "Mikko", "Sami", "Kalle", "Aleksi", "Antti", "Joonas",
    "Juho", "Roope", "Tuomas", "Vesa", "Otto", "Onni", "Eetu",
    "Iiro", "Niklas", "Toni", "Valtteri", "Santeri", "Rasmus",
    # Czech / Slovak
    "Petr", "Jakub", "Tomas", "David", "Marek", "Andrej", "Juraj",
    "Milan", "Radek", "Filip", "Ondrej", "Vojtech", "Lukas", "Michal",
    "Ladislav", "Roman", "Stepan", "Zdenek", "Adam", "Dominik", "Martin",
    # Russian / Eastern European
    "Kirill", "Ivan", "Pavel", "Dmitri", "Alexei", "Yegor", "Artemi",
    "Nikita", "Vladimir", "Sergei", "Andrei", "Maxim", "Grigori",
    "Ilya", "Vyacheslav", "Yevgeni", "Konstantin", "Semyon", "Danil",
    "Timofey", "Arseni",
    # German / Swiss / Austrian
    "Lukas", "Leon", "Tim", "Felix", "Maximilian", "Jonas", "Niklas",
    "Julian", "Moritz", "Simon", "Nico", "Timo", "Kai", "Dario",
    "Sven", "Reto", "Denis", "Yannick", "Luca", "Marco",
)

LAST_NAMES = (
    # North American / common Anglo surnames
    "Anderson", "Bennett", "Carlson", "Dawson", "Ellison", "Foster",
    "Graham", "Harrison", "Ingram", "Jenkins", "Keller", "Lawson",
    "Mitchell", "Nelson", "Ogden", "Parsons", "Quincy", "Reeves",
    "Sawyer", "Turner", "Underwood", "Vance", "Walsh", "Yates",
    "Bishop", "Chandler", "Donovan", "Ferris", "Gallagher", "Hutchins",
    "Ivers", "Jasper", "Kingston", "Lambert", "Morrow", "Norris",
    "Osborne", "Prentice", "Quimby", "Roberts", "Shepherd", "Thornton",
    "Upton", "Vaughn", "Whitfield", "Yardley", "Zimmerman", "Abbott",
    "Bradshaw", "Crawford", "Dempsey", "Emerson", "Fletcher", "Griggs",
    "Hollis", "Ibsen", "Jorgensen", "Kessler", "Larkin", "Mercer",
    "Nash", "Oakley", "Pemberton", "Quill", "Ramsey", "Stafford",
    "Tremblay", "Vickers", "Warfield", "Yeoman", "Ashford", "Barlow",
    "Cormier", "Dresden", "Ellery", "Farrow", "Gladwin", "Hargrove",
    # French-Canadian
    "Gagnon", "Roy", "Cote", "Bouchard", "Gauthier", "Morin", "Lavoie",
    "Fortin", "Gagne", "Ouellet", "Pelletier", "Belanger", "Levesque",
    "Bergeron", "Boucher", "Caron", "Desjardins", "Dube", "Fournier",
    "Gosselin", "Lachance", "Lapointe", "Leblanc", "Mercier", "Paquette",
    "Perreault", "Poirier", "Simard", "Theriault", "Vachon",
    # Scandinavian (Swedish/Norwegian/Danish)
    "Lindqvist", "Karlsson", "Nilsson", "Andersson", "Johansson",
    "Bergstrom", "Eriksson", "Forsberg", "Hedman", "Josi", "Lindholm",
    "Pettersson", "Nyquist", "Larsson", "Ekholm", "Sandin", "Wallin",
    "Ostlund", "Blomqvist", "Dahl", "Frisk", "Holm", "Lundqvist",
    "Nystrom", "Sundberg", "Wikstrom", "Ahlberg", "Backstrom",
    # Finnish
    "Rantanen", "Aho", "Heiskanen", "Barkov", "Jarvis", "Kotkaniemi",
    "Laine", "Rask", "Granlund", "Kahkonen", "Manninen", "Puljujarvi",
    "Kapanen", "Lehkonen", "Ristolainen", "Saros", "Teravainen",
    "Vatanen", "Maenpaa", "Nurmi", "Hamalainen", "Koivu", "Selanne",
    # Czech / Slovak
    "Pastrnak", "Necas", "Svechnikov", "Chytil", "Vrana", "Krejci",
    "Voracek", "Jaskin", "Palat", "Novak", "Cerny", "Dvorak",
    "Hajek", "Kral", "Marek", "Prochazka", "Sevcik", "Slafkovsky",
    "Chara", "Halak", "Gudas", "Zacha", "Studnicka",
    # Russian / Eastern European
    "Kucherov", "Ovechkin", "Vasilevskiy", "Shesterkin", "Sorokin",
    "Dorofeyev", "Barbashev", "Malkin", "Panarin", "Kaprizov",
    "Zaitsev", "Nikishin", "Voronkov", "Chinakhov", "Marchenko",
    "Fedotov", "Gusev", "Yakupov", "Zubov", "Datsyuk", "Ovchinnikov",
    # German / Swiss / Austrian
    "Meier", "Faksa", "Fiala", "Kahun", "Sturm", "Grubauer", "Nater",
    "Hischier", "Josi", "Fiala", "Ambuhl", "Corvi", "Kurashev",
    "Moser", "Fischer", "Hofer", "Baumgartner", "Wagner", "Zimmermann",
    # Existing "recognizable hockey name" seed set kept for flavor variety
    "McDavid", "Crosby", "Matthews", "Draisaitl", "MacKinnon",
    "Marner", "Hughes", "Point", "Makar", "Werenski", "Weber",
    "Ellis", "Larkin", "Kreider", "Zibanejad", "Trocheck", "Marchand",
    "Hellebuyck", "Swayman", "Fleury", "Bobrovsky", "Price", "Andersen",
    "Suzuki", "Caufield", "Hutson", "Dach", "Boeser", "Miller",
    "Horvat", "Domi", "Tavares", "Nylander", "Rielly", "Bunting",
    "Knies", "Cirelli", "Stamkos", "Perry", "Toews", "Kane", "DeBrincat",
    "Bertuzzi", "Copp", "Zegras", "Terry", "Trouba", "Guentzel",
    "Letang", "Rakell", "Chychrun", "Schmidt", "Eichel", "Stone",
    "Pacioretty", "Hague", "Robertson", "Hintz", "Pavelski", "Oettinger",
    "Wyman", "Lindgren", "Duchene", "Landeskog", "Newhook", "Girard",
    "Byram",
)


def random_name(rng: Rng) -> str:
    """Pick a first and last name via ``rng.choice()`` and return "First Last"."""
    first = rng.choice(FIRST_NAMES)
    last = rng.choice(LAST_NAMES)
    return f"{first} {last}"
