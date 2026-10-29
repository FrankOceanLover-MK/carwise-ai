"""Unit tests for the deterministic scoring and filtering logic (no network or API keys needed)."""
import pytest

from app import search as search_module
from app.search import (
    ScoreBreakdown,
    SearchCriteria,
    _distance_score,
    _economy_score,
    _mileage_score,
    _passes_filters,
    _price_score,
    _safety_score,
    score_listing,
)


def test_weights_sum_to_one():
    perfect = ScoreBreakdown(price=1, mileage=1, distance=1, economy=1, safety=1)
    assert perfect.total == pytest.approx(1.0)


def test_total_uses_documented_weights():
    bd = ScoreBreakdown(price=1, mileage=0, distance=0, economy=0, safety=0)
    assert bd.total == pytest.approx(0.30)
    bd = ScoreBreakdown(price=0, mileage=1, distance=0, economy=0, safety=0)
    assert bd.total == pytest.approx(0.25)


@pytest.mark.parametrize(
    "fn,args",
    [
        (_price_score, (None, 20000)),
        (_mileage_score, (None,)),
        (_distance_score, (None, 50)),
        (_economy_score, (None, None)),
        (_safety_score, (None,)),
    ],
)
def test_missing_data_gets_neutral_score(fn, args):
    assert fn(*args) == 0.5


def test_price_within_budget_scores_full_and_far_over_scores_low():
    assert _price_score(18000, 20000) == 1.0
    assert _price_score(30000, 20000) == 0.05


def test_mileage_decreases_as_mileage_rises():
    assert _mileage_score(20000) > _mileage_score(60000) > _mileage_score(100000)


def test_economy_is_bounded():
    assert _economy_score(10, 12) == 0.2
    assert _economy_score(40, 45) == 1.0


def test_safety_scales_with_stars():
    assert _safety_score(5) == 1.0
    assert _safety_score(2.5) == 0.5


def test_budget_filter_allows_small_overage_only():
    criteria = SearchCriteria(budget=20000)
    assert _passes_filters({"price": 22000}, criteria)
    assert not _passes_filters({"price": 25000}, criteria)
    assert not _passes_filters({"price": None}, criteria)


def test_negative_body_style_filter():
    criteria = SearchCriteria(body_style="not SUV")
    assert _passes_filters({"body_style": "Sedan"}, criteria)
    assert not _passes_filters({"body_style": "SUV"}, criteria)


def test_search_ranks_best_match_first(monkeypatch):
    live = [
        {"id": "a", "make": "Toyota", "price": 19000, "mileage": 20000, "distance_miles": 10,
         "city_mpg": 30, "highway_mpg": 38, "safety_rating": 5, "body_style": "Sedan"},
        {"id": "b", "make": "Toyota", "price": 19500, "mileage": 110000, "distance_miles": 70,
         "city_mpg": 15, "highway_mpg": 20, "safety_rating": 3, "body_style": "Sedan"},
    ]
    monkeypatch.setattr(search_module, "fetch_active_listings", lambda **kw: live)
    results = search_module.search(SearchCriteria(budget=20000, max_distance=50), top_k=2)
    assert [r.listing["id"] for r in results] == ["a", "b"]
    assert results[0].total_score > results[1].total_score


def test_search_deduplicates_by_id(monkeypatch):
    dup = {"id": "x", "price": 10000, "mileage": 10000}
    monkeypatch.setattr(search_module, "fetch_active_listings", lambda **kw: [dup, dup])
    assert len(search_module.search(SearchCriteria(budget=20000))) == 1


def test_score_listing_handles_empty_listing():
    result = score_listing({}, SearchCriteria())
    assert 0.0 <= result.total_score <= 1.0


# --- variety of results -------------------------------------------------------------------------

def _car(i, model, price):
    return {"id": f"{model}-{i}", "make": "Toyota", "model": model, "price": price, "mileage": 5000,
            "distance_miles": 10, "city_mpg": 25, "highway_mpg": 32, "safety_rating": 5}


def test_results_prefer_different_models(monkeypatch):
    live = [_car(1, "GR86", 30000), _car(2, "GR86", 30100), _car(3, "GR86", 30200),
            _car(4, "Supra", 38000), _car(5, "86", 36000)]
    monkeypatch.setattr(search_module, "fetch_active_listings", lambda **kw: live)
    results = search_module.search(SearchCriteria(budget=40000), top_k=3)
    assert {r.listing["model"] for r in results} == {"GR86", "Supra", "86"}


def test_repeats_fill_in_when_few_models_exist(monkeypatch):
    live = [_car(i, "GR86", 30000 + i) for i in range(4)] + [_car(9, "Supra", 38000)]
    monkeypatch.setattr(search_module, "fetch_active_listings", lambda **kw: live)
    results = search_module.search(SearchCriteria(budget=40000), top_k=3)
    assert len(results) == 3
    assert {r.listing["model"] for r in results} == {"GR86", "Supra"}
