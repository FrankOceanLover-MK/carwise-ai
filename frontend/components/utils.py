import os
import requests
from typing import Optional, Dict, Any, Tuple, List

DEFAULT_BASE = os.getenv("BACKEND_BASE_URL", "http://127.0.0.1:8000")
TIMEOUT = float(os.getenv("HTTP_TIMEOUT_SECONDS", "60"))


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message
        super().__init__(f"{status}: {message}")


def _handle_response(resp: requests.Response) -> Any:
    if 200 <= resp.status_code < 300:
        try:
            if resp.headers.get("content-type", "").startswith("application/json"):
                return resp.json()
            return resp.text
        except Exception:
            return resp.text

    try:
        data = resp.json()
    except Exception:
        data = {"detail": resp.text}

    message = data.get("detail") or data.get("error") or resp.text
    raise ApiError(resp.status_code, str(message))


def health(base: str = DEFAULT_BASE) -> Dict[str, Any]:
    r = requests.get(f"{base}/health", timeout=TIMEOUT)
    return _handle_response(r)


def get_car(vin: str, base: str = DEFAULT_BASE) -> Dict[str, Any]:
    r = requests.get(f"{base}/cars/{vin}", timeout=TIMEOUT)
    data = _handle_response(r)
    if not isinstance(data, dict):
        raise ApiError(500, "Unexpected response format from /cars/{vin}")
    return data


def get_summary(vin: str, base: str = DEFAULT_BASE) -> str:
    r = requests.get(f"{base}/cars/{vin}/summary", timeout=TIMEOUT)
    data = _handle_response(r)
    if isinstance(data, dict) and "summary" in data:
        return str(data["summary"])
    if isinstance(data, str):
        return data
    raise ApiError(500, "Unexpected response format from /cars/{vin}/summary")


def try_recommendations(
    params: Dict[str, Any],
    base: str = DEFAULT_BASE,
) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Call the backend search endpoint and flatten the response into a list that
    charts.table can render easily.
    """
    payload: Dict[str, Any] = {
        "budget": params.get("budget"),
        "max_distance": params.get("max_distance"),
        "body_style": params.get("body_style"),
        "fuel_type": params.get("fuel_type"),
        "top_k": params.get("top_k", 5),
    }

    r = requests.post(f"{base}/search", json=payload, timeout=TIMEOUT)
    data = _handle_response(r)
    path = "/search"

    if not isinstance(data, dict):
        raise ApiError(500, "Unexpected response format from /search")

    results = data.get("results") or []
    flattened: List[Dict[str, Any]] = []
    for item in results:
        listing = item.get("listing") or {}
        score = item.get("score") or {}

        flat: Dict[str, Any] = {
            "year": listing.get("year"),
            "make": listing.get("make"),
            "model": listing.get("model"),
            "trim": listing.get("trim"),
            "price": listing.get("price"),
            "mileage": listing.get("mileage"),
            "distance_miles": listing.get("distance_miles"),
            "city_mpg": listing.get("city_mpg"),
            "highway_mpg": listing.get("highway_mpg"),
            "safety_rating": listing.get("safety_rating"),
            "score": score.get("total"),
        }

        breakdown = {
            "price": score.get("price"),
            "mileage": score.get("mileage"),
            "distance": score.get("distance"),
            "economy": score.get("economy"),
            "safety": score.get("safety"),
        }
        flat["score_breakdown"] = breakdown

        rationale_bits = []
        for key, label in [
            ("price", "price"),
            ("mileage", "mileage"),
            ("distance", "distance"),
            ("economy", "economy"),
            ("safety", "safety"),
        ]:
            val = breakdown.get(key)
            if isinstance(val, (int, float)):
                rationale_bits.append(f"{label} match {round(val * 100)} percent")
        flat["rationale"] = ", ".join(rationale_bits) if rationale_bits else None

        flattened.append(flat)

    return path, flattened


def openapi_has_recommendations(base: str = DEFAULT_BASE) -> bool:
    """
    For this app we treat /search as the recommendations endpoint.
    """
    try:
        r = requests.get(f"{base}/openapi.json", timeout=TIMEOUT)
        spec = r.json()
        paths = spec.get("paths", {})
        return "/search" in paths
    except Exception:
        return False


def ask_chat(
    question: str,
    vin: Optional[str] = None,
    base: str = DEFAULT_BASE,
    history: Optional[List[Dict[str, str]]] = None,
    zip_code: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Call the /chat endpoint. If vin is provided the backend will
    explain that specific car. Otherwise it will run discovery mode.
    """
    payload: Dict[str, Any] = {"question": question}
    if vin:
        payload["vin"] = vin
    if zip_code:
        payload["zip_code"] = zip_code
    if history:
        # Only send the last few turns and keep role/content pairs
        payload["history"] = [
            {"role": item.get("role"), "content": item.get("content")}
            for item in history
            if item.get("role") in {"user", "assistant"} and item.get("content")
        ][-10:]

    r = requests.post(f"{base}/chat", json=payload, timeout=TIMEOUT)
    data = _handle_response(r)
    if not isinstance(data, dict):
        raise ApiError(500, "Unexpected response from /chat")
    return data
