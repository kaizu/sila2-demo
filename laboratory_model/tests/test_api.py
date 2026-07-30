"""Tests for the HTTP layer (`app.main`), driven through FastAPI's TestClient.

Where `test_state.py` covers the world rules, these cover the contract a caller actually
sees: which status code a rejection carries, the shape of the error envelope, and the two
different paths a bad location name can take through validation. The scenario at the
bottom is the sequence `samples/laboratory_model_smoke.py` walks over a live stack, kept
here so the same ground is covered without docker.
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi.testclient import TestClient


def _error(response) -> dict:
    # Every failure renders the same envelope, so the tests reach into it the same way.
    return response.json()["error"]


def test_health_reports_healthy(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_add_returns_201_and_the_resulting_location_state(client: TestClient) -> None:
    # An add answers with the full state of the location, not just an acknowledgement, so
    # a caller needs no follow-up read.
    response = client.post("/items/add", json={"location": "spot-1"})

    assert response.status_code == 201
    body = response.json()
    assert body["location"] == "spot-1"
    assert body["occupied"] is True
    assert body["accessible"] is True
    assert body["item_id"]


def test_world_rule_violations_are_409_with_a_stable_code(client: TestClient) -> None:
    # 409 conflict is the status for "the world says no". The code is what callers switch
    # on; the details carry the offending location.
    client.post("/locations/lock", json={"location": "spot-1"})

    response = client.post("/items/add", json={"location": "spot-1"})

    assert response.status_code == 409
    error = _error(response)
    assert error["code"] == "location_locked"
    assert error["details"] == {"location": "spot-1"}
    assert error["message"]


def test_degenerate_move_is_a_400_not_a_conflict(client: TestClient) -> None:
    # A move to itself is bad input rather than a world-state conflict, so it is the one
    # domain error that maps to 400.
    client.post("/items/add", json={"location": "spot-1"})

    response = client.post("/items/move", json={"source": "spot-1", "destination": "spot-1"})

    assert response.status_code == 400
    assert _error(response)["code"] == "same_source_and_destination"


def test_move_reports_the_locked_destination_over_the_empty_source(client: TestClient) -> None:
    # The API-level counterpart of the ordering test in test_state.py: accessibility is
    # settled before occupancy, so this reports the lock even though the source is empty.
    client.post("/locations/lock", json={"location": "spot-2"})

    response = client.post("/items/move", json={"source": "spot-1", "destination": "spot-2"})

    assert response.status_code == 409
    assert _error(response)["code"] == "destination_locked"


def test_remove_takes_its_location_from_a_delete_body(client: TestClient) -> None:
    # DELETE /items/remove carries a JSON body, which httpx will not send through the
    # `delete()` shorthand -- hence the explicit request() call here and in any caller.
    client.post("/items/add", json={"location": "spot-1"})

    response = client.request("DELETE", "/items/remove", json={"location": "spot-1"})

    assert response.status_code == 200
    assert response.json()["removed"] is True
    assert client.get("/locations/spot-1").json()["occupied"] is False


def test_location_names_are_percent_encoded_in_the_path(client: TestClient) -> None:
    # Real location names contain a colon ("centrifuge:1") and go into a path segment, so
    # the encoded form has to resolve to the same location the body form created.
    client.post("/items/add", json={"location": "centrifuge:1"})

    response = client.get(f"/locations/{quote('centrifuge:1', safe='')}")

    assert response.status_code == 200
    assert response.json()["occupied"] is True


def test_a_bad_name_in_the_path_is_400_invalid_location(client: TestClient) -> None:
    # The path parameter bypasses the request models, so the handler validates it itself;
    # this is the code that identifies that route.
    response = client.get(f"/locations/{quote('bad name', safe='')}")

    assert response.status_code == 400
    assert _error(response)["code"] == "invalid_location"


def test_dotted_names_are_currently_rejected(client: TestClient) -> None:
    # The location grammar has no `.`, so labcode's dotted spot names (dispenser.deck) do
    # not round-trip today. Pinned deliberately: the device-centric refactor (M0) has to
    # widen this, and that change should be visible as this test failing.
    response = client.get(f"/locations/{quote('dispenser.deck', safe='')}")

    assert response.status_code == 400
    assert _error(response)["code"] == "invalid_location"


def test_a_bad_name_in_a_body_is_400_invalid_request(client: TestClient) -> None:
    # Bodies are validated by the pydantic request models, so a bad name arrives as a
    # RequestValidationError. It must still come back in this API's envelope with a 400,
    # not as FastAPI's default 422 shape.
    response = client.post("/items/add", json={"location": "bad name"})

    assert response.status_code == 400
    assert _error(response)["code"] == "invalid_request"


def test_a_missing_field_is_400_invalid_request(client: TestClient) -> None:
    response = client.post("/items/add", json={})

    assert response.status_code == 400
    assert _error(response)["code"] == "invalid_request"


def test_state_returns_the_whole_world(client: TestClient) -> None:
    client.post("/items/add", json={"location": "spot-2"})
    client.post("/locations/lock", json={"location": "spot-1"})

    response = client.get("/state")

    assert response.status_code == 200
    locations = response.json()["locations"]
    assert [entry["location"] for entry in locations] == ["spot-1", "spot-2"]


def test_reset_clears_the_world(client: TestClient) -> None:
    client.post("/items/add", json={"location": "spot-1"})

    response = client.post("/reset")

    assert response.status_code == 200
    assert response.json() == {"cleared": True}
    assert client.get("/state").json()["locations"] == []


def test_smoke_scenario_add_move_lock_remove(client: TestClient) -> None:
    """The sequence `samples/laboratory_model_smoke.py` runs against a live stack.

    Kept as one test rather than split up because the point is the whole life cycle: an
    item is created, carried, shut in, released and taken out, and its identity has to be
    the same at every step."""
    # Create, and remember the id the world minted.
    added = client.post("/items/add", json={"location": "spot-1"}).json()
    item_id = added["item_id"]

    # Carry it: the source empties and the destination holds the same item.
    moved = client.post("/items/move", json={"source": "spot-1", "destination": "station:1"}).json()
    assert moved["item_id"] == item_id
    assert client.get("/locations/spot-1").json()["occupied"] is False
    assert client.get(f"/locations/{quote('station:1', safe='')}").json()["item_id"] == item_id

    # Shut it in: still there, no longer reachable, and removal is refused.
    locked = client.post("/locations/lock", json={"location": "station:1"}).json()
    assert locked["accessible"] is False
    blocked = client.request("DELETE", "/items/remove", json={"location": "station:1"})
    assert blocked.status_code == 409
    assert _error(blocked)["code"] == "location_locked"

    # Release it: the same call now succeeds and reports the same id, which is what proves
    # the rejection above was the lock rather than anything else.
    client.post("/locations/unlock", json={"location": "station:1"})
    removed = client.request("DELETE", "/items/remove", json={"location": "station:1"}).json()
    assert removed["removed"] is True
    assert removed["item_id"] == item_id
