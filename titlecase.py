"""Title Case for Google Shopping feed titles.

Google's product data spec tells merchants not to use block capitals in the
`title` attribute. Every value in custom.full_title is ALL CAPS, so this module
recases them on the way into the feed. The Shopify metafield is left alone,
which keeps the storefront source of truth stable and makes a revert one commit.

Casing is LEARNED from the store's own human-written storefront titles, tags,
vendor and product type, so acronyms (NHL, COA, CCM) and names (MacInnis,
McDavid) come back right instead of being guessed. Anything the store never
writes in mixed case falls through to explicit rules below.

The transform is letter-for-letter lossless: only capitalisation changes, never
characters. `titlecase` asserts that, so a bad rule fails the build instead of
quietly shipping a mangled title to Google.
"""

import re
import collections

# Must stay upper case even where the store never writes them in prose.
ACRONYMS = {
    "NHL", "NBA", "MLB", "NFL", "CFL", "AHL", "WHA", "OHL", "CHL", "QMJHL",
    "WHL", "IIHF", "PGA", "UFC", "MMA", "WWE", "MLS", "NCAA", "NASCAR", "WJC",
    "ASG", "NHLPA", "HHOF",
    "COA", "UDA", "JSA", "PSA", "DNA", "GNR", "HOF", "MVP", "ROY", "KO", "TKO",
    "COR", "ROM",
    "CCM", "CN", "DC", "USA", "US", "UK", "EU", "TV", "LP", "HD", "BC", "LA",
    "NY", "OT", "AP",
    "XL", "XXL", "XS", "S", "M", "L",
    "R2", "D2", "C3PO", "AK",
}
# Correct spellings the store itself is inconsistent about.
NAMES = {
    "LAFONTAINE": "LaFontaine",
    "LECLAIR": "LeClair",
    "VANBIESBROUCK": "VanBiesbrouck",
    "MACINNIS": "MacInnis",
    "MACKINNON": "MacKinnon",
    "MACLEISH": "MacLeish",
    "LEBRON": "LeBron",
}
SMALL = {"a", "an", "the", "and", "or", "of", "in", "on", "at", "to", "for",
         "with", "by", "vs", "from", "as", "is", "its"}
# Proper names that contain a small word and must keep their capitals.
# Only names where the small word is part of the name itself. "Legends of the
# Crease" and "Revenge of the Jedi" are correct lower case and stay out.
PHRASES = {
    "THE GOAL": "The Goal", "THE GREAT ONE": "The Great One",
    "THE GOLDEN JET": "The Golden Jet", "THE FLYING GOAL": "The Flying Goal",
    "THE MASK": "The Mask", "THE LAUNCH": "The Launch", "THE ROCKET": "The Rocket",
    "THE MOTION PICTURE": "The Motion Picture", "THE FLOWER": "The Flower",
    "THE EMPIRE STRIKES BACK": "The Empire Strikes Back",
    "THE MANDALORIAN": "The Mandalorian",
}
ROMAN = {"II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "XI", "XII", "XIII"}
ORD = re.compile(r"^(\d+)(ST|ND|RD|TH)$", re.I)
DIM = re.compile(r"^(\d+(?:\.\d+)?)X(\d+(?:\.\d+)?)$", re.I)
INITIALS = re.compile(r"^(?:[A-Za-z]\.){2,}$")
TOKEN = re.compile(
    r"[A-Za-z0-9'’.\-/&#%“”]*[A-Za-z0-9][A-Za-z0-9'’.\-/&#%]*"
)
# A small word stays capitalised when it opens a quoted or bracketed phrase.
OPENERS = set('"“‘\'([-–—:,/')


def build_casing(products):
    """upper(token) -> the cased form the store itself uses most often.

    `products` is an iterable of dicts with any of title, vendor, productType,
    tags. ALL CAPS source words are skipped because they teach nothing.
    """
    counts = collections.defaultdict(collections.Counter)
    for p in products:
        sources = [p.get("title") or "", p.get("vendor") or "",
                   p.get("productType") or ""]
        sources += [t for t in (p.get("tags") or []) if not t.startswith("_label_")]
        for s in sources:
            for w in re.findall(r"[A-Za-z][A-Za-z'’.\-]*", s):
                if w.isupper() and len(w) > 3:
                    continue
                counts[w.upper()][w] += 1
    return {k: v.most_common(1)[0][0] for k, v in counts.items()}


def _cap(u):
    """Upper-case the first LETTER, lower the rest, so a leading quote survives."""
    for i, ch in enumerate(u):
        if ch.isalpha():
            return u[:i] + ch.upper() + u[i + 1:].lower()
    return u


def _word(w, casing, small_ok):
    u = w.upper()
    if u in NAMES:
        return NAMES[u]
    if INITIALS.match(w):                 # A.J.  L.A.  J.S.  P.K.
        return u
    if u in ACRONYMS or u in ROMAN:
        return u
    m = ORD.match(w)
    if m:                                 # 51ST -> 51st
        return m.group(1) + m.group(2).lower()
    m = DIM.match(w)
    if m:                                 # 8X10 -> 8x10
        return f"{m.group(1)}x{m.group(2)}"
    for sep in ("-", "/"):                # SCI-FI, I/O
        if sep in w and len(w) >= 3:
            return sep.join(_word(part, casing, False) if part else ""
                            for part in w.split(sep))
    if small_ok and u.lower() in SMALL:
        return u.lower()
    if u in casing:
        return casing[u]
    if u.startswith("MC") and len(u) > 3:
        return "Mc" + u[2].upper() + u[3:].lower()
    if u.startswith("MAC") and len(u) > 4:
        return "Mac" + u[3].upper() + u[4:].lower()
    if u.startswith("O'") and len(u) > 3:
        return "O'" + u[2].upper() + u[3:].lower()
    return _cap(u)


def titlecase(value, casing):
    """Recase an ALL CAPS title. Mixed-case input is returned untouched."""
    if not value or value != value.upper():
        return value
    original = value
    for up, cased in PHRASES.items():
        value = re.sub(r"\b" + re.escape(up) + r"\b", cased, value)
    out, pos, first = [], 0, True
    for m in TOKEN.finditer(value):
        out.append(value[pos:m.start()])
        back = value[:m.start()].rstrip()
        prev = back[-1] if back else ""
        opens = first or prev in OPENERS
        tok = m.group(0)
        out.append(tok if tok != tok.upper()
                   else _word(tok, casing, small_ok=not opens))
        pos = m.end()
        first = False
    out.append(value[pos:])
    result = "".join(out)
    assert result.upper() == original.upper(), (original, result)
    return result


def unlearned(values, casing):
    """Tokens that fell through to the generic rule, for human review."""
    out = collections.Counter()
    for v in values:
        if not v or v != v.upper():
            continue
        for w in re.findall(r"[A-Za-z][A-Za-z'’.\-]*", v):
            u = w.upper()
            if u in ACRONYMS or u in ROMAN or u in NAMES or u in casing:
                continue
            out[u] += 1
    return out
