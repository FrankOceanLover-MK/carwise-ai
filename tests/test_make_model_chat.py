"""Make / model / fuel extraction flows from the LLM's JSON into the search criteria."""
from fastapi.testclient import TestClient

from app import main

client = TestClient(main.app)


def _fake_llm(filter_json):
    def fake(messages, **kwargs):
        system = messages[0]["content"]
        if "filter extraction" in system:
            return filter_json
        return "Here is a short recommendation."
    return fake


def test_extract_filters_reads_make_and_model(monkeypatch):
    monkeypatch.setattr(
        main, "chat_completion",
        _fake_llm('{"budget": 20000, "make": "chevy", "model": "Bolt", "fuel_type": "Electric"}'),
    )
    f = main.extract_filters_from_question("used chevy bolt under 20k")
    assert f == {"budget": 20000.0, "fuel_type": "Electric", "make": "Chevrolet", "model": "Bolt"}


def test_criteria_carries_make_and_model():
    c = main.build_criteria_from_filters({"make": "Honda", "model": "Civic", "fuel_type": "Hybrid"}, "90210")
    assert (c.make, c.model, c.fuel_type, c.zip_code) == ("Honda", "Civic", "Hybrid", "90210")


def test_chat_passes_make_model_to_search(monkeypatch):
    seen = {}
    monkeypatch.setattr(main, "chat_completion", _fake_llm('{"make": "Toyota", "model": "Prius"}'))

    def fake_search(criteria, top_k=3):
        seen["c"] = criteria
        return []

    monkeypatch.setattr(main, "search_pipeline", fake_search)
    r = client.post("/chat", json={"question": "used prius"})
    assert r.status_code == 200
    assert (seen["c"].make, seen["c"].model) == ("Toyota", "Prius")
    assert "different model" in r.json()["answer"]


def test_no_results_message_mentions_fuel_and_brand():
    msg = main._no_results_message({"fuel_type": "Electric", "make": "Honda"}, None)
    assert "fuel type" in msg and "brand" in msg


def test_extract_filters_reads_color(monkeypatch):
    monkeypatch.setattr(main, "chat_completion", _fake_llm('{"body_style": "Sedan", "color": "black"}'))
    assert main.extract_filters_from_question("a cute black sudan") == {"body_style": "Sedan", "color": "black"}
    c = main.build_criteria_from_filters({"color": "black"})
    assert c.color == "black"


def test_one_bad_listing_does_not_cause_a_500(monkeypatch):
    from app.search import ListingWithScore, ScoreBreakdown

    good = ListingWithScore({"id": "1", "year": 2022, "make": "Ram", "model": "1500"}, ScoreBreakdown(1, 1, 1, 1, 1))
    bad = ListingWithScore({"id": "2", "year": 2022, "make": "Ram", "model": {"oops": 1}}, ScoreBreakdown(1, 1, 1, 1, 1))
    monkeypatch.setattr(main, "chat_completion", _fake_llm("{}"))
    monkeypatch.setattr(main, "search_pipeline", lambda c, top_k=3: [bad, good])
    r = client.post("/chat", json={"question": "a truck"})
    assert r.status_code == 200
    assert [x["id"] for x in r.json()["listings"]] == ["1"]
