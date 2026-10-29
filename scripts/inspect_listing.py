"""Print what Auto.dev returns for one live listing (keys only, no personal data).

Use this to check which photo and link fields your plan includes:
    python -m scripts.inspect_listing
"""
import json
import os

import requests
from dotenv import load_dotenv

load_dotenv()
key = os.getenv("AUTO_DEV_API_KEY")
if not key:
    raise SystemExit("Set AUTO_DEV_API_KEY in your .env first.")

resp = requests.get("https://api.auto.dev/listings", params={"apikey": key, "limit": 1}, timeout=30)
print("HTTP", resp.status_code)
item = (resp.json().get("data") or [{}])[0]
print("top-level keys:    ", sorted(item))
print("retailListing keys:", sorted(item.get("retailListing") or {}))
print("vehicle keys:      ", sorted(item.get("vehicle") or {}))

from app.external_apis import _map_auto_dev_listing_to_schema  # noqa: E402

mapped = _map_auto_dev_listing_to_schema(item)
print("\nMapped result:")
print(json.dumps({k: mapped[k] for k in ("year", "make", "model", "price", "image_url", "listing_url", "dealer", "city", "state")}, indent=2))
