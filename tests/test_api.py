"""API-level tests using FastAPI's TestClient. External services are mocked."""
from fastapi.testclient import TestClient

from app import main, llm_prompts

client = TestClient(main.app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200


def test_chat_rejects_empty_question():
    r = client.post("/chat", json={"question": "   "})
    assert r.status_code == 400


def test_vin_prompt_includes_customer_question():
    msgs = llm_prompts.build_car_advice_messages(
        user_question="Is this car good for road trips?", car_summary="2019 Porsche 911"
    )
    assert "Is this car good for road trips?" in msgs[1]["content"]
    assert "2019 Porsche 911" in msgs[1]["content"]


# --- live-listings behaviour (no sample data, ZIP handling, honest errors) ---------------------

import pytest

from app import external_apis


class _Resp:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body or {"data": []}
        self.text = str(self._body)

    def json(self):
        return self._body


def test_zip_and_distance_are_sent_to_auto_dev(monkeypatch):
    monkeypatch.setattr(external_apis, "AUTO_DEV_API_KEY", "k")
    seen = {}

    def fake_get(url, params, headers, timeout):
        seen.update(params)
        return _Resp()

    monkeypatch.setattr(external_apis.requests, "get", fake_get)
    external_apis.fetch_active_listings(zip_code="95035", max_distance=25)
    assert seen["zip"] == "95035" and seen["distance"] == 25


def test_service_failure_raises_instead_of_returning_empty(monkeypatch):
    monkeypatch.setattr(external_apis, "AUTO_DEV_API_KEY", "k")
    monkeypatch.setattr(external_apis.requests, "get", lambda *a, **k: _Resp(500))
    with pytest.raises(external_apis.ApiError):
        external_apis.fetch_active_listings()


def test_near_me_without_zip_asks_for_zip(monkeypatch):
    monkeypatch.setattr(main, "extract_filters_from_question", lambda q: {"body_style": "truck"})
    r = client.post("/chat", json={"question": "trucks near me"})
    assert r.status_code == 200
    body = r.json()
    assert "ZIP" in body["answer"] and body["listings"] == []


def test_no_results_does_not_call_the_llm(monkeypatch):
    monkeypatch.setattr(main, "extract_filters_from_question", lambda q: {"budget": 5000})
    monkeypatch.setattr(main, "search_pipeline", lambda criteria, top_k=3: [])

    def boom(*a, **k):
        raise AssertionError("LLM should not be called when there are no listings")

    monkeypatch.setattr(main, "chat_completion", boom)
    r = client.post("/chat", json={"question": "a car under $5k"})
    assert "couldn't find" in r.json()["answer"]


def test_listing_service_down_is_reported_honestly(monkeypatch):
    monkeypatch.setattr(main, "extract_filters_from_question", lambda q: {})

    def down(criteria, top_k=3):
        raise main.ExternalApiError("The listings service timed out.")

    monkeypatch.setattr(main, "search_pipeline", down)
    r = client.post("/chat", json={"question": "any suv"})
    assert "couldn't reach" in r.json()["answer"]


def test_reads_multiple_pages_and_survives_a_late_failure(monkeypatch):
    monkeypatch.setattr(external_apis, "AUTO_DEV_API_KEY", "k")
    row = lambda n: {"vin": f"V{n}", "vehicle": {"year": 2020, "make": "Toyota", "model": f"M{n}"}, "retailListing": {}}
    pages_seen = []

    def fake_get(url, params, headers, timeout):
        pages_seen.append(params["page"])
        if params["page"] == 1:
            return _Resp(200, {"data": [row(1), row(2)]})
        if params["page"] == 2:
            return _Resp(500)
        return _Resp(200, {"data": []})

    monkeypatch.setattr(external_apis.requests, "get", fake_get)
    out = external_apis.fetch_active_listings(pages=3)
    assert [c["vin"] for c in out] == ["V1", "V2"]   # page 2 failed, page 1 results are kept
    assert sorted(pages_seen) == [1, 2, 3]   # later pages are fetched together, a failed one is just skipped
