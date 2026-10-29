"""Manual smoke test that hits the real external APIs (needs AUTO_DEV_API_KEY). Run from the repo root:
    python -m scripts.smoke_test_apis
"""
from app.external_apis import (
    auto_dev_vin_decode,
    nhtsa_decode_vin,
    carquery_get_trims,
    get_economy_from_carquery,
    get_car_profile_from_vin,
)


def main():
    vin = "WP0AF2A99KS165242"

    print("=== Auto.dev VIN decode ===")
    auto_data = auto_dev_vin_decode(vin)
    vehicle = auto_data.get("vehicle", {})
    year = vehicle.get("year")
    make = vehicle.get("make")
    model = vehicle.get("model")
    print(year, make, model)

    print("\n=== NHTSA decode ===")
    nhtsa_data = nhtsa_decode_vin(vin)
    print(nhtsa_data.get("ModelYear"), nhtsa_data.get("Make"), nhtsa_data.get("Model"))

    print("\n=== CarQuery trims example (from decoded VIN) ===")
    trims = carquery_get_trims(make=make, model=model, year=year)
    print(trims[:2])

    print("\n=== CarQuery fuel economy via helper ===")
    econ = get_economy_from_carquery(year=year, make=make, model=model)
    print(econ or "No economy data from CarQuery.")

    print("\n=== Full car profile from VIN ===")
    profile = get_car_profile_from_vin(vin)
    print(profile)

    # === ADD THIS TO TEST VALIDATION ===
    from schemas import CarProfile
    print("\n=== Validating with Pydantic... ===")
    validated = CarProfile(**profile)
    print("SUCCESS! The data matches the schema.")


if __name__ == "__main__":
    main()
