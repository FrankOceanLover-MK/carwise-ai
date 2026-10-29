# schemas.py
from typing import Optional, List, Dict, Any

from pydantic import BaseModel, Field


class EngineSummary(BaseModel):
    displacement_l: Optional[float] = None
    cylinders: Optional[int] = None
    hp: Optional[int] = None
    fuel_type: Optional[str] = None


class EconomySummary(BaseModel):
    city_mpg: Optional[float] = None
    highway_mpg: Optional[float] = None
    mpge: Optional[float] = None


class SafetySummary(BaseModel):
    nhtsa_stars: Optional[float] = None
    notes: Optional[str] = None


class CarProfile(BaseModel):
    vin: str
    year: Optional[int] = None
    make: Optional[str] = None
    model: Optional[str] = None
    trim: Optional[str] = None

    body_style: Optional[str] = None
    mileage: Optional[int] = None
    price: Optional[float] = None

    fuel_type: Optional[str] = None
    drivetrain: Optional[str] = None
    origin: Optional[str] = None

    engine: Optional[EngineSummary] = None
    economy: Optional[EconomySummary] = None
    safety: Optional[SafetySummary] = None

    # Keep any extra backend fields
    extra: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        extra = "allow"


class ScoreBreakdownModel(BaseModel):
    price: float
    mileage: float
    distance: float
    economy: float
    safety: float
    total: float


class SearchCriteriaModel(BaseModel):
    budget: Optional[int] = Field(
        None,
        description="Maximum budget in US dollars.",
    )
    max_distance: Optional[float] = Field(
        None,
        description="Maximum distance in miles for listings.",
    )
    body_style: Optional[str] = Field(
        None,
        description="Desired body style such as suv, sedan, truck.",
    )
    fuel_type: Optional[str] = Field(
        None,
        description="Desired fuel type such as gasoline, hybrid, electric.",
    )
    zip_code: Optional[str] = Field(
        None,
        description="5-digit US ZIP code to search around (used with max_distance).",
    )
    top_k: Optional[int] = Field(
        5,
        description="Maximum number of results to return.",
    )


class SearchListing(BaseModel):
    id: Optional[str] = None
    year: Optional[int] = None
    make: Optional[str] = None
    model: Optional[str] = None
    trim: Optional[str] = None
    price: Optional[float] = None
    mileage: Optional[float] = None
    distance_miles: Optional[float] = None
    fuel_type: Optional[str] = None
    body_style: Optional[str] = None
    city_mpg: Optional[float] = None
    highway_mpg: Optional[float] = None
    safety_rating: Optional[float] = None
    source: Optional[str] = None

    # new fields
    vin: Optional[str] = None
    listing_url: Optional[str] = None
    image_url: Optional[str] = None
    dealer: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    match_score: Optional[int] = None  # 0-100, from the weighted scoring model



class SearchResult(BaseModel):
    listing: SearchListing
    score: ScoreBreakdownModel


class SearchResponse(BaseModel):
    results: List[SearchResult]
    criteria_applied: Dict[str, Any]
