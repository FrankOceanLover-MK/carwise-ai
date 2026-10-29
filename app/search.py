"""Deterministic filtering and scoring for live car listings."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.external_apis import fetch_active_listings

logger = logging.getLogger(__name__)

# Pages of Auto.dev results to scan when the shopper asks for a specific fuel type, model or color.
FUEL_SEARCH_PAGES = 6


@dataclass
class ScoreBreakdown:
    price: float
    mileage: float
    distance: float
    economy: float
    safety: float

    @property
    def total(self) -> float:
        return (
            0.30 * self.price
            + 0.25 * self.mileage
            + 0.15 * self.distance
            + 0.20 * self.economy
            + 0.10 * self.safety
        )


@dataclass
class ListingWithScore:
    listing: Dict[str, Any]
    breakdown: ScoreBreakdown

    @property
    def total_score(self) -> float:
        return self.breakdown.total


@dataclass
class SearchCriteria:
    budget: Optional[float] = None
    max_distance: Optional[float] = None
    body_style: Optional[str] = None
    fuel_type: Optional[str] = None
    make: Optional[str] = None
    model: Optional[str] = None
    color: Optional[str] = None
    zip_code: Optional[str] = None  # origin for distance filtering (5-digit US ZIP)

# --------------------------------------------------------------------------------------
# Fuel / powertrain matching
#
# Auto.dev reports the *engine* fuel, so a hybrid often shows up as "Gasoline" and many EVs
# have an empty fuel field. Trusting that one field drops real hybrids and EVs, so we also
# look at the model, trim and title, and at a small table of vehicles that only come as a
# hybrid or only as an EV.
# --------------------------------------------------------------------------------------

_FUEL_ALIASES = {
    "gas": "gasoline", "gasoline": "gasoline", "petrol": "gasoline", "regular": "gasoline",
    "ev": "electric", "bev": "electric", "electric": "electric",
    "all-electric": "electric", "all electric": "electric", "battery electric": "electric",
    "battery": "electric", "zero emission": "electric",
    "hybrid": "hybrid", "hev": "hybrid", "hybrid electric": "hybrid",
    "phev": "plug-in", "plug-in": "plug-in", "plug in": "plug-in", "plugin": "plug-in",
    "plug-in hybrid": "plug-in", "plug in hybrid": "plug-in",
    "diesel": "diesel", "turbo diesel": "diesel",
    "flex": "flex", "flex fuel": "flex", "flex-fuel": "flex", "e85": "flex",
    "hydrogen": "hydrogen", "fuel cell": "hydrogen",
}

# (make, model prefix, first model year). Models that are only sold as hybrids from that year.
_HYBRID_ONLY = [
    ("toyota", "prius", 0), ("toyota", "camry", 2025), ("toyota", "sienna", 2021),
    ("toyota", "venza", 2021), ("toyota", "crown", 2023), ("toyota", "c-hr", 9999),
    ("honda", "insight", 0), ("honda", "cr-z", 0),
    ("ford", "c-max", 0), ("lexus", "ct", 0), ("hyundai", "ioniq hybrid", 0),
    ("kia", "niro hybrid", 0),
]

# (make, model prefix). Models that are only sold as EVs.
_EV_ONLY = [
    ("nissan", "leaf"), ("nissan", "ariya"), ("chevrolet", "bolt"), ("chevrolet", "spark ev"),
    ("chevrolet", "equinox ev"), ("chevrolet", "blazer ev"), ("chevrolet", "silverado ev"),
    ("hyundai", "ioniq 5"), ("hyundai", "ioniq 6"), ("hyundai", "ioniq 9"),
    ("hyundai", "kona electric"), ("hyundai", "ioniq electric"),
    ("kia", "ev6"), ("kia", "ev9"), ("kia", "ev3"), ("kia", "niro ev"), ("kia", "soul ev"),
    ("ford", "mustang mach-e"), ("ford", "mach-e"), ("ford", "f-150 lightning"),
    ("ford", "lightning"), ("ford", "e-transit"),
    ("volkswagen", "id.4"), ("volkswagen", "id.buzz"), ("volkswagen", "e-golf"),
    ("audi", "e-tron"), ("audi", "q4 e-tron"), ("audi", "q8 e-tron"), ("audi", "q6 e-tron"),
    ("audi", "rs e-tron"),
    ("porsche", "taycan"), ("bmw", "i3"), ("bmw", "i4"), ("bmw", "i5"), ("bmw", "i7"),
    ("bmw", "ix"), ("toyota", "bz4x"), ("subaru", "solterra"), ("lexus", "rz"),
    ("cadillac", "lyriq"), ("cadillac", "optiq"), ("cadillac", "vistiq"),
    ("cadillac", "escalade iq"), ("cadillac", "celestiq"), ("gmc", "hummer ev"),
    ("gmc", "sierra ev"), ("honda", "prologue"), ("acura", "zdx"), ("mazda", "mx-30"),
    ("jaguar", "i-pace"), ("fiat", "500e"), ("mini", "cooper se"), ("mini", "countryman se"),
    ("volvo", "ex30"), ("volvo", "ex90"), ("volvo", "ec40"), ("volvo", "xc40 recharge"),
    ("mercedes-benz", "eqb"), ("mercedes-benz", "eqe"), ("mercedes-benz", "eqs"),
    ("mercedes-benz", "eqa"), ("mercedes-benz", "g 580"), ("genesis", "gv60"),
    ("genesis", "electrified"), ("dodge", "charger daytona"), ("jeep", "wagoneer s"),
    ("jeep", "recon"), ("smart", "fortwo electric"), ("mitsubishi", "i-miev"),
]

# Brands that only sell EVs.
_EV_ONLY_MAKES = {"tesla", "rivian", "lucid", "polestar", "fisker", "vinfast", "faraday future"}


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def _year(listing: Dict[str, Any]) -> int:
    try:
        return int(listing.get("year") or 0)
    except (TypeError, ValueError):
        return 0


def _model_starts_with(model: str, prefix: str) -> bool:
    return model == prefix or model.startswith(prefix + " ") or model.startswith(prefix + "-")


def _text_blob(listing: Dict[str, Any]) -> str:
    parts = [listing.get(k) for k in ("fuel_type", "model", "trim", "title", "name", "engine")]
    return " ".join(_norm(p) for p in parts if p)


def _is_plug_in(listing: Dict[str, Any]) -> bool:
    blob = _text_blob(listing)
    make, model = _norm(listing.get("make")), _norm(listing.get("model"))
    if any(w in blob for w in ("plug-in", "plug in", "plugin", "phev", "4xe")):
        return True
    return make == "toyota" and bool(re.search(r"\bprime\b", blob))


def _is_hybrid(listing: Dict[str, Any]) -> bool:
    """True for hybrids and plug-in hybrids (not mild-hybrid marketing alone)."""
    blob = _text_blob(listing)
    make, model, year = _norm(listing.get("make")), _norm(listing.get("model")), _year(listing)
    fuel = _norm(listing.get("fuel_type"))
    if "hybrid" in blob or _is_plug_in(listing):
        return True
    if "electric" in fuel and ("gas" in fuel or "petrol" in fuel):
        return True
    if re.search(r"\b\d{3}h\b", model + " " + _norm(listing.get("trim"))):  # Lexus 300h, 450h
        return True
    if re.search(r"\bhev\b", blob):
        return True
    return any(
        make == m and _model_starts_with(model, mod) and year >= first
        for m, mod, first in _HYBRID_ONLY
    )


def _is_electric(listing: Dict[str, Any]) -> bool:
    """True for fully electric vehicles. Hybrids and plug-ins are not counted."""
    if _is_hybrid(listing):
        return False
    blob = _text_blob(listing)
    make, model = _norm(listing.get("make")), _norm(listing.get("model"))
    if "electric" in _norm(listing.get("fuel_type")) or re.search(r"\b(ev|bev)\b", blob):
        return True
    if make in _EV_ONLY_MAKES:
        return True
    return any(make == m and _model_starts_with(model, mod) for m, mod in _EV_ONLY)


def _normalize_fuel(wanted: str) -> str:
    w = _norm(wanted)
    return _FUEL_ALIASES.get(w, w)


def _fuel_matches(listing: Dict[str, Any], wanted: str) -> bool:
    """Does this listing match the fuel / powertrain the shopper asked for?"""
    target = _normalize_fuel(wanted)
    if not target:
        return True
    blob = _text_blob(listing)
    fuel = _norm(listing.get("fuel_type"))

    if target == "hybrid":
        return _is_hybrid(listing)
    if target == "plug-in":
        return _is_plug_in(listing)
    if target == "electric":
        return _is_electric(listing)
    if target == "gasoline":
        # A "gas" shopper does not want a hybrid or EV. Unknown fuel counts as gas.
        if _is_hybrid(listing) or _is_electric(listing):
            return False
        return fuel == "" or any(w in fuel for w in ("gas", "petrol", "unleaded", "regular", "premium"))
    if target == "diesel":
        return "diesel" in blob
    if target == "flex":
        return "flex" in blob or "e85" in blob
    if target == "hydrogen":
        return "hydrogen" in blob or "fuel cell" in blob or _norm(listing.get("model")) == "mirai"
    return target in blob  # anything unfamiliar: plain text match

_MAKE_ALIASES = {
    "chevy": "Chevrolet", "vw": "Volkswagen", "volks": "Volkswagen", "merc": "Mercedes-Benz",
    "mercedes": "Mercedes-Benz", "benz": "Mercedes-Benz", "mercedes benz": "Mercedes-Benz",
    "land rover": "Land Rover", "range rover": "Land Rover", "rolls royce": "Rolls-Royce",
    "alfa": "Alfa Romeo", "aston": "Aston Martin", "caddy": "Cadillac",
}
_KNOWN_MAKES = [
    "Acura", "Alfa Romeo", "Aston Martin", "Audi", "Bentley", "BMW", "Buick", "Cadillac",
    "Chevrolet", "Chrysler", "Dodge", "Ferrari", "Fiat", "Fisker", "Ford", "Genesis", "GMC",
    "Honda", "Hummer", "Hyundai", "Infiniti", "Jaguar", "Jeep", "Kia", "Lamborghini",
    "Land Rover", "Lexus", "Lincoln", "Lucid", "Maserati", "Mazda", "McLaren", "Mercedes-Benz",
    "Mercury", "Mini", "Mitsubishi", "Nissan", "Oldsmobile", "Plymouth", "Polestar", "Pontiac",
    "Porsche", "Ram", "Rivian", "Rolls-Royce", "Saab", "Saturn", "Scion", "Smart", "Subaru",
    "Suzuki", "Tesla", "Toyota", "VinFast", "Volkswagen", "Volvo",
]
_CANONICAL_MAKES = {m.lower(): m for m in _KNOWN_MAKES}


def canonical_make(value: Optional[str]) -> Optional[str]:
    """Turn 'chevy', 'toyota', 'BMW' into the spelling Auto.dev uses ('Chevrolet', 'Toyota', 'BMW')."""
    v = _norm(value)
    if not v:
        return None
    v = _MAKE_ALIASES.get(v, v)
    return _CANONICAL_MAKES.get(v.lower(), v.title() if isinstance(v, str) and v == v.lower() else v)


def _squash(value: Any) -> str:
    """Lowercase and drop punctuation/spaces, so 'CR-V', 'cr v' and 'crv' all compare equal."""
    return re.sub(r"[^a-z0-9]", "", _norm(value))


def _model_matches(listing: Dict[str, Any], wanted: str) -> bool:
    w = _squash(wanted)
    if not w:
        return True
    model = _squash(listing.get("model"))
    if model:
        return model.startswith(w)
    return w in _squash(listing.get("title") or listing.get("name"))

# Dealers use fancy paint names ("Midnight Black Metallic", "Magnetic Gray", "Soul Red Crystal"), so we map
# keywords in the name to a simple color family and compare families.
_COLOR_FAMILIES = {
    "black": ["black", "onyx", "obsidian", "ebony", "jet", "noir", "midnight", "shadow", "raven", "carbon", "nero"],
    "white": ["white", "pearl", "alpine", "frost", "glacier", "snow", "polar", "ivory", "blanc", "bianco", "cream"],
    "gray": ["gray", "grey", "charcoal", "graphite", "gunmetal", "granite", "slate", "magnetic", "meteor",
             "steel", "titanium", "cement", "storm", "stealth", "ash", "nardo"],
    "silver": ["silver", "platinum", "sterling", "lunar", "billet", "argent", "ingot", "quartz"],
    "red": ["red", "burgundy", "maroon", "crimson", "ruby", "cherry", "scarlet", "cardinal", "garnet",
            "cayenne", "rosso", "wine", "candy", "ruby"],
    "blue": ["blue", "navy", "cobalt", "sapphire", "azure", "indigo", "denim", "ocean", "marine", "cyan", "teal"],
    "green": ["green", "emerald", "olive", "forest", "sage", "lime", "army", "jade", "mint"],
    "yellow": ["yellow", "gold", "lemon", "sunflower", "mustard", "banana"],
    "orange": ["orange", "copper", "tangerine", "burnt", "sunset", "amber"],
    "brown": ["brown", "bronze", "chocolate", "mocha", "espresso", "coffee", "cocoa", "walnut", "mahogany"],
    "beige": ["beige", "tan", "sand", "champagne", "khaki", "taupe", "desert", "latte", "camel", "bisque"],
    "purple": ["purple", "violet", "plum", "amethyst", "lavender", "magenta", "grape"],
    "pink": ["pink", "rose", "blush", "fuchsia", "salmon", "coral"],
}
_COLOR_ALIASES = {"grey": "gray", "gold": "yellow", "tan": "beige", "teal": "blue", "turquoise": "blue"}


def _color_families(text: Any) -> set:
    words = set(re.findall(r"[a-z]+", _norm(text)))
    return {fam for fam, keys in _COLOR_FAMILIES.items() if words.intersection(keys)}


def _wanted_color_family(wanted: str) -> Optional[str]:
    w = _norm(wanted)
    w = _COLOR_ALIASES.get(w, w)
    if w in _COLOR_FAMILIES:
        return w
    fams = _color_families(w)
    return next(iter(fams)) if len(fams) == 1 else None


def _color_matches(listing: Dict[str, Any], wanted: str) -> bool:
    """True if the listing's exterior color is in the requested color family."""
    listing_color = listing.get("color")
    if not listing_color:
        return False  # asked for a color and we can't confirm it, so don't show it
    fam = _wanted_color_family(wanted)
    if fam is None:
        return _norm(wanted) in _norm(listing_color)  # unfamiliar color word: plain text match
    return fam in _color_families(listing_color)


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _price_score(price: Optional[float], budget: Optional[float]) -> float:
    if price is None:
        return 0.5
    if budget is None:
        return 0.6

    if price <= budget:
        if price >= 0.7 * budget:
            return 1.0
        return 0.6 + 0.4 * (price / (0.7 * budget))
    over = price - budget
    if over <= 0.1 * budget:
        return 0.6 * (1 - over / (0.1 * budget))
    return 0.05


def _mileage_score(mileage: Optional[float]) -> float:
    if mileage is None:
        return 0.5
    if mileage <= 30000:
        return 1.0
    if mileage <= 90000:
        return _clamp(1 - (mileage - 30000) / 60000)
    if mileage <= 120000:
        return 0.2
    return 0.05


def _distance_score(distance_miles: Optional[float], max_distance: Optional[float]) -> float:
    if distance_miles is None:
        return 0.5
    if max_distance is None:
        max_distance = 100.0
    if distance_miles <= max_distance:
        return 1.0
    if distance_miles <= 2 * max_distance:
        return _clamp(1 - (distance_miles - max_distance) / max_distance)
    return 0.05


def _economy_score(city_mpg: Optional[float], highway_mpg: Optional[float]) -> float:
    if city_mpg is None and highway_mpg is None:
        return 0.5
    mpg = 0.0
    weight = 0.0
    if city_mpg is not None:
        mpg += 0.6 * city_mpg
        weight += 0.6
    if highway_mpg is not None:
        mpg += 0.4 * highway_mpg
        weight += 0.4
    if weight == 0:
        return 0.5
    mpg /= weight

    if mpg <= 20:
        return 0.2
    if mpg >= 35:
        return 1.0
    return 0.2 + 0.8 * ((mpg - 20) / 15.0)


def _safety_score(stars: Optional[float]) -> float:
    if stars is None:
        return 0.5
    return _clamp(stars / 5.0)


def score_listing(listing: Dict[str, Any], criteria: SearchCriteria) -> ListingWithScore:
    price = listing.get("price")
    mileage = listing.get("mileage")
    distance_miles = listing.get("distance_miles")
    city_mpg = listing.get("city_mpg")
    highway_mpg = listing.get("highway_mpg")
    safety = listing.get("safety_rating")

    bd = ScoreBreakdown(
        price=_price_score(price, criteria.budget),
        mileage=_mileage_score(mileage),
        distance=_distance_score(distance_miles, criteria.max_distance),
        economy=_economy_score(city_mpg, highway_mpg),
        safety=_safety_score(safety),
    )

    return ListingWithScore(listing=listing, breakdown=bd)


def _passes_filters(listing: Dict[str, Any], criteria: SearchCriteria) -> bool:
    # Make filter
    if criteria.make:
        make = (listing.get("make") or "").lower()
        if criteria.make.lower().strip() not in make:
            return False

    # Color filter
    if criteria.color and not _color_matches(listing, criteria.color):
        return False

    # Model filter ("Civic", "CR-V", "Model 3")
    if criteria.model and not _model_matches(listing, criteria.model):
        return False

    # Budget filter - more flexible
    if criteria.budget is not None:
        price = listing.get("price")
        if price is None:
            return False
        # Allow slight over-budget (10%) for scoring to handle
        if price > criteria.budget * 1.15:
            return False

    # Body style filter - handle "not SUV" case
    if criteria.body_style:
        body_style = (listing.get("body_style") or "").lower()
        criteria_style = criteria.body_style.lower()
        
        # Handle negative filters like "not SUV"
        if criteria_style.startswith("not "):
            excluded_style = criteria_style[4:].strip()
            if excluded_style in body_style:
                return False
        else:
            # Positive filter - must contain the style
            if criteria_style not in body_style:
                return False

    # Fuel type filter
    if criteria.fuel_type and not _fuel_matches(listing, criteria.fuel_type):
        return False

    # Distance filter - more flexible
    if criteria.max_distance is not None:
        dist = listing.get("distance_miles")
        if dist is not None and dist > criteria.max_distance * 1.5:
            return False

    return True


def _diversify(scored: List[ListingWithScore], k: int) -> List[ListingWithScore]:
    """Pick the top k results, preferring different models over repeats of the same one.

    First pass takes the best listing for each distinct make and model, in score order.
    If there are fewer than k distinct models, the best remaining listings fill the gaps.
    """
    picked: List[ListingWithScore] = []
    seen_models = set()
    for item in scored:
        key = (str(item.listing.get("make", "")).lower(), str(item.listing.get("model", "")).lower())
        if key in seen_models:
            continue
        seen_models.add(key)
        picked.append(item)
        if len(picked) == k:
            return picked
    for item in scored:
        if item not in picked:
            picked.append(item)
            if len(picked) == k:
                break
    return picked


def search(criteria: SearchCriteria, top_k: int = 5) -> List[ListingWithScore]:
    """Fetch live listings from Auto.dev, filter them, and rank them by score.

    Raises ApiError if the live listings service can't be reached, so callers can tell
    "no matches" apart from "the service is down".
    """
    fetch_args: Dict[str, Any] = dict(
        budget=criteria.budget,
        min_year=2015,
        make=canonical_make(criteria.make),
        body_style=criteria.body_style,
        zip_code=criteria.zip_code,
        max_distance=criteria.max_distance,
        limit=100,
    )
    if criteria.fuel_type or criteria.model or criteria.color:
        # Hybrids, EVs and one specific model are a small slice of listings, so look through more pages.
        fetch_args["pages"] = FUEL_SEARCH_PAGES
    candidates = fetch_active_listings(**fetch_args)
    logger.debug("Fetched %d candidates from Auto.dev", len(candidates))

    # Deduplicate by ID/VIN
    seen = set()
    unique_candidates = []
    for item in candidates:
        key = str(item.get("id") or item.get("vin") or id(item))
        if key in seen:
            continue
        seen.add(key)
        unique_candidates.append(item)

    filtered = [c for c in unique_candidates if _passes_filters(c, criteria)]
    logger.debug("%d candidates passed filters", len(filtered))

    scored = [score_listing(item, criteria) for item in filtered]
    scored.sort(key=lambda s: s.total_score, reverse=True)
    return _diversify(scored, top_k)