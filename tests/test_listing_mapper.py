

def test_duplicate_make_is_removed_from_model():
    from app.external_apis import _map_auto_dev_listing_to_schema as m
    out = m({"vehicle": {"vin": "V", "year": 2026, "make": "Mazda", "model": "Mazda CX-30"}, "retailListing": {}})
    assert out["model"] == "CX-30"
    out = m({"vehicle": {"vin": "V", "year": 2026, "make": "Honda", "model": "Civic"}, "retailListing": {}})
    assert out["model"] == "Civic"


def test_numeric_model_becomes_text():
    from app.external_apis import _map_auto_dev_listing_to_schema as m
    out = m({"vehicle": {"vin": "V", "year": 2022, "make": "Ram", "model": 1500, "trim": 2500}, "retailListing": {}})
    assert out["model"] == "1500" and out["trim"] == "2500"
    out = m({"vehicle": {"vin": "V", "year": 2022, "make": "Ram", "model": None}, "retailListing": {}})
    assert out["model"] is None
