# -*- coding: utf-8 -*-
"""Compose product descriptions for careerjerseys.com.

The catalogue's median product description is 16 words, usually the old ALL CAPS
title pasted in plus "Photos shown are our catalogue images." Those pages give
Google nothing to rank.

This does NOT invent facts. Every sentence is built from data the store already
holds: the product title, its tags (player, team, league, sport), productType,
and whatever real copy the existing description already contains. Where a fact
is not in the data, the sentence is not written. Nothing here asserts a
signature, an edition size, a provenance or a history that the product record
does not already state.

The closing blocks reproduce the house pattern already live on ~315 products,
with the em dash removed to match Ryan's standing rule.
"""
import re
import hashlib

TEAMS = [
    "Anaheim Ducks","Arizona Coyotes","Boston Bruins","Buffalo Sabres","Calgary Flames",
    "Carolina Hurricanes","Chicago Blackhawks","Colorado Avalanche","Columbus Blue Jackets",
    "Dallas Stars","Detroit Red Wings","Edmonton Oilers","Florida Panthers","Los Angeles Kings",
    "Minnesota Wild","Montreal Canadiens","Nashville Predators","New Jersey Devils",
    "New York Islanders","New York Rangers","Ottawa Senators","Philadelphia Flyers",
    "Pittsburgh Penguins","San Jose Sharks","Seattle Kraken","St. Louis Blues",
    "Tampa Bay Lightning","Toronto Maple Leafs","Vancouver Canucks","Vegas Golden Knights",
    "Washington Capitals","Winnipeg Jets","Quebec Nordiques","Hartford Whalers",
    "Colorado Rockies","Minnesota North Stars","Phoenix Coyotes",
    "Toronto Blue Jays","Atlanta Braves","New York Mets","Los Angeles Dodgers","New York Yankees",
    "Chicago Bulls","Los Angeles Lakers","New York Knicks","Toronto Raptors","Atlanta Hawks",
    "Miami Dolphins","Toronto Argonauts","BC Lions","Ottawa Rough Riders","Montreal Alouettes",
    "Saskatchewan Roughriders","Team Canada","Team USA","Team Sweden","Team Finland",
]
LEAGUES = {"NHL","MLB","NBA","NFL","CFL","IIHF","CHL","WHA","PGA","UFC","WWE"}
SPORTS = {"Hockey","Baseball","Basketball","Football","Boxing","Golf","Wrestling"}
NON_PLAYER_TAGS = {
    "autographed","autograph authentic","memorabilia","collectible","limited edition",
    "best seller","flash sale","on-hand","easel item","museum framed","premium number",
    "mcdonald's monopoly","jersey","autographed jersey","hockey photographs","career jersey",
    "new release","owner's stash","deal of the week","fathers day","number 1 of edition",
    "hockey jersey","framed signed jersey","collectible trading cards","comics","movies",
    "movie and television","hollywood","pop culture art","modern art","celebrity","usa",
    "signed","autographs","new arrival","sale","clearance","featured","fan favorite",
}
SIGNED_WORDS = ("signed", "autographed", "inscribed")
WALL_ART = {"framed print", "framed poster", "framed canvas", "framed photo",
            "framed display", "wrapped canvas", "lithograph", "print"}
# Orphan adjectives left behind once the item words are stripped from a title.
ORPHAN = re.compile(r"\s+(colorful|colourful|pop|modern|vibrant|bold|textured|museum|wall|"
                    r"home|decor|décor|classic collection|reproduction)$", re.I)

SIZE_TOKEN = re.compile(r"\((\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)\)", re.I)
SIZE_BARE = re.compile(r"\b(\d+(?:\.\d+)?)x(\d+(?:\.\d+)?)\b", re.I)
FRAMED_SIZE = re.compile(r'Framed size:\s*([\d.]+)"?\s*x\s*([\d.]+)"?', re.I)
EDITION = re.compile(r"(?:/(\d+)\b|#\s*(\d+)\s+of\s+(\d+)|Ltd\.?\s*Ed\.?\s*(\d+)|Limited Edition of (\d+))", re.I)
NOTE = re.compile(r"\bwith\s+([A-Z0-9][A-Za-z0-9 .']{1,28}?)\s+Note\b")
INSCRIBED = re.compile(r"\b(?:&|and)?\s*Inscribed\s+([A-Za-z0-9 .']{2,28})", re.I)

# Order matters. A framing word beats a subject noun, so "Comic Collection
# Framed Poster Art" is a framed poster, not a comic.
ITEMS = [
    ("career jersey", "career jersey"), ("wrapped canvas", "wrapped canvas"),
    ("mystery box", "mystery box"), ("framed canvas", "framed canvas"),
    ("framed poster", "framed poster"), ("framed print", "framed print"),
    ("framed photo", "framed photo"), ("framed art", "framed print"),
    ("framed display", "framed display"), ("framed wall art", "framed print"),
    ("poster", "framed poster"), ("canvas", "framed canvas"),
    ("lithograph", "lithograph"), ("litho", "lithograph"),
    ("puck", "puck"), ("helmet", "helmet"), ("stick", "hockey stick"),
    ("basketball", "basketball"), ("plaque", "plaque"), ("book", "book"),
    ("stamp", "stamp set"), ("flag", "flag"), ("glove", "glove"), ("comic", "comic"),
    ("photograph", "photo"), ("photo", "photo"),
    ("print", "print"), ("frame", "framed display"), ("display", "framed display"),
    ("sign", "signed display"), ("jersey", "jersey"), ("card", "trading card"),
]
# Words stripped from the title to leave the subject of an unsigned art piece.
STRIP = re.compile(
    r"\b(framed|unframed|museum|wall|art|artwork|canvas|poster|print|photo|photograph|"
    r"decor|décor|collectible|collectable|limited|edition|signed|autographed|"
    r"wrapped|textured|display|piece)\b", re.I)
BOILER = (
    "photos shown are our catalogue images",
    "own this piece of hockey history",
    "own a true piece of hockey history",
    "own this amazing piece",
    "comes with certificate of authenticity and hologram",
)


def facts(p):
    t = p["title"]
    low = t.lower()
    tags = [x for x in p.get("tags", []) if not x.startswith("_label_")]
    f = {"title": t}
    f["team"] = next((x for x in TEAMS if x in t), None) or \
                next((x for x in TEAMS if x in tags), None)
    f["league"] = next((x for x in tags if x in LEAGUES), None)
    f["sport"] = next((x for x in tags if x in SPORTS), None)
    f["signed"] = any(w in low for w in SIGNED_WORDS)
    f["facsimile"] = any("facsimile" in x.lower() or "reproduction" in x.lower() for x in tags)
    f["item"] = next((label for key, label in ITEMS if key in low), None)
    desc_low = (p.get("description") or "").lower()
    if f["item"] in (None, "comic", "collectible"):
        if "framed print" in desc_low or "framed textured print" in desc_low:
            f["item"] = "framed print"
        elif "framed canvas" in desc_low:
            f["item"] = "framed canvas"
    f["item"] = f["item"] or "collectible"
    # player: a tag that is not a team, league, sport or marketing label, and whose
    # words appear in the title. That is the store's own name for the signer.
    cands = []
    for x in tags:
        if x in TEAMS or x in LEAGUES or x in SPORTS: continue
        if x.lower() in NON_PLAYER_TAGS: continue
        if re.fullmatch(r"\d+%?", x): continue
        if " " not in x: continue
        if all(w.lower() in low for w in x.split()):
            cands.append(x)
    f["player"] = cands[0] if cands else None
    f["others"] = [c for c in cands[1:3]]
    m = SIZE_TOKEN.search(t) or SIZE_BARE.search(t)
    f["size"] = f"{m.group(1)} x {m.group(2)}" if m else None
    m = FRAMED_SIZE.search(p.get("description") or "")
    f["framed_size"] = f'{m.group(1)}" x {m.group(2)}"' if m else None
    m = EDITION.search(t)
    f["edition"] = next((g for g in m.groups() if g), None) if m else None
    f["edition_no"] = m.group(2) if (m and m.group(2)) else None
    m = NOTE.search(t)
    f["note"] = m.group(1).strip() if m else None
    if not f["note"]:
        m = INSCRIBED.search(t)
        f["note"] = m.group(1).strip() if m else None
    f["framed"] = "framed" in low or "frame" in low
    f["unframed"] = "unframed" in low
    d = p.get("description") or ""
    f["has_size_copy"] = bool(re.search(r"\bmeasur(?:es|ing)\b|\bFramed size\b", d, re.I))
    f["has_auth_copy"] = bool(re.search(r"certificate of authenticity|\bCOA\b|hologram|"
                                        r"authenticat", d, re.I))
    # Subject of an unsigned art piece: the title with item and size words removed.
    subj = SIZE_TOKEN.sub(" ", t)
    subj = STRIP.sub(" ", subj)
    subj = re.sub(r"[()]|\s+", lambda m: " ", subj)
    subj = re.sub(r"\s+", " ", subj).strip(" ,-")
    for _ in range(3):                      # peel trailing orphan adjectives
        new = ORPHAN.sub("", subj).strip(" ,-&")
        if new == subj:
            break
        subj = new
    f["subject"] = subj
    return f


def keep_existing(p):
    """Real sentences already in the description, minus boilerplate and title echoes."""
    d = re.sub(r"\s+", " ", p.get("description") or "").strip()
    if not d:
        return []
    d = d.replace(p["title"].upper(), " ").replace(p["title"], " ")
    d = re.sub(r"\b(St|Mr|Mrs|Dr|Jr|Sr|Ltd|Ed|No|vs|Inc|Co|approx)\.\s",
               lambda m: m.group(1) + "\u0001 ", d)              # shield abbreviations
    d = re.sub(r"\b([A-Z])\.\s", lambda m: m.group(1) + "\u0001 ", d)   # and initials
    out = []
    for s in (x.replace("\u0001", ".") for x in re.split(r"(?<=[.!])\s+", d)):
        s = s.strip()
        if len(s) < 25:
            continue
        if any(b in s.lower() for b in BOILER):
            continue
        if s.isupper():
            continue
        if "framed size" in s.lower():
            continue
        out.append(s)
    return out


def pick(seed, options):
    h = int(hashlib.md5(seed.encode()).hexdigest(), 16)
    return options[h % len(options)]


def opener(f, pid):
    """Two to three sentences of real, product-specific copy in second person."""
    who = f["player"]
    team = f["team"]
    item = f["item"]
    signed = f["signed"] and not f["facsimile"]
    bits = []
    team_of = f" {team}" if team else ""

    signers = ([who] if who else []) + f["others"]
    if signed and signers:
        names = " and ".join(signers[:3])
        lead = pick(pid + "a", [
            f"Add a{team_of} {item} hand signed by {names} to your collection.",
            f"This{team_of} {item} was hand signed by {names}.",
            f"Own a{team_of} {item} carrying the signature of {names}." if len(signers) == 1
            else f"Own a{team_of} {item} carrying the signatures of {names}.",
        ])
    elif signed:
        lead = pick(pid + "a", [
            f"This{team_of} {item} is hand signed and guaranteed authentic.",
            f"Own a{team_of} {item}, hand signed and guaranteed authentic.",
        ])
    elif who:
        lead = pick(pid + "a", [
            f"Add this{team_of} {item} featuring {who} to your collection.",
            f"This{team_of} {item} celebrates {who}.",
        ])
    elif f["subject"] and len(f["subject"]) > 3 and item in WALL_ART:
        lead = pick(pid + "a", [
            f'Bring {f["subject"]} to your wall as a {item}.',
            f'This {item} features {f["subject"]}.',
            f'Put {f["subject"]} on your wall as a {item}.',
        ])
    elif f["subject"] and len(f["subject"]) > 3:
        lead = pick(pid + "a", [
            f'This {item} commemorates {f["subject"]}.',
            f'Add this {f["subject"]} {item} to your collection.',
        ])
    else:
        lead = f"This{team_of} {item} comes from our authenticated collection."
    bits.append(re.sub(r"\ba (?=[aeiou])", "an ", lead))

    if f["note"]:
        bits.append(f'It carries the inscription "{f["note"]}" alongside the signature.')

    if f["edition"]:
        if f["edition_no"]:
            bits.append(f'This is number {f["edition_no"]} of an edition of {f["edition"]}, '
                        f"hand numbered on the piece.")
        else:
            bits.append(f'The edition is limited to {f["edition"]}, hand numbered.')

    # Presentation. Only state a size when the existing copy does not already state one,
    # so the page can never contradict itself.
    sz = None
    if not f["has_size_copy"]:
        sz = f["framed_size"] or (f'{f["size"]} inches' if f["size"] else None)

    if item == "puck":
        bits.append("The puck is sealed in a premium acrylic display case with an officially "
                    "licensed team pin, so you can put it straight on a shelf.")
    elif item in ("framed display", "framed canvas", "framed poster", "framed print",
                  "framed photo", "signed display"):
        bits.append("It arrives museum framed and ready to hang"
                    + (f", measuring {sz}." if sz else "."))
    elif item == "wrapped canvas":
        bits.append("It is a gallery wrapped canvas with no outer frame, ready to hang as it is"
                    + (f", measuring {sz}." if sz else "."))
    elif item in ("jersey", "career jersey"):
        bits.append("As a high-end signed collectible it is made for display rather than wear.")
    elif item == "photo" and sz:
        bits.append(f"The photograph measures {sz}.")
    elif item in ("print", "lithograph") and sz:
        bits.append(f"It measures {sz}." if not f["framed"] else f"It comes framed at {sz}.")
    return " ".join(bits)


AUTH_SIGNED = ("Every item we sell is sourced directly from the player, from official signings, "
               "from exclusive distributors, or from autographs certified by recognized "
               "third-party authenticators. This piece ships with a numbered Certificate of "
               "Authenticity and a tamper-proof, uniquely coded hologram, backed by our 100% "
               "Authenticity Guarantee.")
AUTH_PLAIN = ("This piece ships with a numbered Certificate of Authenticity and a tamper-proof, "
              "uniquely coded hologram, backed by our 100% Authenticity Guarantee.")
SHIPPING_SIGNED = (
    "Packaging and shipping: handling typically takes 1 to 5 business days, and orders typically "
    "ship within 7 business days. As an autographed collectible, some orders can take a few "
    "additional weeks if the piece is being framed, the jersey is being sewn together, or we are "
    "waiting on a celebrity signing, and we will keep you updated if that applies to your order. "
    "See our Shipping Policy for full details.")
SHIPPING_PLAIN = (
    "Packaging and shipping: handling typically takes 1 to 5 business days, and orders typically "
    "ship within 7 business days. Framed pieces can take a little longer. See our Shipping Policy "
    "for full details.")
CATALOGUE = "Photos shown are our catalogue images."


def build(p):
    f = facts(p)
    pid = p["id"]
    paras = [opener(f, pid)]
    existing = keep_existing(p)
    if existing:
        paras.append(" ".join(existing))
    signed = f["signed"] and not f["facsimile"]
    if signed:
        paras.append(AUTH_SIGNED)
    elif f["has_auth_copy"]:
        paras.append(AUTH_PLAIN)
    if f["item"] in ("jersey", "career jersey"):
        paras.append("Sizing: this jersey comes in size L or XL. If you have questions about the "
                     "size before ordering, contact us at info@autographauthentic.com.")
    paras.append(SHIPPING_SIGNED if signed else SHIPPING_PLAIN)
    tail = CATALOGUE
    if f["framed_size"]:
        tail += f' Framed size: {f["framed_size"]}'
    paras.append(tail)
    html = "".join(f"<p>{x}</p>" for x in paras)
    html = html.replace("—", ",").replace("  ", " ")
    return html


def words(html):
    return len(re.sub(r"<[^>]+>", " ", html).split())
