"""Tests for the HTTP layer (`app.main`), driven through FastAPI's TestClient.

Where `test_state.py` covers the world rules, these cover the contract a caller actually sees:
which status code a rejection carries, the shape of the error envelope, and the two different
paths a bad location name can take through validation. The scenario at the bottom is the
sequence `samples/laboratory_model_smoke.py` walks over a live stack, kept here so the same
ground is covered without docker.

The status codes carry a distinction worth stating: **400** is "your request is malformed",
**404** is "that place does not exist", and **409** is "the world says no". The middle one is
new -- a location used to spring into existence on being mentioned, so there was nothing to
report as absent.
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


# --- Names. Dotted locations are the addressing scheme now, not an error. ---


def test_dotted_names_are_the_addressing_scheme(client: TestClient) -> None:
    # The inverse of what this file used to assert. `device.spot` is the only form of a location,
    # so a dotted name round-trips through a path segment and reads back as a spot.
    response = client.get(f"/locations/{quote('centrifuge.deck', safe='')}")

    assert response.status_code == 200
    body = response.json()
    assert body["device"] == "centrifuge"
    assert body["spot"] == "deck"
    assert body["location"] == "centrifuge.deck"


def test_a_name_without_a_dot_is_400_invalid_location(client: TestClient) -> None:
    # There is no "device standing in for its only spot": a bare device name is malformed, which
    # is what makes any location missed by the rename fail loudly instead of addressing something
    # unintended. The previous generation of names (`centrifuge:1`) lands here.
    response = client.get(f"/locations/{quote('centrifuge:1', safe='')}")

    assert response.status_code == 400
    assert _error(response)["code"] == "invalid_location"


def test_a_name_with_two_dots_is_400_invalid_location(client: TestClient) -> None:
    response = client.get(f"/locations/{quote('a.b.c', safe='')}")

    assert response.status_code == 400
    assert _error(response)["code"] == "invalid_location"


def test_a_bad_character_in_the_path_is_400_invalid_location(client: TestClient) -> None:
    # The path parameter bypasses the request models, so the handler validates it itself; this is
    # the code that identifies that route.
    response = client.get(f"/locations/{quote('bad name.deck', safe='')}")

    assert response.status_code == 400
    assert _error(response)["code"] == "invalid_location"


def test_a_bad_name_in_a_body_is_400_invalid_request(client: TestClient) -> None:
    # Bodies are validated by the pydantic request models, so a bad name arrives as a
    # RequestValidationError. It must still come back in this API's envelope with a 400, not as
    # FastAPI's default 422 shape.
    response = client.post("/items/add", json={"location": "bad name.deck"})

    assert response.status_code == 400
    assert _error(response)["code"] == "invalid_request"


def test_a_missing_field_is_400_invalid_request(client: TestClient) -> None:
    response = client.post("/items/add", json={})

    assert response.status_code == 400
    assert _error(response)["code"] == "invalid_request"


# --- Existence. ---


def test_a_well_formed_but_undeclared_location_is_404(client: TestClient) -> None:
    response = client.get(f"/locations/{quote('station.slot9', safe='')}")

    assert response.status_code == 404
    error = _error(response)
    assert error["code"] == "unknown_location"
    assert error["details"] == {"location": "station.slot9"}


def test_adding_to_an_undeclared_location_is_404(client: TestClient) -> None:
    response = client.post("/items/add", json={"location": "dispenser.deck"})

    assert response.status_code == 404
    assert _error(response)["code"] == "unknown_location"


# --- Items. ---


def test_add_returns_201_and_the_resulting_spot_state(client: TestClient) -> None:
    # An add answers with the full state of the spot, not just an acknowledgement, so a caller
    # needs no follow-up read.
    response = client.post("/items/add", json={"location": "station.slot1"})

    assert response.status_code == 201
    body = response.json()
    assert body["location"] == "station.slot1"
    assert body["occupied"] is True
    assert body["accessible"] is True
    assert body["item_id"]


def test_world_rule_violations_are_409_with_a_stable_code(client: TestClient) -> None:
    # 409 conflict is the status for "the world says no". The code is what callers switch on; the
    # details carry the offending location.
    client.post("/locations/lock", json={"location": "centrifuge.deck"})

    response = client.post("/items/add", json={"location": "centrifuge.deck"})

    assert response.status_code == 409
    error = _error(response)
    assert error["code"] == "location_locked"
    assert error["details"] == {"location": "centrifuge.deck"}
    assert error["message"]


def test_degenerate_move_is_a_400_not_a_conflict(client: TestClient) -> None:
    # A move to itself is bad input rather than a world-state conflict, so it is the one domain
    # error that maps to 400.
    client.post("/items/add", json={"location": "station.slot1"})

    response = client.post("/items/move", json={"source": "station.slot1", "destination": "station.slot1"})

    assert response.status_code == 400
    assert _error(response)["code"] == "same_source_and_destination"


def test_move_reports_the_locked_destination_over_the_empty_source(client: TestClient) -> None:
    # The API-level counterpart of the ordering test in test_state.py: accessibility is settled
    # before occupancy, so this reports the lock even though the source is empty.
    client.post("/locations/lock", json={"location": "centrifuge.deck"})

    response = client.post("/items/move", json={"source": "station.slot1", "destination": "centrifuge.deck"})

    assert response.status_code == 409
    assert _error(response)["code"] == "destination_locked"


def test_remove_takes_its_location_from_a_delete_body(client: TestClient) -> None:
    # DELETE /items/remove carries a JSON body, which httpx will not send through the `delete()`
    # shorthand -- hence the explicit request() call here and in any caller.
    client.post("/items/add", json={"location": "station.slot1"})

    response = client.request("DELETE", "/items/remove", json={"location": "station.slot1"})

    assert response.status_code == 200
    assert response.json()["removed"] is True
    assert client.get("/locations/station.slot1").json()["occupied"] is False


# --- Devices and the whole-world view. ---


def test_devices_lists_the_declared_topology(client: TestClient) -> None:
    response = client.get("/devices")

    assert response.status_code == 200
    assert response.json()["devices"] == ["centrifuge", "station", "thermal-cycler"]


def test_a_device_reports_its_state_and_its_spots(client: TestClient) -> None:
    response = client.get("/devices/station")

    assert response.status_code == 200
    body = response.json()
    assert body["device"] == "station"
    assert body["state"] == {}
    assert [spot["spot"] for spot in body["spots"]] == ["slot1", "slot2"]


def test_an_undeclared_device_is_404(client: TestClient) -> None:
    response = client.get("/devices/dispenser")

    assert response.status_code == 404
    assert _error(response)["code"] == "unknown_device"


def test_state_returns_every_declared_device(client: TestClient) -> None:
    client.post("/items/add", json={"location": "station.slot2"})

    response = client.get("/state")

    assert response.status_code == 200
    devices = response.json()["devices"]
    assert [device["device"] for device in devices] == ["centrifuge", "station", "thermal-cycler"]
    # The seed's opaque device state is visible here, which is what makes `/state` usable as the
    # single assertion surface for a test.
    assert devices[0]["state"] == {"door": "open"}
    station_spots = {spot["location"]: spot for spot in devices[1]["spots"]}
    assert station_spots["station.slot2"]["occupied"] is True
    assert station_spots["station.slot1"]["occupied"] is False


def test_state_of_an_unseeded_world_has_no_devices(unseeded_client: TestClient) -> None:
    # No seed file configured means a world with no topology at all -- which is empty rather
    # than broken.
    assert unseeded_client.get("/state").json() == {"devices": []}


# --- Opaque device state over HTTP. ---


def test_setting_and_reading_a_state_key(client: TestClient) -> None:
    response = client.put("/devices/centrifuge/state/door", json={"value": "closed"})

    assert response.status_code == 200
    assert response.json() == {"device": "centrifuge", "key": "door", "value": "closed"}
    assert client.get("/devices/centrifuge/state").json()["state"]["door"] == "closed"


def test_state_values_keep_their_json_type(client: TestClient) -> None:
    # A bool must not arrive back as 1, and an int must not arrive back as "3": the server that
    # wrote a key is the only thing that knows what it means, so the value is kept verbatim.
    client.put("/devices/centrifuge/state/ready", json={"value": True})
    client.put("/devices/centrifuge/state/cycles", json={"value": 3})

    stored = client.get("/devices/centrifuge/state").json()["state"]
    assert stored["ready"] is True
    assert stored["cycles"] == 3


def test_a_structured_state_value_is_rejected(client: TestClient) -> None:
    # Scalars only. A nested value would invite callers to model meaning inside something nothing
    # validates.
    response = client.put("/devices/centrifuge/state/door", json={"value": {"open": True}})

    assert response.status_code == 400
    assert _error(response)["code"] == "invalid_request"


def test_unsetting_a_state_key_returns_the_remaining_bag(client: TestClient) -> None:
    client.put("/devices/centrifuge/state/spin", json={"value": 1})

    response = client.request("DELETE", "/devices/centrifuge/state/spin")

    assert response.status_code == 200
    # `door` came from the seed and is untouched; only the requested key is gone.
    assert response.json()["state"] == {"door": "open"}


def test_unsetting_a_key_that_is_not_set_is_404(client: TestClient) -> None:
    response = client.request("DELETE", "/devices/centrifuge/state/absent")

    assert response.status_code == 404
    assert _error(response)["code"] == "unknown_state_key"


def test_a_bad_state_key_is_400(client: TestClient) -> None:
    response = client.put(f"/devices/centrifuge/state/{quote('bad key', safe='')}", json={"value": 1})

    assert response.status_code == 400
    assert _error(response)["code"] == "invalid_state_key"


# --- Lifecycle. ---


def test_reset_empties_the_world_but_keeps_the_topology(client: TestClient) -> None:
    # The distinction that makes reset safe to call between tests: afterwards the devices are
    # still there, so the very next add works.
    client.post("/items/add", json={"location": "station.slot1"})

    response = client.post("/reset")

    assert response.status_code == 200
    assert response.json() == {"cleared": True}
    devices = client.get("/state").json()["devices"]
    assert [device["device"] for device in devices] == ["centrifuge", "station", "thermal-cycler"]
    assert client.get("/locations/station.slot1").json()["occupied"] is False
    # Reset clears the opaque state too, which is why it is not a substitute for a reseed.
    assert devices[0]["state"] == {}


def test_reseed_restores_the_seeded_world(client: TestClient) -> None:
    client.post("/items/add", json={"location": "station.slot1"})
    client.post("/reset")

    response = client.post("/reseed")

    assert response.status_code == 200
    body = response.json()
    assert body["reseeded"] is True
    assert body["devices"] == 3
    assert body["spots"] == 4
    # The seed's device state is back, which a plain reset does not do.
    assert client.get("/devices/centrifuge/state").json()["state"] == {"door": "open"}


def test_reseed_without_a_configured_file_is_refused(unseeded_client: TestClient) -> None:
    response = unseeded_client.post("/reseed")

    assert response.status_code == 409
    assert _error(response)["code"] == "seed_file_not_configured"


# --- The whole life cycle, as the live smoke sample walks it. ---


def test_smoke_scenario_add_move_lock_remove(client: TestClient) -> None:
    """The sequence `samples/laboratory_model_smoke.py` runs against a live stack.

    Kept as one test rather than split up because the point is the whole life cycle: an item is
    created, carried, shut in, released and taken out, and its identity has to be the same at
    every step."""
    # Create, and remember the id the world minted.
    added = client.post("/items/add", json={"location": "station.slot1"}).json()
    item_id = added["item_id"]

    # Carry it: the source empties and the destination holds the same item.
    moved = client.post("/items/move", json={"source": "station.slot1", "destination": "centrifuge.deck"}).json()
    assert moved["item_id"] == item_id
    assert client.get("/locations/station.slot1").json()["occupied"] is False
    assert client.get("/locations/centrifuge.deck").json()["item_id"] == item_id

    # Shut it in: still there, no longer reachable, and removal is refused.
    locked = client.post("/locations/lock", json={"location": "centrifuge.deck"}).json()
    assert locked["accessible"] is False
    blocked = client.request("DELETE", "/items/remove", json={"location": "centrifuge.deck"})
    assert blocked.status_code == 409
    assert _error(blocked)["code"] == "location_locked"

    # Release it: the same call now succeeds and reports the same id, which is what proves the
    # rejection above was the lock rather than anything else.
    client.post("/locations/unlock", json={"location": "centrifuge.deck"})
    removed = client.request("DELETE", "/items/remove", json={"location": "centrifuge.deck"}).json()
    assert removed["removed"] is True
    assert removed["item_id"] == item_id
