"""Procedural name generation from nationality-keyed name pools.

Mirrors the *pattern* of HoopR's ``hoopsim/gen/namegen.py`` -- weighted first/last name pools drawn
from the shared, seedable :class:`~pucksim.rng.Rng` -- but keyed by nationality rather than flat.

WHAT WAS WRONG WITH THE FLAT POOLS
==================================
223 first and 289 last names in two flat tuples, drawn independently. Three separate problems, of
which the third was the one playtesting actually complained about:

1. **Too small.** 700+ players per league against a pool that size means constant collisions on
   surnames and a league that reads as though it were assembled from a handful of names.
2. **Incoherent pairing.** First and last were drawn from unrelated tuples, so a roster was full of
   men called "Miro Gagnon" and "Jean-Sebastien Ovechkin". Nationality is a real thing about a
   hockey player, and it was being scrambled.
3. **It read as a current NHL roster.** The old pools carried an explicit block commented
   "recognizable hockey name seed set" -- McDavid, Crosby, Matthews, Draisaitl, MacKinnon, Makar,
   Ovechkin, Pastrnak, Selanne, Chara and ~100 more -- plus more of the same seeded through the
   national blocks. Generated teams therefore looked like a slightly-shuffled real NHL.

THE PURGE RULE, WHICH IS ABOUT DISTINCTIVENESS AND NOT ABOUT OVERLAP
====================================================================
Every marquee name is gone. What is deliberately NOT attempted is eliminating all overlap with real
NHL surnames, because that goal is incoherent: the genuinely common surnames of every hockey nation
have someone in the league. There is an NHL Smith, Wilson, Miller, Roy, Novak and Virtanen, and
removing all of them would leave pools of nothing but rare names, which reads *more* artificial,
not less.

The rule is **distinctiveness**: a surname is out if it reads as a reference to one specific real
player (``McDavid``, ``Draisaitl``, ``Ovechkin``, ``Pastrnak``, ``Kaprizov``, ``Slafkovsky``,
``Hellebuyck``, ``Selanne``, ``Chara``), and in if it reads as an ordinary name that some real
player also happens to have (``Smith``, ``Tremblay``, ``Roy``, ``Novak``). "Connor McDavid" is a
reference. "Cole Bannister" is a hockey player.

DETERMINISM
===========
Two deliberate choices here, both about keeping seeds stable across FUTURE edits to this file:

* Draws use ``pool[int(rng.random() * len(pool))]`` rather than ``rng.choice(pool)``.
  ``random.choice`` consumes a variable number of bits depending on the sequence length, so under
  it *any* pool edit -- adding a single name -- shifted the entire downstream RNG stream (ratings,
  ages, everything, since they all share one ``Rng``). A single ``random()`` draw makes pool size
  stream-neutral, so later name additions no longer re-roll every league.
* Nationality is drawn first, from a cumulative walk over ``NATIONALITY_WEIGHTS`` sorted by key, so
  adding a nationality does not renumber the others.

This round's restructuring shifts existing seeds regardless -- old seeds will not reproduce their
old rosters. That is a one-time cost paid to stop paying it.
"""
from __future__ import annotations

import itertools
from typing import Dict, Optional, Sequence, Set, Tuple

from pucksim.rng import Rng

# Share of players by nationality, roughly tracking real NHL demographics (~42% Canadian of which
# about a fifth are francophone, ~28% American, ~10% Swedish, then Russia/Finland/Czechia and a
# tail). Values are relative weights, not percentages -- they need not sum to anything.
NATIONALITY_WEIGHTS: Dict[str, float] = {
    "CAN": 33.0,
    "CAN-QC": 9.0,
    "USA": 28.0,
    "SWE": 10.0,
    "RUS": 6.0,
    "FIN": 5.0,
    "CZE": 4.0,
    "SVK": 2.0,
    "SUI": 1.0,
    "GER": 1.0,
    "DEN": 0.6,
    "LAT": 0.4,
}

# Human-readable labels, for a UI that wants to show more than a code.
NATIONALITY_NAMES: Dict[str, str] = {
    "CAN": "Canada",
    "CAN-QC": "Canada (Quebec)",
    "USA": "United States",
    "SWE": "Sweden",
    "RUS": "Russia",
    "FIN": "Finland",
    "CZE": "Czechia",
    "SVK": "Slovakia",
    "SUI": "Switzerland",
    "GER": "Germany",
    "DEN": "Denmark",
    "LAT": "Latvia",
}

NAME_POOLS: Dict[str, Dict[str, Tuple[str, ...]]] = {
    # -- Anglophone Canada ---------------------------------------------------
    "CAN": {
        "first": (
            "Aiden", "Austin", "Bennett", "Blake", "Braden", "Bradley", "Brady", "Brandon",
            "Brayden", "Brendan", "Brett", "Brock", "Bryce", "Byron", "Caleb", "Cameron",
            "Carson", "Carter", "Chase", "Clayton", "Cody", "Colby", "Cole", "Colton",
            "Connor", "Cooper", "Corey", "Curtis", "Dalton", "Damon", "Darcy", "Dawson",
            "Dean", "Declan", "Derek", "Devon", "Dillon", "Drew", "Dustin", "Dylan",
            "Easton", "Elliot", "Emmett", "Ethan", "Evan", "Everett", "Gage", "Garrett",
            "Gavin", "Grady", "Graham", "Grant", "Grayson", "Griffin", "Harrison", "Hayden",
            "Hudson", "Hunter", "Isaac", "Jace", "Jackson", "Jared", "Jarrett", "Jaxon",
            "Jayden", "Jesse", "Joel", "Jonah", "Jordan", "Joshua", "Kade", "Keegan",
            "Keith", "Kenton", "Kieran", "Kirby", "Kyle", "Landon", "Lane", "Levi",
            "Liam", "Lincoln", "Logan", "Lucas", "Malcolm", "Mason", "Maxwell", "Miles",
            "Mitchell", "Nathan", "Nolan", "Owen", "Parker", "Porter", "Quinn", "Reid",
            "Riley", "Ronan", "Ross", "Rowan", "Ryder", "Shane", "Shea", "Spencer",
            "Stuart", "Tanner", "Tate", "Trent", "Trevor", "Tristan", "Tyler", "Tyson",
            "Wade", "Walker", "Weston", "Wyatt", "Zachary",
        ),
        "last": (
            "Abbott", "Aitken", "Alcorn", "Allison", "Applegate", "Archibald", "Armitage",
            "Ashby", "Ashford", "Atkinson", "Ayres", "Baird", "Baldwin", "Ballantyne",
            "Bannister", "Barclay", "Barlow", "Barnett", "Barrington", "Bartlett", "Bateman",
            "Baxter", "Beattie", "Beaumont", "Bellamy", "Benson", "Berkley", "Bethune",
            "Bickford", "Birchall", "Bishop", "Blackwood", "Blakely", "Bradshaw", "Brannigan",
            "Brennan", "Brewster", "Bridger", "Brimley", "Brockman", "Broderick", "Bromley",
            "Buchanan", "Burgess", "Burnside", "Bushnell", "Calloway", "Cardwell", "Carlisle",
            "Carmichael", "Carruthers", "Cartwright", "Cassidy", "Chadwick", "Chalmers",
            "Chandler", "Charlton", "Clairmont", "Clarkson", "Claybourne", "Clemens", "Coburn",
            "Cochrane", "Colvin", "Comstock", "Conroy", "Copeland", "Corbett", "Cornish",
            "Cosgrove", "Coulter", "Cranston", "Crawford", "Creighton", "Crosbie", "Culver",
            "Cummings", "Dalgleish", "Danforth", "Darrow", "Davenport", "Deakin", "Delaney",
            "Dempsey", "Denholm", "Dennison", "Dewhurst", "Dinsmore", "Doherty", "Dolan",
            "Donnelly", "Dorsey", "Dougall", "Downing", "Drayton", "Driscoll", "Dunbar",
            "Duncan", "Dunmore", "Durrant", "Eddington", "Egerton", "Eldridge", "Ellery",
            "Elliston", "Ellsworth", "Emerson", "Endicott", "Erskine", "Everard", "Fairbairn",
            "Fairweather", "Falconer", "Farnham", "Farquhar", "Farrow", "Faulkner", "Fenwick",
            "Ferguson", "Ferris", "Fielding", "Findlay", "Finnegan", "Flanagan", "Fletcher",
            "Flynn", "Forbes", "Fordham", "Forrester", "Frampton", "Fraser", "Freeborn",
            "Frobisher", "Fulton", "Galbraith", "Gallagher", "Galloway", "Garnett", "Garrick",
            "Gaskell", "Gibbons", "Gifford", "Gilchrist", "Gladwin", "Godfrey", "Goodwin",
            "Gorman", "Grantham", "Greaves", "Greenfield", "Gregson", "Grenville", "Griggs",
            "Guthrie", "Hadfield", "Halloran", "Halstead", "Hamlin", "Hanbury", "Hanley",
            "Harcourt", "Hargrove", "Harkness", "Harlow", "Harrington", "Hartley", "Harwood",
            "Haskell", "Hathaway", "Havelock", "Hawkes", "Haywood", "Hedley", "Henshaw",
            "Hepburn", "Herriot", "Hewitt", "Hickman", "Hillard", "Hobson", "Hodgins",
            "Hogarth", "Holbrook", "Hollingsworth", "Hollis", "Holloway", "Horsley",
            "Houghton", "Howland", "Hoyt", "Hubbard", "Huntley", "Hurley", "Hutchins",
            "Ingersoll", "Ingram", "Ironside", "Irvine", "Isherwood", "Jardine", "Jasper",
            "Jellicoe", "Jenkins", "Jessop", "Kavanagh", "Kearns", "Keating", "Keller",
            "Kelsey", "Kemble", "Kendrick", "Kerr", "Kettering", "Kilbride", "Kilgore",
            "Kimball", "Kingsley", "Kinsella", "Kirkland", "Knowles", "Laidlaw", "Lamont",
            "Langford", "Larkspur", "Lattimer", "Lawson", "Ledger", "Lennox", "Lightfoot",
            "Linwood", "Littlejohn", "Lockhart", "Loveridge", "Lowry", "Ludlow", "Lyndon",
            "Macaulay", "Maddox", "Mallory", "Manning", "Marlowe", "Marsden", "Mathers",
            "Maybury", "McAllister", "McBride", "McCallum", "McClintock", "McCorkle",
            "McCrae", "McElroy", "McGarrigle", "McKellar", "McLachlan", "McNaughton",
            "McPhail", "Melrose", "Mercer", "Merriweather", "Middleton", "Milburn", "Millward",
            "Monroe", "Montgomery", "Moorcroft", "Morrow", "Mortimer", "Mowbray", "Muirhead",
            "Mulholland", "Nash", "Netherton", "Newcombe", "Norbury", "Norris", "Northcott",
            "Oakley", "Ogden", "Ormerod", "Osborne", "Oswald", "Overton", "Paisley",
            "Palgrave", "Parsons", "Pemberton", "Pendleton", "Pennington", "Percival",
            "Perkins", "Pettigrew", "Pickering", "Pinkerton", "Ponsonby", "Prentice",
            "Prescott", "Purcell", "Quimby", "Radcliffe", "Rainford", "Ramsey", "Ransome",
            "Rathbone", "Ravenhill", "Redfern", "Reeves", "Renfrew", "Ridgeway", "Rivington",
            "Roberts", "Rockwell", "Rothwell", "Rowntree", "Rutherford", "Sanderson",
            "Sawyer", "Scarborough", "Selby", "Sewell", "Shackleton", "Shepherd", "Sheridan",
            "Sherwood", "Shipley", "Sinclair", "Skelton", "Slater", "Somerville", "Southwell",
            "Spalding", "Stafford", "Stanhope", "Stapleton", "Sterling", "Stockwell",
            "Stoddard", "Strathmore", "Sutcliffe", "Swinburne", "Tarrant", "Templeman",
            "Thatcher", "Thornbury", "Thornton", "Tilbury", "Tolliver", "Townsend",
            "Trelawney", "Tremaine", "Trentham", "Turnbull", "Turner", "Underhill",
            "Underwood", "Upton", "Vandergrift", "Vaughan", "Verity", "Vickers", "Waddell",
            "Wakefield", "Walbrook", "Walsh", "Warfield", "Warrington", "Waverly", "Weatherby",
            "Wellesley", "Westbrook", "Wetherell", "Wheatley", "Whitcomb", "Whitfield",
            "Whittaker", "Wickham", "Willoughby", "Winslow", "Winterbourne", "Wolcott",
            "Woodrow", "Worthington", "Wrenfield", "Wyndham", "Yardley", "Yeoman", "Yorke",
        ),
    },
    # -- Francophone Canada --------------------------------------------------
    "CAN-QC": {
        "first": (
            "Alexandre", "Antoine", "Benoit", "Bruno", "Charles", "Christophe", "Claude",
            "Cedric", "Damien", "Denis", "Didier", "Dominic", "Edouard", "Emile", "Etienne",
            "Fabien", "Felix", "Francois", "Frederic", "Gabriel", "Gaetan", "Gilles",
            "Guillaume", "Hugo", "Jean-Christophe", "Jean-Francois", "Jean-Philippe",
            "Jean-Sebastien", "Jerome", "Joel", "Julien", "Laurent", "Louis", "Luc",
            "Ludovic", "Marc-Andre", "Marc-Olivier", "Mathieu", "Maxime", "Michel",
            "Nicolas", "Olivier", "Pascal", "Patrice", "Philippe", "Pierre-Alexandre",
            "Pierre-Luc", "Pierre-Olivier", "Raphael", "Remi", "Renaud", "Samuel",
            "Sebastien", "Serge", "Simon", "Stephane", "Sylvain", "Thierry", "Tristan",
            "Vincent", "Xavier", "Yannick", "Yves",
        ),
        "last": (
            "Allaire", "Arcand", "Arsenault", "Aubin", "Aubry", "Audet", "Barrette",
            "Beaudoin", "Beaulieu", "Beauregard", "Belisle", "Berthiaume", "Bernier",
            "Berube", "Bilodeau", "Bissonnette", "Blanchette", "Blouin", "Bolduc",
            "Bonneau", "Bourassa", "Bourgeois", "Brasseur", "Breton", "Brissette", "Brochu",
            "Brunet", "Cadieux", "Cadorette", "Caron", "Chalifoux", "Charbonneau",
            "Charest", "Charron", "Chartrand", "Chouinard", "Clermont", "Cloutier",
            "Corbeil", "Cormier", "Cote", "Courchesne", "Cyr", "Daoust", "Deschamps",
            "Deschenes", "Desjardins", "Deslauriers", "Desrochers", "Desrosiers",
            "Dorion", "Doucet", "Drapeau", "Dufour", "Dumas", "Dumont", "Duquette",
            "Durocher", "Emond", "Falardeau", "Ferland", "Filion", "Fontaine", "Forget",
            "Fortier", "Fortin", "Fournier", "Frechette", "Gagne", "Gagnon", "Galarneau",
            "Gaudet", "Gendron", "Germain", "Gignac", "Gervais", "Godbout", "Gosselin",
            "Goulet", "Grenier", "Grondin", "Guay", "Guilbault", "Hamelin", "Hebert",
            "Houle", "Hudon", "Jodoin", "Joly", "Labelle", "Laberge", "Labonte",
            "Labrecque", "Lachance", "Lacombe", "Lacroix", "Ladouceur", "Laflamme",
            "Lafond", "Lachapelle", "Laframboise", "Lagace", "Lajoie", "Lalonde",
            "Lamarche", "Lamontagne", "Lamothe", "Landry", "Langevin", "Langlois",
            "Lanthier", "Lapierre", "Laplante", "Lapointe", "Larivee", "Larose",
            "Latulippe", "Laurin", "Lauzon", "Lavallee", "Laverdiere", "Lavigne",
            "Lavoie", "Leblanc", "Leclerc", "Lecuyer", "Lefebvre", "Legault", "Legere",
            "Lemay", "Lemire", "Lepage", "Lesage", "Lessard", "Letourneau", "Levesque",
            "Lussier", "Maheux", "Mailhot", "Maillet", "Malette", "Marcotte", "Marleau",
            "Martel", "Massicotte", "Mathieu", "Menard", "Mercier", "Michaud", "Millette",
            "Mireault", "Moisan", "Monette", "Morency", "Morin", "Morissette", "Nadeau",
            "Nantel", "Normandin", "Ouellet", "Ouimet", "Paquin", "Paquette", "Paradis",
            "Parent", "Payette", "Pelletier", "Perron", "Picard", "Pichette", "Pilon",
            "Pinard", "Piche", "Plamondon", "Poirier", "Pomerleau", "Poulin", "Prevost",
            "Proulx", "Quintal", "Rancourt", "Raymond", "Renaud", "Rioux", "Rivard",
            "Robidoux", "Rondeau", "Rousseau", "Roussel", "Routhier", "Roy", "Sauve",
            "Sauvageau", "Seguin", "Simard", "Soucy", "St-Amour", "St-Denis", "St-Hilaire",
            "St-Jean", "St-Onge", "St-Pierre", "Talbot", "Tanguay", "Tessier", "Theriault",
            "Therrien", "Thibault", "Thibodeau", "Tourigny", "Tremblay", "Trepanier",
            "Trudel", "Tourangeau", "Vaillant", "Vaillancourt", "Valiquette", "Veilleux",
            "Verreault", "Villeneuve", "Vincent",
        ),
    },
    # -- United States -------------------------------------------------------
    "USA": {
        "first": (
            "Aaron", "Adam", "Alec", "Andrew", "Anthony", "Ben", "Blaine", "Bradley",
            "Brendan", "Brian", "Broderick", "Bryan", "Casey", "Chad", "Charlie",
            "Chris", "Clark", "Coleman", "Colin", "Craig", "Daniel", "Danny", "David",
            "Derrick", "Doug", "Drake", "Eli", "Eric", "Evan", "Frank", "Gabe",
            "Garret", "Gordon", "Greg", "Hayes", "Henry", "Hutton", "Jack", "Jackson",
            "Jake", "James", "Jason", "Jeff", "Jeremy", "Joe", "John", "Johnny",
            "Jonathan", "Josh", "Justin", "Keith", "Kenny", "Kevin", "Kurt", "Lance",
            "Larry", "Lawrence", "Lucas", "Luke", "Marcus", "Mark", "Matt", "Matthew",
            "Michael", "Mike", "Nate", "Nathaniel", "Nick", "Patrick", "Paul", "Peter",
            "Philip", "Quentin", "Randall", "Ray", "Reece", "Richard", "Rob", "Robert",
            "Ronnie", "Ryan", "Sam", "Scott", "Sean", "Seth", "Steve", "Stephen",
            "Tanner", "Ted", "Theo", "Thomas", "Timothy", "Todd", "Tom", "Tommy",
            "Tony", "Troy", "Vance", "Wesley", "Will", "William", "Zach",
        ),
        "last": (
            "Ackerman", "Adkins", "Albright", "Alderman", "Alvarado", "Ambrose", "Ammons",
            "Andrus", "Arbuckle", "Arnett", "Ashcroft", "Atwood", "Babcock", "Ballinger",
            "Bandy", "Barkley", "Barnhart", "Barron", "Bartholomew", "Batchelder",
            "Beauchamp", "Beecher", "Belmont", "Bergquist", "Berkshire", "Bickerstaff",
            "Bidwell", "Billings", "Bingham", "Birdsall", "Blackburn", "Blaisdell",
            "Blanchard", "Bledsoe", "Bly", "Bogart", "Bolinger", "Bonham", "Boothby",
            "Bostwick", "Bourne", "Bowersox", "Boylan", "Braddock", "Bradbury",
            "Brandeis", "Brantley", "Breckenridge", "Bridgeman", "Brightwell", "Brimmer",
            "Brockway", "Broome", "Brubaker", "Buckhalter", "Bulger", "Bunnell",
            "Burdette", "Burkhart", "Burrows", "Butterfield", "Cadwallader", "Caldwell",
            "Calhoun", "Camden", "Canfield", "Carbaugh", "Carlisle", "Carnahan",
            "Carrington", "Casebolt", "Chamberlin", "Chapin", "Chastain", "Cheatham",
            "Chesney", "Clements", "Cliburn", "Clyburn", "Coffelt", "Colburn", "Colfax",
            "Collier", "Colwell", "Conover", "Considine", "Coombs", "Coppinger",
            "Corliss", "Cortland", "Cottrell", "Coyne", "Cranfill", "Crenshaw",
            "Crittenden", "Crocker", "Cromartie", "Culpepper", "Cunliffe", "Curtiss",
            "Cutler", "Dabney", "Daggett", "Dalrymple", "Danvers", "Darlington",
            "Dearborn", "DeHaven", "Delacroix", "Denby", "Dennard", "Derringer",
            "Devane", "Dewberry", "Dickerson", "Dillard", "Dilworth", "Dobbins",
            "Dockery", "Doolittle", "Dorrance", "Dortch", "Dowdell", "Draper",
            "Driggers", "Dudley", "Dunkelberger", "Dupree", "Durbin", "Eakins",
            "Earnshaw", "Eastman", "Eckhardt", "Edgerton", "Eggleston", "Elkins",
            "Ellinger", "Elsworth", "Ely", "Embry", "Emmerich", "Engelhardt", "Ensley",
            "Epperson", "Ervin", "Eubanks", "Everhart", "Ewell", "Fairchild", "Faircloth",
            "Fallon", "Farnsworth", "Fassbender", "Featherstone", "Ferrell", "Fickett",
            "Fenwood", "Finnerty", "Fishburn", "Fitzhugh", "Fleener", "Flournoy",
            "Fogarty", "Follansbee", "Forsythe", "Fosdick", "Foxworth", "Frankel",
            "Frazier", "Freeland", "Fritsch", "Frye", "Fulbright", "Gaddis", "Gainer",
            "Galligan", "Gantt", "Gardiner", "Garwood", "Garland", "Garrity", "Gaskins",
            "Gatlin", "Geiger", "Gentry", "Gerhardt", "Gillis", "Gilmore", "Girdler",
            "Glasscock", "Godwin", "Goetz", "Goldsberry", "Goode", "Gowdy", "Grantland",
            "Greaser", "Greenough", "Gresham", "Grissom", "Groves", "Grubbs", "Guilford",
            "Gunderson", "Gurley", "Hackett", "Hadden", "Haggerty", "Hainsworth",
            "Halbrook", "Halliday", "Hamblin", "Hammersmith", "Hanchett", "Hardaway",
            "Harkins", "Harmon", "Harnish", "Harshbarger", "Hartsfield", "Haskins",
            "Hasbrouck", "Hatfield", "Havens", "Hawksley", "Hazelwood", "Heffernan",
            "Heindel", "Helmsley", "Hemphill", "Henderson", "Hennessey", "Herrington",
            "Hettinger", "Hibbard", "Hightower", "Hildreth", "Hinckley", "Hindman",
            "Hinson", "Hoagland", "Hockenberry", "Hodgkins", "Hoffman", "Hollingshead",
            "Holmberg", "Honeycutt", "Hooker", "Hornbeck", "Horrigan", "Hostetler",
            "Hovland", "Howerton", "Hoxie", "Hubbell", "Huddleston", "Hufford",
            "Huguley", "Hulsey", "Humphries", "Hunnicutt", "Hurlbut", "Hutchinson",
            "Ingalls", "Inman", "Isbell", "Jacoby", "Jamison", "Janeway", "Jernigan",
            "Jessup", "Jewett", "Jolley", "Jordanson", "Judkins", "Kanavel", "Karcher",
            "Kavanaugh", "Keegan", "Keenum", "Kellerman", "Kemmerer", "Kenworthy",
            "Kepler", "Kernodle", "Kettleman", "Kilpatrick", "Kimbrough", "Kincaid",
            "Kinsey", "Kirchner", "Kittredge", "Klingensmith", "Knudsen", "Kohlmeier",
            "Kramer", "Kuykendall", "Ladd", "Lafferty", "Lampkin", "Landreth", "Langhorne",
            "Lankford", "Lanning", "Lassiter", "Latham", "Lauderdale", "Leatherwood",
            "Ledbetter", "Leftwich", "Lehmann", "Lemmon", "Lensch", "Lesnick", "Lightner",
            "Lindstrom", "Linkous", "Litchfield", "Lockridge", "Loeffler", "Lofton",
            "Loganberry", "Longacre", "Lovelace", "Lowder", "Lucey", "Ludwick",
            "Lundgren", "Lybrand", "Lyman", "Mabry", "Macomber", "Maddock", "Magruder",
            "Mahaffey", "Malcolm", "Mangrum", "Manzella", "Marbury", "Marchetti",
            "Markley", "Marlatt", "Marston", "Mashburn", "Massengill", "Mattingly",
            "Maulding", "Maxfield", "McAdoo", "McCandless", "McClanahan", "McCollough",
            "McCutcheon", "McFadden", "McGinnis", "McKamey", "McKinstry", "McLendon",
            "McMasters", "McQuaid", "McSwain", "Meacham", "Medlin", "Melancon",
            "Mendenhall", "Merryman", "Mickelson", "Milholland", "Millender", "Minshall",
            "Mixon", "Moffitt", "Mondragon", "Montague", "Moorhead", "Morganfield",
            "Mosier", "Mottley", "Mullenix", "Mundy", "Murchison", "Musselman",
            "Nabors", "Nadeau", "Naugle", "Neeley", "Nesbitt", "Newkirk", "Nickerson",
            "Nordstrom", "Northrup", "Nunnally", "Oberlin", "Odom", "Ogletree",
            "Oldham", "Olinger", "Ormsby", "Orndorff", "Ostrander", "Ottinger",
            "Overstreet", "Paffenbarger", "Pankratz", "Parkhurst", "Partlow", "Patchett",
            "Pattillo", "Pearsall", "Peavy", "Pedigo", "Pennebaker", "Pepperell",
            "Perryman", "Pettibone", "Pfeiffer", "Philbrick", "Pickens", "Pilcher",
            "Pinckney", "Plunkett", "Poindexter", "Pomeroy", "Pontius", "Poplin",
            "Portwood", "Prewitt", "Prickett", "Pruett", "Puckett", "Purnell",
            "Quarles", "Quillen", "Rademacher", "Ragsdale", "Rainwater", "Rambeau",
            "Randolph", "Rasmussen", "Ratliff", "Reddick", "Redmond", "Reinhardt",
            "Renshaw", "Rexford", "Rhinehart", "Richmond", "Ridenour", "Rigsby",
            "Rinehart", "Ripley", "Roark", "Rockhold", "Rodenhauser", "Rollins",
            "Rooker", "Rosenbaum", "Rothbury", "Roundtree", "Rowe", "Ruckman",
            "Rundell", "Rushing", "Rutledge", "Sackett", "Saddler", "Salsbury",
            "Sanderlin", "Sandoval", "Sargent", "Satterfield", "Saylor", "Scarbrough",
            "Schaeffer", "Schell", "Schoonover", "Schroeder", "Scoggins", "Scranton",
            "Seagraves", "Sedgwick", "Selkirk", "Sessions", "Shadrick", "Shanklin",
            "Sharpton", "Shattuck", "Shelburne", "Shellenberger", "Shenk", "Shepler",
            "Sheridan", "Shockley", "Shoemaker", "Shropshire", "Sikorski", "Silvernail",
            "Simonton", "Sisemore", "Skaggs", "Slaughter", "Slocum", "Smallwood",
            "Snodgrass", "Somerset", "Sowell", "Spangler", "Sparkman", "Spearman",
            "Speight", "Spillman", "Spivey", "Sprague", "Stallworth", "Standridge",
            "Stanfield", "Starkweather", "Steadman", "Stebbins", "Steckler", "Stegall",
            "Stenson", "Stidham", "Stillwell", "Stinnett", "Stockbridge", "Stonebraker",
            "Stoughton", "Stovall", "Strickland", "Stringfellow", "Strother", "Stubblefield",
            "Sturdivant", "Sudduth", "Sumrall", "Sutphin", "Swearingen", "Sweitzer",
            "Swindell", "Sykes", "Taggart", "Tallman", "Tankersley", "Tarleton",
            "Tatum", "Teasley", "Templeton", "Terhune", "Thackston", "Thigpen",
            "Thorndike", "Threadgill", "Thurmond", "Tidwell", "Tilghman", "Tinsley",
            "Tipton", "Tolbert", "Tomlinson", "Torkelson", "Trafton", "Trammell",
            "Traylor", "Trimble", "Truesdale", "Tullis", "Turnipseed", "Twombly",
            "Underdown", "Upshaw", "Urquhart", "Vandiver", "VanMeter", "Vanwinkle",
            "Varnado", "Veatch", "Vermillion", "Vestal", "Vinson", "Voorhees",
            "Waddington", "Wadsworth", "Wainscott", "Waldrop", "Walkup", "Wallingford",
            "Wamsley", "Wanamaker", "Warnock", "Washburn", "Wasserman", "Waterhouse",
            "Wathen", "Weatherford", "Weddington", "Weinstein", "Welborn", "Wentworth",
            "Wertman", "Westmoreland", "Whaley", "Wheelock", "Whitehurst", "Whitesides",
            "Whitlow", "Whitmire", "Wickersham", "Wigginton", "Wilburn", "Wilcoxon",
            "Wilhoit", "Willingham", "Winchell", "Wingfield", "Winfrey", "Winthrop",
            "Wisniewski", "Witherspoon", "Wolfenbarger", "Woodbury", "Woolridge",
            "Workman", "Wortham", "Wrenn", "Wyatt", "Yancey", "Yarborough", "Yeager",
            "Yost", "Youngblood", "Zabriskie", "Zeigler", "Zilinski", "Zumwalt",
        ),
    },
    # -- Sweden --------------------------------------------------------------
    "SWE": {
        "first": (
            "Adam", "Albin", "Alfred", "Algot", "Anders", "Andreas", "Anton", "Arvid",
            "August", "Axel", "Benjamin", "Bjorn", "Casper", "Christoffer", "Dag",
            "Daniel", "Edvin", "Elias", "Emil", "Erik", "Filip", "Folke", "Fredrik",
            "Gunnar", "Gustav", "Hampus", "Hannes", "Harald", "Hjalmar", "Hugo",
            "Isak", "Jesper", "Joakim", "Johan", "Jonas", "Kalle", "Karl", "Kasper",
            "Klas", "Leo", "Linus", "Ludvig", "Magnus", "Malte", "Marcus", "Mattias",
            "Melker", "Mikael", "Nils", "Olle", "Olof", "Oscar", "Oskar", "Patrik",
            "Per", "Pontus", "Rasmus", "Robin", "Rune", "Samuel", "Sixten", "Stellan",
            "Sten", "Sture", "Svante", "Sven", "Theodor", "Tobias", "Torbjorn", "Vidar",
            "Viktor", "Wilmer", "Yngve",
        ),
        "last": (
            "Ahlgren", "Ahlstrom", "Akerlund", "Albinsson", "Almqvist", "Alvesson",
            "Arvidsson", "Asplund", "Axelsson", "Bengtsson", "Berggren", "Berglund",
            "Bergman", "Bergqvist", "Bergsten", "Birkeland", "Bjorklund", "Bjornstad",
            "Blomberg", "Blomgren", "Bohlin", "Borjesson", "Brannstrom", "Brodin",
            "Bystrom", "Cederberg", "Cedergren", "Dahlberg", "Dahlgren", "Dahlin",
            "Danielsson", "Edlund", "Ekelund", "Ekstrand", "Ekstrom", "Eliasson",
            "Elmgren", "Engberg", "Engstrom", "Enqvist", "Falkenberg", "Fredriksson",
            "Frisell", "Gillberg", "Granberg", "Grundstrom", "Gullberg", "Gunnarsson",
            "Gustafsson", "Hagberg", "Haglund", "Hagstrom", "Hallberg", "Hallgren",
            "Hammarstrom", "Hansson", "Hedberg", "Hedlund", "Hedstrom", "Hellstrom",
            "Henriksson", "Hjelm", "Holmberg", "Holmgren", "Holmstrom", "Hultgren",
            "Isaksson", "Jakobsson", "Jansson", "Jarnstrom", "Jonsson", "Kallstrom",
            "Karlberg", "Karlgren", "Kjellberg", "Klingstrom", "Kollberg", "Kvist",
            "Lagerqvist", "Landin", "Larsen", "Lidstrand", "Liljedahl", "Lindberg",
            "Lindblad", "Lindborg", "Lindell", "Lindkvist", "Lindstrom", "Ljungberg",
            "Ljunggren", "Lofgren", "Lofstrom", "Lundberg", "Lundell", "Lundgren",
            "Lundin", "Lundmark", "Magnusson", "Malmberg", "Mansson", "Mattsson",
            "Molin", "Moller", "Mostrom", "Nordberg", "Nordin", "Nordlund", "Nordqvist",
            "Norling", "Nygren", "Nyholm", "Nylund", "Odqvist", "Ohlsson", "Olausson",
            "Olofsson", "Olsson", "Oscarsson", "Osterberg", "Ostergren", "Palmgren",
            "Persson", "Ramstedt", "Rehn", "Ringqvist", "Rosen", "Rosengren", "Rundberg",
            "Rydberg", "Rydell", "Sahlin", "Salmberg", "Samuelsson", "Sandberg",
            "Sandell", "Sandgren", "Sandstrom", "Sjoberg", "Sjogren", "Sjolander",
            "Sjostrand", "Skoglund", "Soderberg", "Soderholm", "Soderlund", "Soderqvist",
            "Solberg", "Stahl", "Stenberg", "Stenlund", "Stenmark", "Stjernberg",
            "Strandberg", "Stromberg", "Stromgren", "Sundgren", "Sundell", "Sundkvist",
            "Sundquist", "Sundstrom", "Svanberg", "Svedberg", "Svensson", "Tengvall",
            "Thelin", "Thorell", "Thulin", "Tornberg", "Tornqvist", "Ulfsson",
            "Vallgren", "Wahlberg", "Wahlgren", "Wahlstrom", "Wallander", "Wallenberg",
            "Wallentin", "Wennerlund", "Wennstrom", "Werner", "Westberg", "Westerlund",
            "Westling", "Westman", "Wickberg", "Widmark", "Wiklund", "Wikstrand",
            "Ymer", "Zetterqvist", "Ostberg", "Ostlund", "Oberg",
            "Andersson",
            "Bergstrom",
            "Eriksson",
            "Johansson",
            "Karlsson",
            "Larsson",
            "Lindqvist",
            "Nilsson",
            "Nystrom",
        ),
    },
    # -- Russia --------------------------------------------------------------
    "RUS": {
        "first": (
            "Aleksandr", "Aleksei", "Anatoli", "Andrei", "Anton", "Arkadi", "Arseni",
            "Artem", "Boris", "Danil", "Denis", "Dmitri", "Eduard", "Fedor", "Gennadi",
            "Georgi", "Gleb", "Grigori", "Igor", "Ilya", "Innokenti", "Ivan", "Kirill",
            "Konstantin", "Leonid", "Maksim", "Matvei", "Mikhail", "Nikita", "Nikolai",
            "Oleg", "Pavel", "Pyotr", "Roman", "Rostislav", "Ruslan", "Sergei",
            "Semyon", "Stanislav", "Stepan", "Svyatoslav", "Timofei", "Timur", "Vadim",
            "Valeri", "Vasili", "Viktor", "Vitali", "Vladimir", "Vladislav",
            "Vyacheslav", "Yaroslav", "Yegor", "Yevgeni", "Yuri", "Zakhar",
        ),
        "last": (
            "Abramov", "Afanasyev", "Agapov", "Akimov", "Alekseyev", "Andreyev",
            "Anikin", "Anisimov", "Antipov", "Antonov", "Arkhipov", "Artemyev",
            "Astakhov", "Avdeyev", "Babkin", "Baranov", "Basov", "Bazarov", "Belikov",
            "Belyaev", "Bespalov", "Bezrukov", "Biryukov", "Blinov", "Bobkov",
            "Bogdanov", "Bolshov", "Borisov", "Bragin", "Brusilov", "Bukin", "Bulanov",
            "Burlakov", "Chebotarev", "Cherkasov", "Chernov", "Chernyshev", "Chistyakov",
            "Danilov", "Davydov", "Dementyev", "Demidov", "Denisov", "Dobrynin",
            "Dolgov", "Dorokhov", "Drozdov", "Dubinin", "Dudin", "Dyachenko", "Yefimov",
            "Yegorov", "Yeremin", "Yermakov", "Yeroshin", "Filatov", "Filippov",
            "Frolov", "Gavrilov", "Glebov", "Golovin", "Goncharov", "Gorbunov",
            "Gordeyev", "Gorelov", "Gorshkov", "Grachev", "Gribkov", "Grishin",
            "Gromov", "Gurov", "Ignatyev", "Ilyin", "Isayev", "Ivanov", "Kabanov",
            "Kalinin", "Kamenev", "Karpov", "Kartashov", "Kazakov", "Kharitonov",
            "Khokhlov", "Khomyakov", "Khudyakov", "Kiselev", "Klimov", "Kobzev",
            "Kolesnikov", "Kolobov", "Komarov", "Kondratyev", "Konovalov", "Kopylov",
            "Korolev", "Korshunov", "Kosarev", "Kostin", "Kotov", "Kovalenko",
            "Kozlov", "Krasilnikov", "Kruglov", "Kryukov", "Kudryashov", "Kulikov",
            "Kurbatov", "Kuznetsov", "Lapshin", "Larin", "Lavrov", "Lazarev",
            "Lebedev", "Leonov", "Levin", "Lisitsyn", "Lobanov", "Loginov", "Lukin",
            "Lyapin", "Makarov", "Maksimov", "Malinin", "Maltsev", "Manin", "Markov",
            "Martynov", "Maslov", "Matveyev", "Medvedev", "Melnikov", "Mikhailov",
            "Milyutin", "Mironov", "Mishin", "Molchanov", "Morozov", "Moskvin",
            "Nazarov", "Nechayev", "Nekrasov", "Nesterov", "Nikitin", "Nikolayev",
            "Novikov", "Obukhov", "Odintsov", "Orekhov", "Orlov", "Osipov",
            "Ovsyannikov", "Panfilov", "Panin", "Pankratov", "Pavlov", "Petrov",
            "Pimenov", "Platonov", "Plotnikov", "Podolsky", "Polyakov", "Ponomarev",
            "Popov", "Postnikov", "Potapov", "Prokhorov", "Pronin", "Puchkov",
            "Rodionov", "Rogov", "Romanov", "Roshchin", "Rozanov", "Rubtsov",
            "Rudakov", "Rumyantsev", "Rybakov", "Ryzhkov", "Safonov", "Samsonov",
            "Savelyev", "Savin", "Selezenev", "Semenov", "Sergeyev", "Serov",
            "Shakhov", "Shalimov", "Shaposhnikov", "Sharov", "Shchukin", "Shcherbakov",
            "Shevchenko", "Shilov", "Shirokov", "Shishkin", "Shmelev", "Shubin",
            "Shulgin", "Sidorov", "Silin", "Simonov", "Sizov", "Skvortsov", "Smirnov",
            "Sobolev", "Sokolov", "Solovyov", "Soroka", "Sosnin", "Stepanov",
            "Strelkov", "Subbotin", "Sukhanov", "Sviridov", "Tarabrin", "Tikhomirov",
            "Tikhonov", "Timofeyev", "Titov", "Tretyakov", "Trofimov", "Tsvetkov",
            "Tulupov", "Turchin", "Ugolnikov", "Ulyanov", "Ustinov", "Vasilyev",
            "Vedernikov", "Veselov", "Vinogradov", "Vishnevsky", "Vlasov", "Volkov",
            "Vorobyov", "Voronin", "Voronov", "Yakovlev", "Yashunin", "Yudin",
            "Yushkov", "Zaharov", "Zaytsev", "Zelenov", "Zhdanov", "Zhilin",
            "Zhukov", "Zinovyev", "Zolotarev", "Zorin", "Zuyev", "Zykov",
        ),
    },
    # -- Finland -------------------------------------------------------------
    "FIN": {
        "first": (
            "Aapo", "Aarne", "Aatos", "Aki", "Aleksi", "Antti", "Arttu", "Eero",
            "Eetu", "Eino", "Elias", "Erkki", "Hannu", "Harri", "Heikki", "Iiro",
            "Ilkka", "Ilmari", "Janne", "Jarkko", "Jere", "Jesse", "Joel", "Joonas",
            "Jouni", "Juha", "Juho", "Jukka", "Jussi", "Kaapo", "Kalle", "Kari",
            "Kasperi", "Lauri", "Leevi", "Markku", "Matias", "Mika", "Mikko", "Niilo",
            "Niko", "Olli", "Onni", "Oskari", "Otso", "Otto", "Paavo", "Pekka",
            "Petteri", "Pyry", "Rasmus", "Reijo", "Risto", "Roope", "Saku", "Sami",
            "Santeri", "Sauli", "Seppo", "Taneli", "Tapio", "Tarmo", "Teemu",
            "Timo", "Toni", "Topias", "Tuomas", "Urho", "Valtteri", "Veeti", "Vesa",
            "Ville", "Väinö",
        ),
        "last": (
            "Aalto", "Aaltonen", "Ahokas", "Ahonen", "Airaksinen", "Alanen", "Anttila",
            "Asikainen", "Auvinen", "Eerola", "Eronen", "Haapala", "Haavisto",
            "Hakala", "Hakkarainen", "Halonen", "Hanninen", "Harju", "Hartikainen",
            "Hautala", "Heikkila", "Heikkinen", "Heinonen", "Helenius", "Hiltunen",
            "Hirvonen", "Hokkanen", "Holappa", "Honkanen", "Huhtala", "Hurskainen",
            "Huttunen", "Hyvarinen", "Ikonen", "Immonen", "Jaakkola", "Jalonen",
            "Jokela", "Jokinen", "Juntunen", "Jussila", "Kaartinen", "Kaipainen",
            "Kallio", "Kangas", "Kanninen", "Karhu", "Karjalainen", "Karppinen",
            "Kauppinen", "Keranen", "Keskinen", "Kettunen", "Kilpelainen", "Kinnunen",
            "Kivimaki", "Kivinen", "Kokko", "Kolehmainen", "Komulainen", "Konttinen",
            "Korhonen", "Koskela", "Koskinen", "Kuisma", "Kujala", "Kukkonen",
            "Kulmala", "Kuusela", "Kuusisto", "Laakso", "Laaksonen", "Lahtinen",
            "Laitinen", "Lammi", "Lampinen", "Lappalainen", "Lassila", "Latvala",
            "Lehtinen", "Lehtonen", "Leinonen", "Leppanen", "Levanen", "Liimatainen",
            "Lindfors", "Lipponen", "Luoma", "Makela", "Makinen", "Malinen",
            "Mattila", "Miettinen", "Moilanen", "Mustonen", "Myllyla", "Nevalainen",
            "Nieminen", "Niiranen", "Nikula", "Niskanen", "Nissinen", "Nousiainen",
            "Nurminen", "Ojala", "Oksanen", "Paananen", "Paavola", "Pajunen",
            "Pakarinen", "Palokangas", "Partanen", "Pasanen", "Peltola", "Peltonen",
            "Pennanen", "Pesonen", "Piirainen", "Pitkanen", "Pohjola", "Pulkkinen",
            "Puustinen", "Raatikainen", "Rahkonen", "Raitanen", "Rantala",
            "Rautiainen", "Riikonen", "Rinta", "Ronkainen", "Ruotsalainen",
            "Rytkonen", "Saarela", "Saarinen", "Salminen", "Salo", "Salonen",
            "Savolainen", "Seppala", "Seppanen", "Sihvonen", "Silvennoinen",
            "Simola", "Sipila", "Sirkka", "Soininen", "Sorsa", "Suominen",
            "Taipale", "Tamminen", "Tanskanen", "Tikkanen", "Toivonen", "Tuomi",
            "Tuominen", "Turunen", "Uusitalo", "Vainio", "Valkama", "Valtonen",
            "Vartiainen", "Vehvilainen", "Venalainen", "Vesterinen", "Viinikainen",
            "Viitala", "Virtanen", "Vuorinen", "Ylitalo", "Ylonen",
            "Hamalainen",
            "Jarvinen",
            "Niemi",
        ),
    },
    # -- Czechia -------------------------------------------------------------
    "CZE": {
        "first": (
            "Adam", "Ales", "Antonin", "Bedrich", "Bohumil", "Cenek", "Daniel",
            "David", "Dominik", "Filip", "Frantisek", "Havel", "Hynek", "Ivan",
            "Jachym", "Jakub", "Jan", "Jaromir", "Jaroslav", "Jindrich", "Jiri",
            "Josef", "Karel", "Kryzstof", "Ladislav", "Libor", "Lubomir", "Ludek",
            "Lukas", "Marek", "Martin", "Matej", "Michal", "Milan", "Miloslav",
            "Miroslav", "Ondrej", "Otakar", "Patrik", "Pavel", "Petr", "Premysl",
            "Radek", "Radim", "Radovan", "Richard", "Roman", "Rostislav", "Rudolf",
            "Stanislav", "Stepan", "Svatopluk", "Tadeas", "Tomas", "Vaclav",
            "Vilem", "Vit", "Vitezslav", "Vladimir", "Vojtech", "Zbynek", "Zdenek",
        ),
        "last": (
            "Ambroz", "Baier", "Bakos", "Bartos", "Bartunek", "Bazant", "Bednar",
            "Benes", "Beran", "Bilek", "Blazek", "Bohac", "Bouska", "Brabec",
            "Branik", "Brezina", "Brozek", "Bures", "Cadek", "Capek", "Cech",
            "Cermak", "Cervenka", "Chalupa", "Chvatal", "Cizek", "Dobias",
            "Dolezal", "Doubek", "Drabek", "Duda", "Dusek", "Fiser", "Fikrle",
            "Fojtik", "Formanek", "Frantik", "Fuksa", "Gerych", "Hajek", "Halasek",
            "Hampl", "Hanousek", "Hanus", "Havlik", "Herman", "Hlavac", "Hobza",
            "Holecek", "Holub", "Homolka", "Horacek", "Horak", "Hovorka", "Hrabal",
            "Hrbek", "Hruby", "Hruska", "Hudec", "Husak", "Jandera", "Janecek",
            "Janota", "Jelinek", "Jindra", "Jirasek", "Jirku", "Jurcik", "Kadlec",
            "Kacer", "Kalina", "Kaminsky", "Kanera", "Kasal", "Kaspar", "Kavan",
            "Klapka", "Klima", "Knotek", "Kocian", "Kohout", "Kolar", "Konecny",
            "Kopecky", "Korinek", "Kostka", "Kotrla", "Koubek", "Kovar", "Kozel",
            "Kratochvil", "Kraus", "Krecmer", "Kriz", "Krupicka", "Kubes", "Kubicek",
            "Kucera", "Kudrna", "Kulhanek", "Kuncar", "Kvapil", "Lang", "Latal",
            "Lehky", "Liska", "Machala", "Machacek", "Malecha", "Mares", "Marik",
            "Masek", "Matejka", "Melichar", "Mikula", "Mlynar", "Moravec", "Mucha",
            "Musil", "Nechvatal", "Nedoma", "Nemec", "Nesvadba", "Nosek", "Novacek",
            "Novak", "Novotny", "Oplt", "Palecek", "Pancik", "Pavlicek", "Pekar",
            "Peterka", "Petrasek", "Pinkas", "Placek", "Pokorny", "Polak", "Popelka",
            "Pospisil", "Prazak", "Prokes", "Pruska", "Rada", "Rehak", "Riha",
            "Rozmara", "Rubes", "Ruzicka", "Rykl", "Sabata", "Safarik", "Salava",
            "Sedlak", "Semerad", "Simecek", "Simon", "Sindelar", "Skala", "Skoda",
            "Slavik", "Slezak", "Smid", "Smrcek", "Sobotka", "Sochor", "Sopr",
            "Soukup", "Sourek", "Spacek", "Sparovec", "Srb", "Stach", "Stary",
            "Stehlik", "Stejskal", "Strapek", "Strnad", "Suchanek", "Sula", "Svoboda",
            "Synek", "Tichy", "Tomanek", "Trnka", "Truhlar", "Ubl", "Urban",
            "Vachal", "Valenta", "Vanek", "Vavra", "Vejvoda", "Vesely", "Vitek",
            "Vlach", "Vlcek", "Vodicka", "Vojtek", "Vondracek", "Vopalka", "Vrba",
            "Vytiska", "Zajic", "Zaloudek", "Zapletal", "Zavoral", "Zeman",
            "Zikmund", "Zilka",
            "Kral",
            "Sedlacek",
        ),
    },
    # -- Slovakia ------------------------------------------------------------
    "SVK": {
        "first": (
            "Adrian", "Andrej", "Boris", "Branislav", "Dalibor", "Dusan", "Erik",
            "Filip", "Gabriel", "Igor", "Ivan", "Jakub", "Jan", "Jaroslav", "Jozef",
            "Juraj", "Kamil", "Kristian", "Ladislav", "Lubomir", "Lukas", "Marcel",
            "Marek", "Marian", "Marko", "Martin", "Matej", "Matus", "Michal",
            "Milan", "Miloslav", "Miroslav", "Norbert", "Ondrej", "Patrik", "Pavol",
            "Peter", "Radoslav", "Rastislav", "Richard", "Robert", "Roman",
            "Samuel", "Simon", "Stanislav", "Stefan", "Tibor", "Tomas", "Vladimir",
            "Zdeno",
        ),
        "last": (
            "Antal", "Babic", "Bacik", "Balaz", "Bartos", "Belan", "Beno",
            "Bezak", "Blaho", "Bosak", "Brencic", "Bukovsky", "Cabak", "Cerny",
            "Chudik", "Cizmar", "Danko", "Dolnik", "Dubovsky", "Duris", "Durica",
            "Fabian", "Farkas", "Fedor", "Ferko", "Gajdos", "Galis", "Gasparik",
            "Gono", "Grexa", "Gross", "Hajko", "Halama", "Hanzel", "Hascak",
            "Hlinka", "Holly", "Hostak", "Hraska", "Hrnko", "Hudak", "Hujsa",
            "Ivan", "Jakubec", "Janik", "Jasko", "Jendek", "Jurco", "Kalis",
            "Kapusta", "Kascak", "Kmec", "Kollar", "Konecny", "Kopecny", "Korim",
            "Kosik", "Kovac", "Kozak", "Krajci", "Kralik", "Krizan", "Kuchta",
            "Kubica", "Kudela", "Kysela", "Lackovic", "Lantos", "Lauko", "Lednicky",
            "Liba", "Lichanec", "Lipiansky", "Macejko", "Machaj", "Majer",
            "Marcinko", "Masar", "Matejka", "Medvid", "Melnik", "Mesar", "Mihalik",
            "Mikus", "Milo", "Mlynarcik", "Nagy", "Nemcik", "Nizky", "Novotny",
            "Obsut", "Olejnik", "Orsulak", "Paska", "Pastor", "Petras", "Pisar",
            "Podhradsky", "Pokovic", "Polak", "Praznovsky", "Prokop", "Puliš",
            "Rakovsky", "Rehak", "Repcik", "Rusnak", "Ruttkay", "Sabol",
            "Sarnik", "Sedlacek", "Sekula", "Simko", "Sipos", "Skalicky", "Sladok",
            "Smolka", "Sofranko", "Soska", "Stano", "Stefanka", "Sturc",
            "Sucharda", "Sulak", "Surovy", "Svec", "Svitek", "Takac", "Tarasek",
            "Tobias", "Toman", "Trencan", "Trska", "Uram", "Vachovec", "Valach",
            "Varga", "Vrabel", "Zabka", "Zahradnik", "Zaujec", "Zeleznik",
        ),
    },
    # -- Switzerland ---------------------------------------------------------
    "SUI": {
        "first": (
            "Andres", "Beat", "Benjamin", "Christoph", "Cyrill", "Dario", "Denis",
            "Dominik", "Elias", "Fabian", "Fabrice", "Flurin", "Gaetan", "Gian",
            "Gilles", "Jannik", "Joel", "Jonas", "Julien", "Kevin", "Lars",
            "Laurent", "Levin", "Lino", "Loic", "Lorenz", "Luca", "Marco",
            "Mathias", "Nando", "Nico", "Noah", "Pascal", "Patrick", "Pius",
            "Ramon", "Raphael", "Remo", "Reto", "Robin", "Roman", "Samuel",
            "Sandro", "Severin", "Silvan", "Simon", "Sven", "Thierry", "Timo",
            "Tristan", "Urs", "Valentin", "Yannick",
        ),
        "last": (
            "Aebi", "Aeschlimann", "Amrein", "Bachmann", "Baumann", "Baumgartner",
            "Berger", "Bieri", "Blaser", "Bosshard", "Brunner", "Buhler",
            "Burkhalter", "Buser", "Cattaneo", "Diethelm", "Egli", "Eichenberger",
            "Etter", "Fankhauser", "Farine", "Frei", "Freuler", "Frick", "Furrer",
            "Gasser", "Gerber", "Giger", "Glauser", "Gnadinger", "Graf", "Grossen",
            "Gubler", "Haldimann", "Hauri", "Hausmann", "Hegglin", "Heller",
            "Hermann", "Hodel", "Hofmann", "Hostettler", "Huber", "Hunziker",
            "Imhof", "Isler", "Jaggi", "Jenny", "Kaufmann", "Keller", "Kessler",
            "Kohler", "Kubli", "Kunzli", "Lehmann", "Leuenberger", "Liechti",
            "Loosli", "Luthi", "Maissen", "Marti", "Mathys", "Merz", "Mettler",
            "Michel", "Moser", "Muller", "Notz", "Oberholzer", "Ott", "Pfister",
            "Pulver", "Reber", "Regli", "Rimann", "Rohrer", "Roth", "Ruegg",
            "Schaller", "Schaub", "Scheidegger", "Schenk", "Scherrer", "Schneider",
            "Schwarz", "Seiler", "Siegrist", "Sigg", "Stadler", "Staub",
            "Steiner", "Streuli", "Stucki", "Suter", "Tanner", "Trachsel",
            "Tschumi", "Vogel", "Vollenweider", "Wagner", "Walther", "Wetzel",
            "Wehrli", "Wiedmer", "Wirz", "Wullschleger", "Wyss", "Zahner",
            "Zbinden", "Zehnder", "Zimmerli", "Zurcher",
        ),
    },
    # -- Germany -------------------------------------------------------------
    "GER": {
        "first": (
            "Alexander", "Andreas", "Benedikt", "Bernd", "Christian", "Constantin",
            "Dennis", "Dominik", "Elias", "Emil", "Fabian", "Felix", "Finn",
            "Florian", "Frank", "Gerrit", "Hendrik", "Jan", "Janik", "Jannis",
            "Johannes", "Jonas", "Julian", "Justus", "Kai", "Karl", "Konrad",
            "Korbinian", "Lars", "Leon", "Leonard", "Lukas", "Manuel", "Marc",
            "Markus", "Matthias", "Maximilian", "Michael", "Moritz", "Nico",
            "Niklas", "Ole", "Oskar", "Patrick", "Paul", "Philipp", "Rafael",
            "Sebastian", "Simon", "Stefan", "Sven", "Thomas", "Tim", "Tobias",
            "Torben", "Valentin", "Vincent", "Yannik",
        ),
        "last": (
            "Achenbach", "Ahrens", "Altmann", "Bachler", "Barthel", "Bauer",
            "Bechtold", "Beckmann", "Behrens", "Bergmann", "Biermann", "Bittner",
            "Bode", "Bohnert", "Brandt", "Braun", "Breuer", "Brinkmann", "Buchner",
            "Burkhardt", "Diekmann", "Dittrich", "Doring", "Drexler", "Eberhardt",
            "Eckert", "Ehrhardt", "Engelmann", "Ernst", "Falkenhagen", "Feldmann",
            "Fischbach", "Forster", "Frankenberg", "Freitag", "Frey", "Gebhardt",
            "Geissler", "Gerlach", "Giesecke", "Gorlitz", "Grabowski", "Grimm",
            "Gunther", "Haase", "Hafner", "Hagedorn", "Hartmann", "Hauser",
            "Heinemann", "Hellwig", "Hensel", "Herzog", "Hildebrand", "Hirsch",
            "Hoffmeister", "Holzer", "Horstmann", "Jung", "Kaltenbach", "Kastner",
            "Kaufmann", "Kellermann", "Kiefer", "Kirchhoff", "Klein", "Kluge",
            "Knauer", "Kober", "Konig", "Kornmann", "Krebs", "Kroger", "Kruger",
            "Kuhlmann", "Kuhnert", "Lange", "Lauterbach", "Lehner", "Leitner",
            "Lichtenberg", "Lindner", "Loewe", "Ludwig", "Mahler", "Maier",
            "Mangold", "Mayer", "Mehlhorn", "Meissner", "Mendel", "Metzger",
            "Neubauer", "Neumann", "Niederer", "Oberhauser", "Ortmann", "Osterhagen",
            "Pfaff", "Pflug", "Pohlmann", "Rauch", "Rehbein", "Reichert",
            "Reinhold", "Richter", "Riedel", "Rittner", "Rohde", "Rosenthal",
            "Sailer", "Sattler", "Schafer", "Scheibe", "Schilling", "Schlegel",
            "Schmid", "Schneiderhan", "Scholz", "Schreiber", "Schubert",
            "Schwaiger", "Seidel", "Sommer", "Sonntag", "Stadelmann", "Stark",
            "Steinmetz", "Stengel", "Stolz", "Strauss", "Thiel", "Tillmann",
            "Traub", "Ulmer", "Unger", "Vogler", "Voigt", "Wachter", "Waldner",
            "Weidemann", "Weinhold", "Weissmann", "Wendt", "Werner", "Wieland",
            "Wiesner", "Winkler", "Wittmann", "Wolff", "Zeller", "Ziegler",
            "Zimmermann",
        ),
    },
    # -- Denmark -------------------------------------------------------------
    "DEN": {
        "first": (
            "Anders", "Asger", "Bjarke", "Casper", "Christian", "Emil", "Esben",
            "Frederik", "Gustav", "Hans", "Jacob", "Jens", "Jeppe", "Jesper",
            "Joachim", "Jonas", "Kasper", "Kristian", "Lasse", "Lauritz", "Magnus",
            "Malthe", "Mads", "Mathias", "Mikkel", "Morten", "Nicklas", "Niels",
            "Oliver", "Oscar", "Patrick", "Peder", "Rasmus", "Silas", "Soren",
            "Svend", "Thomas", "Tobias", "Valdemar", "Villads",
        ),
        "last": (
            "Aagaard", "Andresen", "Bang", "Bertelsen", "Bisgaard", "Bjerre",
            "Bodker", "Bruun", "Christoffersen", "Clausen", "Dahlgaard",
            "Damgaard", "Dueholm", "Egeberg", "Ellegaard", "Elsborg", "Fabricius",
            "Faurholt", "Fisker", "Frandsen", "Friis", "Gadeberg", "Gravesen",
            "Grumsen", "Guldbrandsen", "Hjorth", "Holgersen", "Hovgaard",
            "Iversen", "Jacobsen", "Jeppesen", "Jespersen", "Jorgensen",
            "Kjeldsen", "Klausen", "Knudsen", "Krogh", "Lauritzen", "Lindegaard",
            "Ludvigsen", "Madsen", "Mikkelsen", "Molgaard", "Munkholm", "Nordahl",
            "Ostergaard", "Overgaard", "Pedersen", "Poulsen", "Ravn", "Riis",
            "Rosenkilde", "Sandholm", "Skou", "Skovgaard", "Sondergaard",
            "Sorensen", "Steensen", "Storm", "Thomsen", "Thorup", "Toft",
            "Trolle", "Vestergaard", "Vinther", "Wollesen", "Zachariassen",
        ),
    },
    # -- Latvia --------------------------------------------------------------
    "LAT": {
        "first": (
            "Ainars", "Aleksandrs", "Andris", "Armands", "Arturs", "Deniss",
            "Dzintars", "Edgars", "Eduards", "Elvis", "Emils", "Ervins",
            "Gatis", "Girts", "Guntis", "Haralds", "Ilja", "Ivars", "Janis",
            "Juris", "Kalvis", "Karlis", "Kaspars", "Kristers", "Kristians",
            "Lauris", "Maris", "Martins", "Matiss", "Miks", "Nauris", "Normunds",
            "Oskars", "Peteris", "Raitis", "Ralfs", "Renars", "Rihards",
            "Roberts", "Rodrigo", "Sandis", "Toms", "Uvis", "Valters", "Vitalijs",
        ),
        "last": (
            "Abols", "Andersons", "Apinis", "Aploks", "Balodis", "Baltins",
            "Bergmanis", "Berzins", "Birznieks", "Bluks", "Brencis", "Bukovskis",
            "Celmins", "Ciekurs", "Dinsbergs", "Dombrovskis", "Dukurs",
            "Egle", "Eglitis", "Freibergs", "Galvins", "Gavars", "Grinbergs",
            "Grundmanis", "Jansons", "Jaunzems", "Kalnins", "Karklins",
            "Kaugars", "Kaulins", "Kikuts", "Klavins", "Krastins", "Krumins",
            "Kuznecovs", "Lapsa", "Lasmanis", "Legzdins", "Liepins", "Lisovskis",
            "Locmelis", "Malinovskis", "Meija", "Mucenieks", "Nagle", "Ozolins",
            "Ozols", "Pavlovs", "Petersons", "Plavins", "Priedols", "Purmalis",
            "Rasnacs", "Riekstins", "Rubins", "Rudzitis", "Saulitis", "Silins",
            "Skuja", "Skujins", "Smirnovs", "Sprukts", "Strautins", "Stumburs",
            "Sulcs", "Tambijevs", "Tomsons", "Upitis", "Vaivods", "Vasiljevs",
            "Vitols", "Zalitis", "Zarins", "Zeltins", "Zvirbulis",
        ),
    },
}

# Cumulative nationality table, built once. Sorted by key so that adding a nationality later does
# not renumber the existing ones -- see this module's determinism note.
_NAT_CODES: Tuple[str, ...] = tuple(sorted(NATIONALITY_WEIGHTS))
_NAT_CUMULATIVE: Tuple[float, ...] = tuple(
    itertools.accumulate(NATIONALITY_WEIGHTS[code] for code in _NAT_CODES))
_NAT_TOTAL: float = _NAT_CUMULATIVE[-1]

# How many times to re-draw when a caller is tracking used names. Bounded rather than looping to
# exhaustion: the same shape leaguegen._team_name_and_abbrev already uses, and a duplicate name is
# cosmetic noise rather than a correctness problem, so giving up is an acceptable outcome.
_DUPLICATE_RETRIES = 6


def _draw(rng: Rng, pool: Sequence[str]) -> str:
    """Index a pool with a single ``random()`` draw.

    Deliberately not ``rng.choice(pool)``: ``random.choice`` consumes a variable number of bits
    depending on the sequence length, so under it adding one name to a pool shifted the entire
    downstream RNG stream. One ``random()`` makes pool SIZE stream-neutral.
    """
    return pool[int(rng.random() * len(pool))]


def random_nationality(rng: Rng) -> str:
    """Draw a nationality code weighted by ``NATIONALITY_WEIGHTS``."""
    roll = rng.random() * _NAT_TOTAL
    for code, ceiling in zip(_NAT_CODES, _NAT_CUMULATIVE):
        if roll < ceiling:
            return code
    return _NAT_CODES[-1]


def random_name(rng: Rng, used_names: Optional[Set[str]] = None) -> Tuple[str, str]:
    """Return ``(full_name, nationality_code)``.

    Nationality is drawn FIRST and both names come from that nationality's pool, so a player is
    "Mikko Rautiainen" or "Marc-Andre Bergevin" rather than the "Miro Gagnon" the old independent
    draws produced.

    ``used_names`` is an optional set of names already handed out; when given, a collision is
    re-rolled a bounded number of times and the accepted name is added to the set. The nationality
    is re-drawn along with the name -- retrying within one nationality would quietly bias a small
    pool's nationality upward every time it collided.
    """
    for _attempt in range(_DUPLICATE_RETRIES if used_names is not None else 1):
        nationality = random_nationality(rng)
        pool = NAME_POOLS[nationality]
        name = f"{_draw(rng, pool['first'])} {_draw(rng, pool['last'])}"
        if used_names is None:
            return name, nationality
        if name not in used_names:
            used_names.add(name)
            return name, nationality
    used_names.add(name)
    return name, nationality
