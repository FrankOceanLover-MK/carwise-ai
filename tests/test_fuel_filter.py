import pytest

from app import search as s
from app.search import SearchCriteria, _fuel_matches


def car(make, model, year=2024, fuel="Gasoline", trim="", **kw):
    return {"id": f"{make}{model}{year}{trim}", "make": make, "model": model, "year": year,
            "fuel_type": fuel, "trim": trim, "price": 25000, **kw}


HYBRIDS = [
    car("Toyota", "Camry", 2026),                      # Auto.dev says Gasoline
    car("Toyota", "Prius", 2022),
    car("Toyota", "RAV4", 2023, trim="XLE Hybrid"),
    car("Toyota", "RAV4 Prime", 2023),
    car("Toyota", "Sienna", 2022),
    car("Honda", "Accord", 2023, fuel="Hybrid"),
    car("Lexus", "ES", 2021, trim="300h"),
    car("Ford", "Escape", 2022, fuel="Gas/Electric Hybrid"),
    car("Jeep", "Wrangler", 2023, trim="4xe"),
]
EVS = [
    car("Tesla", "Model 3", 2023, fuel=""),
    car("Nissan", "Leaf", 2020, fuel="Electric"),
    car("Chevrolet", "Bolt EV", 2022),
    car("Hyundai", "Ioniq 5", 2023, fuel=""),
    car("Ford", "Mustang Mach-E", 2022, fuel=""),
    car("Kia", "EV6", 2023, fuel=""),
    car("Chevrolet", "Equinox", 2025, trim="EV LT"),
    car("Rivian", "R1T", 2023, fuel=""),
]
GAS = [car("Toyota", "Camry", 2022), car("Honda", "Civic", 2021), car("Ford", "F-150", 2020),
       car("Chevrolet", "Equinox", 2022), car("Toyota", "RAV4", 2022)]


@pytest.mark.parametrize("c", HYBRIDS)
def test_hybrids_match_hybrid(c):
    assert _fuel_matches(c, "hybrid")
    assert not _fuel_matches(c, "electric")


@pytest.mark.parametrize("c", EVS)
def test_evs_match_electric(c):
    assert _fuel_matches(c, "electric")
    assert _fuel_matches(c, "EV")
    assert not _fuel_matches(c, "hybrid")
    assert not _fuel_matches(c, "gas")


@pytest.mark.parametrize("c", GAS)
def test_gas_cars_are_not_hybrid_or_electric(c):
    assert not _fuel_matches(c, "hybrid")
    assert not _fuel_matches(c, "electric")
    assert _fuel_matches(c, "gasoline")


def test_plug_in_only():
    assert _fuel_matches(car("Toyota", "RAV4 Prime", 2023), "plug-in")
    assert _fuel_matches(car("Toyota", "RAV4 Prime", 2023), "PHEV")
    assert not _fuel_matches(car("Toyota", "Prius", 2022), "plug-in")


def test_diesel_and_unknown():
    assert _fuel_matches(car("Ram", "2500", fuel="Diesel"), "diesel")
    assert not _fuel_matches(car("Ram", "2500"), "diesel")
    assert _fuel_matches(car("Ford", "F-150", fuel="Flex Fuel"), "flex")


def test_old_camry_is_not_hybrid_by_name_alone():
    assert not _fuel_matches(car("Toyota", "Camry", 2022), "hybrid")


def test_no_fuel_filter_passes_everything():
    assert s._passes_filters(car("Honda", "Civic"), SearchCriteria())


def test_make_filter_is_case_insensitive():
    assert s._passes_filters(car("Toyota", "Camry"), SearchCriteria(make="Toyota"))


class FakeFetch:
    def __init__(self, listings):
        self.listings, self.calls = listings, []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return self.listings


@pytest.mark.parametrize("fuel,expected", [("hybrid", "Prius"), ("electric", "Leaf")])
def test_search_end_to_end_and_fetches_extra_pages(monkeypatch, fuel, expected):
    fake = FakeFetch(GAS + [car("Toyota", "Prius", 2022), car("Nissan", "Leaf", 2020, fuel="Electric")])
    monkeypatch.setattr(s, "fetch_active_listings", fake)
    out = s.search(SearchCriteria(fuel_type=fuel), top_k=3)
    assert [r.listing["model"] for r in out] == [expected]
    assert fake.calls[-1]["pages"] == s.FUEL_SEARCH_PAGES


def test_no_fuel_filter_uses_default_pages(monkeypatch):
    fake = FakeFetch(GAS)
    monkeypatch.setattr(s, "fetch_active_listings", fake)
    s.search(SearchCriteria(), top_k=3)
    assert "pages" not in fake.calls[-1]


# ---- make and model ----

@pytest.mark.parametrize("raw,expected", [
    ("chevy", "Chevrolet"), ("Chevrolet", "Chevrolet"), ("toyota", "Toyota"), ("BMW", "BMW"),
    ("bmw", "BMW"), ("vw", "Volkswagen"), ("mercedes", "Mercedes-Benz"), ("land rover", "Land Rover"),
    ("tesla", "Tesla"), (None, None), ("", None),
])
def test_canonical_make(raw, expected):
    assert s.canonical_make(raw) == expected


@pytest.mark.parametrize("wanted,model,ok", [
    ("Civic", "Civic", True), ("civic", "Civic Type R", True), ("CR-V", "CR-V", True),
    ("crv", "CR-V", True), ("Model 3", "Model 3", True), ("F-150", "F-150", True),
    ("Civic", "Accord", False), ("3", "CX-30", False), ("Mustang", "Mustang Mach-E", True),
])
def test_model_matches(wanted, model, ok):
    assert s._model_matches({"model": model}, wanted) is ok


def test_search_make_and_model(monkeypatch):
    fake = FakeFetch([car("Honda", "Civic"), car("Honda", "Accord"), car("Toyota", "Camry")])
    monkeypatch.setattr(s, "fetch_active_listings", fake)
    out = s.search(SearchCriteria(make="honda", model="civic"), top_k=3)
    assert [r.listing["model"] for r in out] == ["Civic"]
    assert fake.calls[-1]["make"] == "Honda"           # canonical spelling sent to Auto.dev
    assert fake.calls[-1]["pages"] == s.FUEL_SEARCH_PAGES


def test_make_plus_fuel(monkeypatch):
    fake = FakeFetch([car("Toyota", "Camry", 2026), car("Toyota", "Camry", 2022), car("Honda", "Accord", 2023, fuel="Hybrid")])
    monkeypatch.setattr(s, "fetch_active_listings", fake)
    out = s.search(SearchCriteria(make="Toyota", fuel_type="hybrid"), top_k=3)
    assert [(r.listing["make"], r.listing["year"]) for r in out] == [("Toyota", 2026)]
