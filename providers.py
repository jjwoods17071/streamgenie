"""
Streaming providers, resolved once into a record with separate facets.

WHY THIS EXISTS: one raw TMDB listing string was being asked four different questions —
what to display, what to group by, which logo to use, and whether the user can watch it —
and the correct answers differ. "Netflix Kids" displays as Netflix, groups as netflix, but
must NOT supply Netflix's logo. "Lionsgate+ Amazon Channels" is Lionsgate+, sold through
Prime, and is neither. A single normalise() string could only ever answer one of those, so
every use of it for another purpose was a latent bug — and several shipped.

TMDB's numeric provider_id is stable (verified: 232 names shared across the tv and movie
endpoints, zero id mismatches) but does NOT group: Netflix, Netflix Kids and Netflix
Standard with Ads are 8, 175 and 1796. Paramount+ spans five ids. So the grouping key is
our own slug, and the TMDB id rides along as a precise reference to the exact listing.

Runtime-agnostic: no streamlit, so the API and the self-test can both use it.
"""
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

IMG = "https://image.tmdb.org/t/p/original"

SERVICE = "service"      # a subscription in its own right
CHANNEL = "channel"      # an add-on resold through another service — a SEPARATE charge
BUNDLE = "bundle"        # live-TV / cable storefront carrying many networks
STORE = "store"          # rental / purchase, not a subscription


@dataclass(frozen=True)
class Provider:
    id: str                      # our slug — the grouping key. Never displayed.
    name: str                    # display text
    kind: str = SERVICE
    logo: Optional[str] = None
    via: Optional[str] = None    # slug of the service this is resold through
    tmdb_id: Optional[int] = None
    raw: str = ""

    @property
    def is_extra_cost(self) -> bool:
        """True when having `via` is not enough — a channel is its own subscription."""
        return self.kind == CHANNEL


# Resold add-ons: "<service> Amazon Channel(s)". Plural matters — missing it is what let
# "Lionsgate+ Amazon Channels" fall through to a generic amazon rule and become Prime Video.
_RESELLER_RE = re.compile(
    r"\s+(?P<who>amazon|apple\s*tv|prime\s+video|roku\s+premium)\s+channels?$", re.I)
_RESELLER_SLUG = {"amazon": "prime-video", "prime video": "prime-video",
                  "apple tv": "apple-tv-plus", "appletv": "apple-tv-plus",
                  "roku premium": "roku"}

# Live-TV / cable storefronts. Real, but not where anyone thinks a show "lives".
BUNDLES = {"fubotv", "spectrum on demand", "directv", "directv stream", "philo", "sling tv",
           "xfinity", "youtube tv", "hulu live", "dish", "optimum", "verizon fios"}

STORES = {"apple tv store", "google play movies", "youtube", "microsoft store",
          "fandango at home", "vudu", "amazon video"}

# Deliberately NOT merged into a lookalike. DisneyNOW is the ABC/Disney live-TV app; it was
# being swept into Disney+ by a substring rule and took Disney+'s logo with it.
NEVER_MERGE = {"disneynow", "apple tv store", "amazon video"}

# The consolidations we actually want, as DATA. A chain of `if "disney" in name` is what
# caused the DisneyNOW bug; a table can be read and corrected.
#   match:     exact lowercase names (after reseller/bundle handling) that mean this service
#   canonical: the TMDB listing whose logo represents the service
SERVICES: Dict[str, Dict[str, Any]] = {
    "netflix":       {"name": "Netflix", "canonical": "netflix",
                      "match": ["netflix", "netflix kids", "netflix standard with ads",
                                "netflix basic with ads"]},
    "prime-video":   {"name": "Prime Video", "canonical": "amazon prime video",
                      "match": ["amazon prime video", "prime video",
                                "amazon prime video with ads",
                                "amazon prime video free with ads"]},
    "max":           {"name": "Max", "canonical": "hbo max",
                      "match": ["max", "hbo max", "hbo"]},
    "hulu":          {"name": "Hulu", "canonical": "hulu",
                      "match": ["hulu", "hulu (no ads)"]},
    "disney-plus":   {"name": "Disney+", "canonical": "disney plus",
                      "match": ["disney plus", "disney+"]},
    "apple-tv-plus": {"name": "Apple TV+", "canonical": "apple tv",
                      "match": ["apple tv", "apple tv+", "apple tv plus"]},
    "paramount-plus": {"name": "Paramount+", "canonical": "paramount plus essential",
                       "match": ["paramount plus", "paramount+", "paramount plus essential",
                                 "paramount plus premium"]},
    "peacock":       {"name": "Peacock", "canonical": "peacock premium",
                      "match": ["peacock", "peacock premium", "peacock premium plus"]},
    "amc-plus":      {"name": "AMC+", "canonical": "amc+",
                      "match": ["amc+", "amc plus"]},
    "mgm-plus":      {"name": "MGM+", "canonical": "mgm plus",
                      "match": ["mgm+", "mgm plus"]},
    "starz":         {"name": "Starz", "canonical": "starz", "match": ["starz"]},
    "curiosity":     {"name": "Curiosity Stream", "canonical": "curiosity stream",
                      "match": ["curiosity stream", "curiositystream"]},
    "crunchyroll":   {"name": "Crunchyroll", "canonical": "crunchyroll",
                      "match": ["crunchyroll"]},
    "discovery-plus": {"name": "Discovery+", "canonical": "discovery+",
                       "match": ["discovery+", "discovery plus"]},
}

_BY_MATCH = {m: slug for slug, spec in SERVICES.items() for m in spec["match"]}


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")
    return s or "unknown"


def split_reseller(raw: str):
    """('MGM+ Amazon Channel') -> ('MGM+', 'prime-video'). Base name, and who resells it."""
    name = (raw or "").strip()
    m = _RESELLER_RE.search(name)
    if not m:
        return name, None
    who = re.sub(r"\s+", " ", m.group("who").strip().lower())
    return _RESELLER_RE.sub("", name).strip(), _RESELLER_SLUG.get(who)


def resolve(raw: str, catalogue: Optional[Dict[str, "Provider"]] = None) -> Provider:
    """One TMDB listing -> a Provider. The only place a raw name is interpreted."""
    raw = (raw or "").strip()
    base, via = split_reseller(raw)
    low = base.lower()

    if low in NEVER_MERGE:
        kind = STORE if low in STORES else SERVICE
        return _decorate(Provider(id=_slugify(base), name=base, kind=kind, via=via, raw=raw),
                         catalogue)
    if low in BUNDLES:
        return _decorate(Provider(id=_slugify(base), name=base, kind=BUNDLE, via=via, raw=raw),
                         catalogue)
    if low in STORES:
        return _decorate(Provider(id=_slugify(base), name=base, kind=STORE, via=via, raw=raw),
                         catalogue)

    slug = _BY_MATCH.get(low)
    if slug:
        name = SERVICES[slug]["name"]
    else:
        slug, name = _slugify(base), base

    kind = CHANNEL if via else SERVICE
    return _decorate(Provider(id=slug, name=name, kind=kind, via=via, raw=raw), catalogue)


def _decorate(p: Provider, catalogue) -> Provider:
    """Attach the logo and tmdb_id from the catalogue entry for this slug."""
    entry = (catalogue or {}).get(p.id)
    if not entry:
        return p
    return Provider(id=p.id, name=p.name, kind=p.kind, logo=entry.logo, via=p.via,
                    tmdb_id=entry.tmdb_id, raw=p.raw)


def build_catalogue(fetch: Callable[[str], Dict[str, Any]]) -> Dict[str, Provider]:
    """slug -> Provider carrying the canonical logo and tmdb_id.

    `fetch(path)` is injected so this stays streamlit-free and testable. Several TMDB
    listings collapse to one slug, so the canonical name in SERVICES decides which supplies
    the logo — a last-writer-wins map is what put the ads-tier mark on Netflix.
    """
    best: Dict[str, tuple] = {}
    for path in ("/watch/providers/tv", "/watch/providers/movie"):
        try:
            data = fetch(path) or {}
        except Exception:
            continue
        for row in data.get("results", []):
            name, logo_path = row.get("provider_name"), row.get("logo_path")
            if not name or not logo_path:
                continue
            base, via = split_reseller(name)
            low = base.lower()
            slug = _BY_MATCH.get(low) or _slugify(base)
            rank = _rank(slug, low, bool(via))
            if slug not in best or rank < best[slug][0]:
                best[slug] = (rank, Provider(
                    id=slug, name=SERVICES.get(slug, {}).get("name", base),
                    kind=CHANNEL if via else SERVICE,
                    logo=f"{IMG}{logo_path}", tmdb_id=row.get("provider_id"), raw=name))
    return {slug: p for slug, (_, p) in best.items()}


def _rank(slug: str, low_base: str, is_reseller: bool) -> int:
    """Lower wins. The service's declared canonical listing first, then plain services,
    then resold channels; length breaks ties so "Netflix" beats "Netflix Kids"."""
    if SERVICES.get(slug, {}).get("canonical") == low_base:
        return 0
    return (200 if is_reseller else 100) + len(low_base)


def routes(listings: List[str], catalogue=None) -> List[Provider]:
    """A show's raw listings -> Providers, real subscriptions before channels and bundles."""
    seen, out = set(), []
    for raw in listings or []:
        p = resolve(raw, catalogue)
        key = (p.id, p.via)
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    order = {SERVICE: 0, CHANNEL: 1, STORE: 2, BUNDLE: 3}
    return sorted(out, key=lambda p: order.get(p.kind, 9))


def watchable(providers: List[Provider], subscribed_ids) -> Optional[Provider]:
    """The best way THIS user can watch it, or None.

    A returned Provider with kind == CHANNEL is NOT included in their subscription — it
    merely bills through it. Callers must not present the two the same way; saying
    "included" about a channel sends someone to look for something they can't play.
    """
    subs = {s for s in (subscribed_ids or ())}
    if not subs:
        return None          # never answered is NOT "subscribes to nothing"
    for p in providers:
        if p.kind == SERVICE and p.id in subs:
            return p
    for p in providers:
        if p.via and p.via in subs:
            return p
    return None
