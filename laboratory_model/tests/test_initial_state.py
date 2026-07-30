"""Tests for startup seeding (`app.initial_state`).

The seed file is the only source of initial world contents -- nothing is persisted, and a
`/reset` clears back to empty rather than reloading -- so what it can express bounds what
scenarios the mock lab can start from. These tests cover that expressiveness (notably the
ordering subtlety behind a "locked and occupied" location) and the input validation that
stops a malformed file from producing a half-seeded world.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.initial_state import load_initial_state
from app.main import create_app
from app.state import LaboratoryModelState


def write_seed(tmp_path: Path, payload: Any) -> str:
    # Seed files are read from disk by path, so every test materialises a real file.
    file_path = tmp_path / "initial_state.json"
    file_path.write_text(json.dumps(payload), encoding="utf-8")
    return str(file_path)


@pytest.fixture
def world() -> LaboratoryModelState:
    return LaboratoryModelState()


def test_seeds_items_and_lock_states(world: LaboratoryModelState, tmp_path: Path) -> None:
    file_path = write_seed(
        tmp_path,
        {
            "locations": [
                {"location": "station:1", "occupied": True},
                {"location": "centrifuge:1", "accessible": False},
                {"location": "plateloc:1"},
            ]
        },
    )

    load_initial_state(state=world, file_path=file_path)

    assert world.get_location("station:1").occupied is True
    assert world.get_location("centrifuge:1").accessible is False
    # Both flags are optional and default to "empty and reachable".
    assert world.get_location("plateloc:1").occupied is False
    assert world.get_location("plateloc:1").accessible is True


def test_locked_and_occupied_is_expressible(world: LaboratoryModelState, tmp_path: Path) -> None:
    # A closed instrument that already holds a plate is a legitimate starting state, and
    # expressing it depends on the loader placing the item BEFORE locking the location --
    # locking first would make the add fail with `location_locked`. Regression test for
    # that ordering.
    file_path = write_seed(
        tmp_path,
        {"locations": [{"location": "thermal-cycler:1", "occupied": True, "accessible": False}]},
    )

    load_initial_state(state=world, file_path=file_path)

    seeded = world.get_location("thermal-cycler:1")
    assert seeded.occupied is True
    assert seeded.accessible is False


def test_seeding_replaces_any_previous_contents(world: LaboratoryModelState, tmp_path: Path) -> None:
    # The loader wipes first, so the file describes the whole world rather than a patch.
    world.add_item("left-over")
    file_path = write_seed(tmp_path, {"locations": [{"location": "station:1", "occupied": True}]})

    load_initial_state(state=world, file_path=file_path)

    assert world.get_location("left-over").occupied is False


def test_an_empty_locations_list_seeds_an_empty_world(world: LaboratoryModelState, tmp_path: Path) -> None:
    world.add_item("left-over")
    file_path = write_seed(tmp_path, {"locations": []})

    load_initial_state(state=world, file_path=file_path)

    assert world.snapshot() == []


def test_rejects_a_missing_file(world: LaboratoryModelState, tmp_path: Path) -> None:
    # A mistyped path must fail loudly at startup rather than silently booting an empty
    # world that looks like a workflow bug later.
    with pytest.raises(FileNotFoundError):
        load_initial_state(state=world, file_path=str(tmp_path / "absent.json"))


def test_rejects_a_document_without_a_locations_list(world: LaboratoryModelState, tmp_path: Path) -> None:
    file_path = write_seed(tmp_path, {"items": []})

    with pytest.raises(ValueError):
        load_initial_state(state=world, file_path=file_path)


def test_rejects_a_duplicated_location(world: LaboratoryModelState, tmp_path: Path) -> None:
    # Two entries for one location would seed it ambiguously (which one wins?), so the
    # file is rejected instead of resolved.
    file_path = write_seed(
        tmp_path,
        {"locations": [{"location": "station:1"}, {"location": "station:1", "occupied": True}]},
    )

    with pytest.raises(ValueError):
        load_initial_state(state=world, file_path=file_path)


def test_rejects_an_invalid_location_name(world: LaboratoryModelState, tmp_path: Path) -> None:
    # Seed files go through the same location grammar as the live API, so a name that
    # could never be addressed cannot be seeded either.
    file_path = write_seed(tmp_path, {"locations": [{"location": "bad name"}]})

    with pytest.raises(ValueError):
        load_initial_state(state=world, file_path=file_path)


def test_rejects_an_entry_that_is_not_an_object(world: LaboratoryModelState, tmp_path: Path) -> None:
    file_path = write_seed(tmp_path, {"locations": ["station:1"]})

    with pytest.raises(ValueError):
        load_initial_state(state=world, file_path=file_path)


def test_rejects_a_non_boolean_flag(world: LaboratoryModelState, tmp_path: Path) -> None:
    # A stray "true" string is rejected rather than coerced, so a typo in the seed file
    # cannot quietly flip a location's meaning.
    file_path = write_seed(tmp_path, {"locations": [{"location": "station:1", "occupied": "true"}]})

    with pytest.raises(ValueError):
        load_initial_state(state=world, file_path=file_path)


def test_startup_seeds_the_app_from_the_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # The wiring end of the same feature: the app reads the file named by the environment
    # variable during startup, so a container comes up with its world already populated.
    file_path = write_seed(
        tmp_path,
        {"locations": [{"location": "station:1", "occupied": True, "accessible": False}]},
    )
    monkeypatch.setenv("LABORATORY_MODEL_INITIAL_STATE_FILE", file_path)

    with TestClient(create_app()) as client:
        locations = client.get("/state").json()["locations"]

    assert len(locations) == 1
    assert locations[0]["location"] == "station:1"
    assert locations[0]["occupied"] is True
    assert locations[0]["accessible"] is False


def test_startup_without_the_environment_variable_leaves_an_empty_world(client: TestClient) -> None:
    # The default path (the `client` fixture clears the variable): no seed file configured
    # means the app still resets, so a reused process starts clean rather than inheriting.
    assert client.get("/state").json()["locations"] == []
