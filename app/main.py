from dotenv import load_dotenv
load_dotenv()

from typing import Dict, Any, List, Optional, Tuple
import json
import re

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from app.external_apis import get_car_profile_from_vin, ApiError as ExternalApiError
from app.schemas import (
    CarProfile,
    SearchResponse,
    SearchCriteriaModel,
    SearchResult,
    ScoreBreakdownModel,
    SearchListing,
)
from app.llm_client import chat_completion, get_llm_info, LLMError
from app.llm_prompts import (
    build_car_advice_messages,
    build_filter_extraction_messages,
    build_recommendation_messages,
    SYSTEM_PROMPT,
)
from app.search import search as search_pipeline, SearchCriteria, canonical_make

import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="GenAI Car Assistant Backend")


# -------------------------------------------------------------------
# Health
# -------------------------------------------------------------------

@app.get("/health")
def health() -> Dict[str, str]:
    """
    Simple health check used by the Streamlit frontend.
    """
    return {"status": "ok", **get_llm_info()}


# -------------------------------------------------------------------
# VIN profile utilities
# -------------------------------------------------------------------

def summarize_profile_for_llm(profile: Dict[str, Any]) -> str:
    """
    Turn a normalized CarProfile like dict into a compact textual summary.

    This is meant for LLM prompts so the model does not have to guess specs.
    """
    year = profile.get("year")
    make = profile.get("make")
    model = profile.get("model")
    trim = profile.get("trim") or ""
    body_type = profile.get("type") or ""
    origin = profile.get("origin") or ""

    engine = profile.get("engine") or {}
    displacement = engine.get("displacement_l")
    cylinders = engine.get("cylinders")
    hp = engine.get("hp")
    fuel_type = engine.get("fuel_type") or "unknown fuel"

    econ = profile.get("economy") or {}
    city_mpg = econ.get("city_mpg")
    hwy_mpg = econ.get("highway_mpg")
    mixed_mpg = econ.get("mixed_mpg")

    parts: List[str] = []

    # Name
    if year and make and model:
        name = f"{year} {make} {model}"
    else:
        base = " ".join([p for p in [make, model] if p])
        name = base or "This vehicle"
    if trim:
        name += f" {trim}"
    if body_type:
        name += f" ({body_type})"
    if origin:
        parts.append(f"{name}, built in {origin}.")
    else:
        parts.append(f"{name}.")

    # Engine
    engine_bits: List[str] = []
    if displacement:
        engine_bits.append(f"{displacement:.1f}L")
    if cylinders:
        engine_bits.append(f"{cylinders} cylinder")
    if hp:
        engine_bits.append(f"{hp} horsepower")
    engine_desc = ", ".join(engine_bits) if engine_bits else "engine specs are partially unknown"
    parts.append(f"Engine: {engine_desc}, fuel: {fuel_type}.")

    # Economy
    if any(v is not None for v in (city_mpg, hwy_mpg, mixed_mpg)):
        eco_bits: List[str] = []
        if city_mpg:
            eco_bits.append(f"city about {city_mpg:.0f} miles per gallon")
        if hwy_mpg:
            eco_bits.append(f"highway about {hwy_mpg:.0f} miles per gallon")
        if mixed_mpg:
            eco_bits.append(f"mixed about {mixed_mpg:.0f} miles per gallon")
        eco_txt = ", ".join(eco_bits)
        parts.append(f"Approximate fuel economy: {eco_txt}.")
    else:
        parts.append("Fuel economy data is not available.")

    return " ".join(parts)


# -------------------------------------------------------------------
# VIN profile routes
# -------------------------------------------------------------------

@app.get("/cars/{vin}", response_model=CarProfile)
def get_car(vin: str) -> CarProfile:
    """
    Return a normalized car profile for the given VIN.
    """
    try:
        profile_dict = get_car_profile_from_vin(vin)
    except ExternalApiError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not profile_dict or not profile_dict.get("year"):
        raise HTTPException(status_code=404, detail="Could not decode VIN")

    return CarProfile(**profile_dict)


class CarSummaryResponse(BaseModel):
    vin: str
    summary: str


@app.get("/cars/{vin}/summary", response_model=CarSummaryResponse)
def get_car_summary(vin: str) -> CarSummaryResponse:
    """
    Get a short natural language summary of the car.
    """
    try:
        profile_dict = get_car_profile_from_vin(vin)
    except ExternalApiError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not profile_dict or not profile_dict.get("year"):
        raise HTTPException(status_code=404, detail="Could not decode VIN")

    summary = summarize_profile_for_llm(profile_dict)
    return CarSummaryResponse(vin=vin, summary=summary)


# -------------------------------------------------------------------
# Chat models
# -------------------------------------------------------------------

class ChatRequest(BaseModel):
    """
    Request body for the /chat endpoint.

    If vin is provided, the assistant talks about that specific car.
    If vin is empty or null, the assistant goes into general discovery mode.
    """
    question: str
    vin: Optional[str] = None
    history: List[Dict[str, str]] = Field(default_factory=list)
    zip_code: Optional[str] = Field(
        None, description="5-digit US ZIP code the shopper searches from (needed for 'near me')."
    )


class ChatResponse(BaseModel):
    """
    Unified response for both chat modes.

    mode:
      "vin"      when answering about a specific VIN
      "general"  when doing search and recommendations

    In VIN mode filters and listings will be empty.
    """
    mode: str
    question: str
    vin: Optional[str] = None
    summary: Optional[str] = None
    answer: str
    filters: Dict[str, Any] = {}
    listings: List[SearchListing] = []


# -------------------------------------------------------------------
# Helper to call LLM for filters and parse the JSON
# -------------------------------------------------------------------

def _parse_number_maybe(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        # strip out non numeric characters except dot and minus
        cleaned = "".join(ch for ch in value if ch.isdigit() or ch in {".", "-"})
        if not cleaned:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def extract_filters_from_question(question: str) -> Dict[str, Any]:
    """
    Use the LLM to turn a free form question into search filters.
    """
    messages = build_filter_extraction_messages(question)
    try:
        raw = chat_completion(messages, max_tokens=256, temperature=0.0)
    except LLMError:
        return {}

    # Try direct JSON first
    data: Any
    try:
        data = json.loads(raw)
    except Exception:
        # Try to pull out the first JSON object if the model added extra text
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return {}
        try:
            data = json.loads(raw[start : end + 1])
        except Exception:
            return {}

    if not isinstance(data, dict):
        return {}

    filters: Dict[str, Any] = {}

    budget = _parse_number_maybe(data.get("budget"))
    if budget is not None and budget > 0:
        filters["budget"] = budget

    max_distance = _parse_number_maybe(data.get("max_distance"))
    if max_distance is not None and max_distance > 0:
        filters["max_distance"] = max_distance

    body_style = data.get("body_style")
    if isinstance(body_style, str) and body_style.strip():
        filters["body_style"] = body_style.strip()

    fuel_type = data.get("fuel_type")
    if isinstance(fuel_type, str) and fuel_type.strip():
        filters["fuel_type"] = fuel_type.strip()

    make = data.get("make")
    if isinstance(make, str) and make.strip():
        filters["make"] = canonical_make(make.strip())

    model = data.get("model")
    if isinstance(model, str) and model.strip():
        filters["model"] = model.strip()

    color = data.get("color")
    if isinstance(color, str) and color.strip():
        filters["color"] = color.strip()

    return filters


def build_criteria_from_filters(filters: Dict[str, Any], zip_code: Optional[str] = None) -> SearchCriteria:
    """
    Map filter dict into a SearchCriteria dataclass.
    """
    return SearchCriteria(
        budget=_parse_number_maybe(filters.get("budget")),
        max_distance=_parse_number_maybe(filters.get("max_distance")),
        body_style=(filters.get("body_style") or None),
        fuel_type=(filters.get("fuel_type") or None),
        make=(filters.get("make") or None),
        model=(filters.get("model") or None),
        color=(filters.get("color") or None),
        zip_code=zip_code,
    )


def _clean_zip(value: Optional[str]) -> Optional[str]:
    """Return a valid 5-digit US ZIP, or None."""
    if not value:
        return None
    value = value.strip()
    return value if re.fullmatch(r"\d{5}", value) else None


_NEARBY_WORDS = re.compile(r"\b(near me|nearby|near by|close to me|around me|local(ly)?|in my area)\b", re.I)


def _no_results_message(filters: Dict[str, Any], zip_code: Optional[str]) -> str:
    """Deterministic reply when the live search finds nothing, so the LLM can't invent cars."""
    tips = []
    if filters.get("budget"):
        tips.append("raising your budget a little")
    if filters.get("max_distance") or zip_code:
        tips.append("widening the distance")
    if filters.get("body_style"):
        tips.append("trying a different body style")
    if filters.get("color"):
        tips.append("trying a different color or dropping the color")
    if filters.get("fuel_type"):
        tips.append("trying a different fuel type")
    if filters.get("model"):
        tips.append("trying a different model")
    elif filters.get("make"):
        tips.append("trying a different brand")
    tips.append("loosening other requirements")
    return (
        "I couldn't find any live listings that match that right now. "
        "You could try " + ", ".join(tips[:-1]) + (", or " if len(tips) > 1 else "") + tips[-1] + "."
    )


# -------------------------------------------------------------------
# Chat endpoint - SIMPLIFIED VERSION
# -------------------------------------------------------------------

@app.post("/chat", response_model=ChatResponse)
def chat_with_llm(payload: ChatRequest) -> ChatResponse:
    """
    LLM powered explanation endpoint - SIMPLIFIED.
    """
    question = payload.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="question must not be empty")

    vin = (payload.vin or "").strip()
    history = [
        {"role": h.get("role"), "content": h.get("content", "").strip()}
        for h in (payload.history or [])
        if h.get("role") in {"user", "assistant"} and isinstance(h.get("content"), str)
    ][-10:]

    def history_text(entries: List[Dict[str, str]]) -> str:
        if not entries:
            return ""
        lines = []
        for item in entries:
            prefix = "User" if item["role"] == "user" else "Assistant"
            lines.append(f"{prefix}: {item['content']}")
        return "\n".join(lines)

    conversation_snippet = history_text(history)

    # VIN specific mode
    if vin:
        try:
            profile_dict = get_car_profile_from_vin(vin)
        except ExternalApiError as e:
            raise HTTPException(status_code=502, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

        if not profile_dict or not profile_dict.get("year"):
            raise HTTPException(status_code=404, detail="Could not decode VIN")

        summary = summarize_profile_for_llm(profile_dict)
        rich_question = (
            question
            if not conversation_snippet
            else f"Conversation so far:\n{conversation_snippet}\n\nLatest customer question: {question}"
        )
        messages = build_car_advice_messages(user_question=rich_question, car_summary=summary)

        try:
            answer = chat_completion(messages)
        except LLMError as e:
            raise HTTPException(status_code=502, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

        return ChatResponse(
            mode="vin",
            question=question,
            vin=vin,
            summary=summary,
            answer=answer,
            filters={},
            listings=[],
        )

    # General discovery mode - SIMPLIFIED
    rich_query = (
        question
        if not conversation_snippet
        else f"Conversation so far:\n{conversation_snippet}\n\nLatest request: {question}"
    )

    filters = extract_filters_from_question(rich_query)
    zip_code = _clean_zip(payload.zip_code)

    # "Near me" and "within X miles" need a starting point
    if not zip_code and (filters.get("max_distance") or _NEARBY_WORDS.search(question)):
        return ChatResponse(
            mode="general",
            question=question,
            answer=(
                "I can look for cars near you, but I need to know where you are first. "
                "Enter your ZIP code in the box at the top of the page and ask again."
            ),
            filters=filters,
            listings=[],
        )

    criteria = build_criteria_from_filters(filters, zip_code)
    if zip_code:
        filters = {**filters, "zip_code": zip_code}

    # Run search (top 3, so the written advice and the cards always describe the same cars)
    try:
        results = search_pipeline(criteria, top_k=3)
    except ExternalApiError as e:
        logger.error("Live listings unavailable: %s", e)
        return ChatResponse(
            mode="general",
            question=question,
            answer=f"I couldn't reach the live listings service just now ({e}) Please try again in a moment.",
            filters=filters,
            listings=[],
        )
    except Exception as e:
        logger.error(f"Search failed: {e}", exc_info=True)
        return ChatResponse(
            mode="general",
            question=question,
            answer="Something went wrong while searching for vehicles. Please try again.",
            filters=filters,
            listings=[],
        )

    if not results:
        return ChatResponse(
            mode="general",
            question=question,
            answer=_no_results_message(filters, zip_code),
            filters=filters,
            listings=[],
        )

    listing_models: List[SearchListing] = []
    listing_dicts: List[Dict[str, Any]] = []
    for r in results:
        try:
            model = SearchListing(**r.listing)
        except Exception as e:  # one odd listing should not break the whole answer
            logger.warning("Skipping a listing that did not validate: %s", e)
            continue
        model.match_score = round(r.total_score * 100)
        listing_models.append(model)
        listing_dicts.append({**model.dict(), "color": r.listing.get("color")})  # color is for the LLM text only

    # Use the existing build_recommendation_messages function
    messages = build_recommendation_messages(
        user_query=rich_query,
        filters=filters,
        listings=listing_dicts,
    )

    try:
        answer = chat_completion(messages)
    except LLMError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return ChatResponse(
        mode="general",
        question=question,
        vin=None,
        summary=None,
        answer=answer,
        filters=filters,
        listings=listing_models,
    )


# -------------------------------------------------------------------
# Structured search endpoint (JSON body)
# -------------------------------------------------------------------

@app.post("/search", response_model=SearchResponse)
def search_inventory(payload: SearchCriteriaModel) -> SearchResponse:
    """
    Deterministic search over live inventory.

    Returns scored listings with transparent breakdowns.
    """
    logger.debug(f"Search criteria received: {payload.dict()}")
    
    criteria = SearchCriteria(
        budget=payload.budget,
        max_distance=payload.max_distance,
        body_style=payload.body_style,
        fuel_type=payload.fuel_type,
        zip_code=_clean_zip(payload.zip_code),
    )
    
    try:
        results = search_pipeline(criteria)
        logger.debug(f"Search returned {len(results)} results")
        
        if results:
            for i, r in enumerate(results[:3]):
                logger.debug(f"Result {i}: {r.listing.get('make')} {r.listing.get('model')} - Score: {r.total_score:.2f}")
        
    except ExternalApiError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        logger.error(f"Search failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")
    
    serialized_results: List[SearchResult] = []
    for r in results:
        listing_model = SearchListing(**r.listing)
        score_model = ScoreBreakdownModel(
            price=r.breakdown.price,
            mileage=r.breakdown.mileage,
            distance=r.breakdown.distance,
            economy=r.breakdown.economy,
            safety=r.breakdown.safety,
            total=r.total_score,
        )
        serialized_results.append(SearchResult(listing=listing_model, score=score_model))

    criteria_applied = {
        "budget": payload.budget,
        "max_distance": payload.max_distance,
        "body_style": payload.body_style,
        "fuel_type": payload.fuel_type,
    }
    return SearchResponse(results=serialized_results, criteria_applied=criteria_applied)


# -------------------------------------------------------------------
# Legacy recommendations endpoints used by try_recommendations
# -------------------------------------------------------------------

def _build_recommendations_from_params(
    price_max: Optional[float],
    mpg_min: Optional[float],
    fuel: Optional[str],
    top_k: int,
) -> List[Dict[str, Any]]:
    # For now we ignore mpg_min in the filter and let the scoring handle economy.
    criteria = SearchCriteria(
        budget=price_max,
        max_distance=None,
        body_style=None,
        fuel_type=fuel,
    )
    results = search_pipeline(criteria, top_k=top_k)
    recos: List[Dict[str, Any]] = []
    for r in results:
        item = dict(r.listing)
        item["score"] = r.total_score
        item["rationale"] = (
            "Score combines price, mileage, distance, economy, and safety. "
            "Higher score means a better overall match for the filters."
        )
        recos.append(item)
    return recos


@app.get("/cars/recommendations")
def cars_recommendations(
    price_max: float = Query(..., gt=0),
    mpg_min: float = Query(0, ge=0),
    fuel: Optional[str] = Query(None),
    top_k: int = Query(5, ge=1, le=20),
) -> List[Dict[str, Any]]:
    """
    Recommendation endpoint that matches the older frontend helper.

    It returns a list of plain dicts, one per listing.
    """
    return _build_recommendations_from_params(price_max, mpg_min, fuel, top_k)


@app.get("/recommendations")
def recommendations(
    price_max: float = Query(..., gt=0),
    mpg_min: float = Query(0, ge=0),
    fuel: Optional[str] = Query(None),
    top_k: int = Query(5, ge=1, le=20),
) -> List[Dict[str, Any]]:
    """
    Alias for /cars/recommendations so the frontend can try both paths.
    """
    return _build_recommendations_from_params(price_max, mpg_min, fuel, top_k)
