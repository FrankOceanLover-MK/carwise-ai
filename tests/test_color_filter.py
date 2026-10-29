import pytest

from app import search as s
from app.external_apis import _color_text, _map_auto_dev_listing_to_schema
from app.search import SearchCriteria, _color_matches


def car(color, make="Honda", model="Civic"):
    return {"id": f"{make}{model}{color}", "make": make, "model": model, "year": 2023, "price": 20000, "color": color}


@pytest.mark.parametrize("wanted,paint,ok", [
    ("black", "Black", True),
    ("black", "Midnight Black Metallic", True),
    ("black", "Onyx", True),
    ("black", "Crystal Black Pearl", True),   # "pearl" is white-ish but the word black is there too
    ("white", "Platinum White Pearl", True),
    ("white", "Black", False),
    ("gray", "Magnetic Gray Metallic", True),
    ("grey", "Charcoal", True),
    ("silver", "Lunar Silver Metallic", True),
    ("red", "Soul Red Crystal", True),
    ("red", "Burgundy", True),
    ("blue", "Deep Sapphire Blue", True),
    ("blue", "Black", False),
    ("pink", "Black", False),
    ("pink", "Rose Pink", True),
])
def test_color_families(wanted, paint, ok):
    assert _color_matches(car(paint), wanted) is ok


def test_unknown_color_is_excluded_when_a_color_is_requested():
    assert not _color_matches(car(None), "black")


def test_search_filters_by_color_and_fetches_extra_pages(monkeypatch):
    calls = []

    def fake(**kw):
        calls.append(kw)
        return [car("Jet Black"), car("White"), car("Red"), car(None)]

    monkeypatch.setattr(s, "fetch_active_listings", fake)
    out = s.search(SearchCriteria(color="black"), top_k=3)
    assert [r.listing["color"] for r in out] == ["Jet Black"]
    assert calls[-1]["pages"] == s.FUEL_SEARCH_PAGES


def test_color_text_accepts_strings_and_objects():
    assert _color_text("Black") == "Black"
    assert _color_text({"name": "Deep Blue"}) == "Deep Blue"
    assert _color_text("Unknown") is None
    assert _color_text(None) is None


def test_mapper_includes_color():
    out = _map_auto_dev_listing_to_schema(
        {"vehicle": {"vin": "V", "year": 2023, "make": "Honda", "model": "Civic",
                     "exteriorColor": "Black", "interiorColor": "Gray"}, "retailListing": {}}
    )
    assert out["color"] == "Black" and out["interior_color"] == "Gray"
