import datetime
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

AUTO_DEV_API_KEY = os.getenv("AUTO_DEV_API_KEY")


class ApiError(RuntimeError):
    pass


# -------------------------------------------------------------------
# Simple in-memory TTL cache (24 hours)
# -------------------------------------------------------------------

_CACHE: Dict[str, Tuple[float, Any]] = {}
CACHE_TTL = 60 * 60 * 24  # 24 hours


def cache_get(key: str):
    now = time.time()
    item = _CACHE.get(key)
    if not item:
        return None
    ts, value = item
    if now - ts > CACHE_TTL:
        _CACHE.pop(key, None)
        return None
    return value


def cache_set(key: str, value: Any):
    _CACHE[key] = (time.time(), value)


# -------------------------------------------------------------------
# 1) AUTO.DEV – VIN decode
# -------------------------------------------------------------------

def auto_dev_vin_decode(vin: str) -> Dict[str, Any]:
    """
    Call Auto.dev VIN Decode API and return JSON.
    """
    if not AUTO_DEV_API_KEY:
        raise ApiError("AUTO_DEV_API_KEY is not set")

    cache_key = f"auto_dev_vin:{vin}"
    cached = cache_get(cache_key)
    if cached is not None:
        return cached

    url = f"https://api.auto.dev/vin/{vin}"
    headers = {
        "Authorization": f"Bearer {AUTO_DEV_API_KEY}",
        "Content-Type": "application/json",
    }
    
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        
        # Validate response has required fields
        if not data or not isinstance(data, dict):
            raise ApiError(f"Invalid response from Auto.dev for VIN {vin}")
        
        cache_set(cache_key, data)
        return data
    except requests.exceptions.RequestException as e:
        raise ApiError(f"Auto.dev API error: {str(e)}")


# -------------------------------------------------------------------
# 2) NHTSA vPIC – decode VIN
# -------------------------------------------------------------------

def nhtsa_decode_vin(vin: str, model_year: int | None = None) -> Dict[str, Any]:
    """
    Use NHTSA vPIC DecodeVinValues endpoint.
    """
    cache_key = f"nhtsa_vin:{vin}:{model_year or ''}"
    cached = cache_get(cache_key)
    if cached is not None:
        return cached

    base = "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues"
    params: Dict[str, Any] = {"format": "json"}
    if model_year:
        params["modelyear"] = model_year

    url = f"{base}/{vin}"
    
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        results = data.get("Results") or []
        flat = results[0] if results else {}

        cache_set(cache_key, flat)
        return flat
    except requests.exceptions.RequestException as e:
        logger.warning(f"NHTSA API warning: {e}")
        return {}


# -------------------------------------------------------------------
# 3) CarQuery – basic make/model/year trims
# -------------------------------------------------------------------

def carquery_get_trims(make: str, model: str, year: int) -> List[Dict[str, Any]]:
    """
    Call CarQuery getTrims to get trims/specs by year/make/model.
    """
    cache_key = f"carquery_trims:{year}:{make}:{model}"
    cached = cache_get(cache_key)
    if cached is not None:
        return cached

    url = "https://www.carqueryapi.com/api/0.3/"
    params = {
        "cmd": "getTrims",
        "make": make,
        "model": model,
        "year": year,
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; CarWiseBackend/0.1; +https://example.com)"
    }

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=10)

        if resp.status_code == 403:
            logger.warning("CarQuery returned 403 Forbidden; skipping trims.")
            cache_set(cache_key, [])
            return []

        resp.raise_for_status()
        data = resp.json()
        trims = data.get("Trims", []) or []
        cache_set(cache_key, trims)
        return trims
    except requests.exceptions.RequestException as e:
        logger.warning(f"CarQuery error: {e}")
        cache_set(cache_key, [])
        return []


# -------------------------------------------------------------------
# 4) Fuel economy helpers
# -------------------------------------------------------------------

def _parse_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_int(value: Any) -> Optional[int]:
    if not value:
        return None
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None


def l_per_100km_to_mpg(l_per_100km: Optional[float]) -> Optional[float]:
    """Convert liters/100km to miles per gallon."""
    if not l_per_100km or l_per_100km <= 0:
        return None
    return round(235.214 / l_per_100km, 1)


def get_economy_from_carquery(year: int, make: str, model: str) -> Dict[str, Any]:
    """
    Use CarQuery trims as the source of fuel economy data.
    """
    trims = carquery_get_trims(make=make, model=model, year=year)
    if not trims:
        return {}

    t = trims[0]

    city_l = _parse_float(t.get("model_lkm_city"))
    hwy_l = _parse_float(t.get("model_lkm_hwy"))
    mixed_l = _parse_float(t.get("model_lkm_mixed"))

    economy: Dict[str, Any] = {
        "fuel_type": t.get("model_engine_fuel"),
        "city_l_per_100km": city_l,
        "highway_l_per_100km": hwy_l,
        "mixed_l_per_100km": mixed_l,
        "city_mpg": l_per_100km_to_mpg(city_l),
        "highway_mpg": l_per_100km_to_mpg(hwy_l),
        "mixed_mpg": l_per_100km_to_mpg(mixed_l),
        "source": "carquery",
        "trim_used": t.get("model_trim"),
    }

    return economy


# -------------------------------------------------------------------
# 5) NHTSA 5-Star Safety Ratings (FIXED)
# -------------------------------------------------------------------

def get_safety_rating(year: int, make: str, model: str) -> Optional[int]:
    """
    Query NHTSA 5-Star Safety Ratings with proper URL encoding.
    """
    cache_key = f"nhtsa_safety:{year}:{make}:{model}"
    cached = cache_get(cache_key)
    if cached is not None:
        return cached

    if not year or not make or not model:
        return None

    try:
        # FIXED: Properly encode make and model for URLs
        # This handles spaces and special characters correctly
        make_encoded = urllib.parse.quote(str(make).strip())
        model_encoded = urllib.parse.quote(str(model).strip())
        
        base_url = "https://api.nhtsa.gov/SafetyRatings"
        query_url = f"{base_url}/modelyear/{year}/make/{make_encoded}/model/{model_encoded}"
        
        resp = requests.get(query_url, timeout=10)
        
        if resp.status_code != 200:
            cache_set(cache_key, None)
            return None
            
        data = resp.json()
        results = data.get("Results", [])
        
        if not results:
            cache_set(cache_key, None)
            return None
            
        vehicle_id = results[0].get("VehicleId")
        if not vehicle_id:
            cache_set(cache_key, None)
            return None

        # Get rating for that vehicle
        rating_url = f"{base_url}/VehicleId/{vehicle_id}"
        resp_rating = requests.get(rating_url, timeout=10)
        
        if resp_rating.status_code != 200:
            cache_set(cache_key, None)
            return None
            
        rating_data = resp_rating.json()
        rating_results = rating_data.get("Results", [])
        
        if not rating_results:
            cache_set(cache_key, None)
            return None
            
        overall_str = rating_results[0].get("OverallRating", "")
        
        try:
            rating = int(overall_str) if overall_str else None
        except ValueError:
            rating = None
            
        cache_set(cache_key, rating)
        return rating

    except Exception as e:
        logger.warning(f"NHTSA Safety API Error for {year} {make} {model}: {e}")
        cache_set(cache_key, None)
        return None


# -------------------------------------------------------------------
# 6) High-level profile helper
# -------------------------------------------------------------------

def get_car_profile_from_vin(vin: str) -> Dict[str, Any]:
    """
    Combine Auto.dev, NHTSA, and CarQuery data into one normalized profile.
    """
    # Decode VIN with Auto.dev
    auto_data = auto_dev_vin_decode(vin)

    # Decode VIN with NHTSA
    nhtsa_data = nhtsa_decode_vin(vin)

    # Extract core identity
    vehicle = auto_data.get("vehicle", {}) or {}

    year = vehicle.get("year")
    if year is None:
        model_year_str = nhtsa_data.get("ModelYear")
        year = int(model_year_str) if model_year_str else None

    make = vehicle.get("make") or auto_data.get("make") or nhtsa_data.get("Make")
    model = vehicle.get("model") or auto_data.get("model") or nhtsa_data.get("Model")
    trim = auto_data.get("trim") or nhtsa_data.get("Trim")

    # Get fuel economy data
    economy = {}
    if year and make and model:
        try:
            economy = get_economy_from_carquery(year=year, make=make, model=model)
        except Exception as e:
            logger.warning(f"CarQuery economy lookup failed: {e}")

    # Get safety rating
    safety_stars = None
    if year and make and model:
        try:
            safety_stars = get_safety_rating(year, make, model)
        except Exception as e:
            logger.warning(f"Safety rating lookup failed: {e}")

    # Build profile
    profile: Dict[str, Any] = {
        "vin": vin,
        "year": year,
        "make": make,
        "model": model,
        "trim": trim,
        "type": auto_data.get("type"),
        "origin": auto_data.get("origin"),

        "engine": {
            "displacement_l": _parse_float(nhtsa_data.get("DisplacementL")),
            "cylinders": _parse_int(nhtsa_data.get("EngineCylinders")),
            "hp": _parse_int(nhtsa_data.get("EngineHP")),
            "fuel_type": economy.get("fuel_type") or nhtsa_data.get("FuelTypePrimary"),
        },

        "economy": {
            "city_mpg": economy.get("city_mpg"),
            "highway_mpg": economy.get("highway_mpg"),
            "mixed_mpg": economy.get("mixed_mpg"),
            "source": economy.get("source"),
        },

        "safety": {
            "nhtsa_stars": safety_stars,
            "source": "nhtsa" if safety_stars else None
        }
    }

    return profile


# -------------------------------------------------------------------
# 7) Auto.dev Listings Search (Enhanced with better error handling)
# -------------------------------------------------------------------

def _http_url(value: Any) -> Optional[str]:
    """Return value as an https URL if it looks like a web URL, else None."""
    if isinstance(value, str) and value.startswith(("http://", "https://")):
        return "https://" + value[len("http://"):] if value.startswith("http://") else value
    return None


def _first_image_url(item: Dict[str, Any], retail: Dict[str, Any]) -> Optional[str]:
    """Find the best photo URL in an Auto.dev listing (field names vary by plan/version)."""
    candidates: List[Any] = []
    for src in (retail, item):
        for key in ("primaryImage", "primaryPhoto", "primaryPhotoUrl", "image", "imageUrl"):
            candidates.append(src.get(key))
        for key in ("photoUrls", "photos", "images"):
            photos = src.get(key)
            if isinstance(photos, list) and photos:
                first = photos[0]
                candidates.append(first.get("url") if isinstance(first, dict) else first)
    for c in candidates:
        url = _http_url(c)
        if url:
            return url
    return None


def _as_text(value: Any) -> Optional[str]:
    """Return value as a clean string, or None when it is missing."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _color_text(value: Any) -> Optional[str]:
    """Auto.dev's color field may be a plain string or a small object; return readable text or None."""
    if isinstance(value, dict):
        value = value.get("name") or value.get("value") or value.get("generic") or value.get("simple")
    if isinstance(value, str) and value.strip() and value.strip().lower() not in {"unknown", "n/a", "none"}:
        return value.strip()
    return None


def _map_auto_dev_listing_to_schema(item: Dict[str, Any]) -> Dict[str, Any]:
    """Map Auto.dev listing format to our internal schema."""
    vehicle = item.get("vehicle", {}) or {}
    retail = item.get("retailListing", {}) or {}

    price = retail.get("price")
    mileage = retail.get("miles")
    distance = item.get("distance")

    vin = vehicle.get("vin") or item.get("vin")

    # Only link to a real dealer/listing page. Never invent a URL that may be dead.
    listing_url = None
    for candidate in (
        retail.get("vdp"),
        item.get("vdp_url"),
        item.get("vdpUrl"),
        retail.get("url"),
        item.get("url"),
    ):
        listing_url = _http_url(candidate)
        if listing_url:
            break

    # Auto.dev sometimes puts the brand inside the model ("Mazda CX-30"), which shows as "Mazda Mazda CX-30".
    # Auto.dev can return numbers where we expect text (the Ram "1500" comes back as the integer 1500).
    make_name = _as_text(vehicle.get("make"))
    model_name = _as_text(vehicle.get("model"))
    if make_name and isinstance(model_name, str):
        prefix = str(make_name).strip() + " "
        if model_name.lower().startswith(prefix.lower()) and len(model_name) > len(prefix):
            model_name = model_name[len(prefix):].strip()

    return {
        "id": item.get("id") or str(vin) or f"listing_{id(item)}",
        "year": vehicle.get("year"),
        "make": make_name,
        "model": model_name,
        "trim": _as_text(item.get("trim") or vehicle.get("trim")),
        "price": price,
        "mileage": mileage,
        "distance_miles": distance,
        "fuel_type": _as_text(vehicle.get("fuel")),
        "body_style": _as_text(vehicle.get("bodyStyle")),
        "color": _color_text(vehicle.get("exteriorColor")),
        "interior_color": _color_text(vehicle.get("interiorColor")),
        "city_mpg": vehicle.get("cityMpg"),
        "highway_mpg": vehicle.get("highwayMpg"),
        "safety_rating": None,  # Can be enriched later
        "source": "auto.dev",
        "vin": vin,
        "listing_url": listing_url,
        "image_url": _first_image_url(item, retail),
        "dealer": retail.get("dealer"),
        "city": retail.get("city"),
        "state": retail.get("state"),
    }


def fetch_active_listings(
    budget: Optional[float] = None,
    min_year: Optional[int] = None,
    make: Optional[str] = None,
    body_style: Optional[str] = None,
    zip_code: Optional[str] = None,
    max_distance: Optional[float] = None,
    limit: int = 15,
    pages: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Call Auto.dev GET /listings and return normalized live listings.

    Returns an empty list when nothing matches. Raises ApiError when the service
    can't be reached or returns an error, so "no results" and "service down" differ.
    """
    if not AUTO_DEV_API_KEY:
        raise ApiError("AUTO_DEV_API_KEY is not set. Add it to your .env file.")
    if pages is None:
        pages = int(os.getenv("AUTO_DEV_PAGES", "3"))

    url = "https://api.auto.dev/listings"
    params: Dict[str, Any] = {"apikey": AUTO_DEV_API_KEY, "limit": limit}

    # Filters from the Auto.dev listings docs
    if budget:
        params["retailListing.price"] = f"1-{int(budget)}"
    if min_year:
        params["vehicle.year"] = f"{min_year}-{datetime.date.today().year + 1}"
    if make:
        params["vehicle.make"] = make
    if body_style:
        params["vehicle.bodyStyle"] = body_style
    if zip_code:
        params["zip"] = zip_code
        params["distance"] = int(max_distance or 50)  # Auto.dev defaults to 50 miles

    headers = {"Authorization": f"Bearer {AUTO_DEV_API_KEY}", "Content-Type": "application/json"}

    # One page is small on the free plan (20 listings), and the newest listings often repeat the same
    # model, so read a few pages to give the ranking (and the variety picker) more to work with.
    def fetch_page(page: int) -> List[Dict[str, Any]]:
        """Return one page of raw listings. Raises ApiError on any failure."""
        try:
            resp = requests.get(url, params={**params, "page": page}, headers=headers, timeout=30)
        except requests.exceptions.Timeout as e:
            logger.warning("Auto.dev listings request timed out (page %d)", page)
            raise ApiError("The listings service timed out.") from e
        except requests.RequestException as e:
            logger.warning("Failed to reach Auto.dev: %s", e)
            raise ApiError("Could not reach the listings service.") from e
        if resp.status_code != 200:
            logger.warning("Auto.dev listings error %s: %s", resp.status_code, resp.text[:300])
            raise ApiError(f"The listings service returned an error ({resp.status_code}).")
        try:
            return resp.json().get("data", []) or []
        except ValueError as e:
            raise ApiError("The listings service returned an unreadable response.") from e

    # Page 1 decides whether the service is up (errors here are shown to the shopper).
    raw_listings: List[Dict[str, Any]] = list(fetch_page(1))

    # Pages 2+ are fetched at the same time, so six pages take about as long as one or two.
    # A page that fails is skipped; the pages that did load are still used.
    extra_pages = list(range(2, max(1, pages) + 1))
    if raw_listings and extra_pages:
        with ThreadPoolExecutor(max_workers=min(5, len(extra_pages))) as pool:
            futures = [pool.submit(fetch_page, p) for p in extra_pages]
            for fut in futures:  # in page order, so the newest listings stay first
                try:
                    raw_listings.extend(fut.result())
                except ApiError:
                    continue

    clean_listings: List[Dict[str, Any]] = []
    for raw in raw_listings:
        try:
            clean = _map_auto_dev_listing_to_schema(raw)
        except Exception as e:  # skip a malformed row rather than failing the whole search
            logger.warning("Error mapping listing: %s", e)
            continue
        if clean.get("year") and clean.get("make") and clean.get("model"):
            clean_listings.append(clean)

    logger.info("Auto.dev returned %d usable listings", len(clean_listings))
    return clean_listings
