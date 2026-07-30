"""Tests for the world's t=0 description (`app.seed`).

The seed file is the only source of world contents -- nothing is persisted, a `/reset` empties
the world without restoring anything, and re-seeding always means reading the file again -- so
what the file can express bounds which scenarios the mock lab can start from. These tests cover
that expressiveness and the validation that stops a malformed file from producing a half-built
world.

The file carries four things and each gets its own group below: the topology (in the same shape
as labcode's `env.yaml`), the opaque device state, which spots start closed, and the initial
occupancy (in the same shape as labcode's `boundary.yaml`). The ordering subtlety that used to
live in `test_initial_state.py` -- that a closed *and* occupied spot is only expressible if items
are placed before spots are closed -- is carried over here, because it is a property of the
loader rather than of the old file format.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from app.main import create_app
from app.seed import load_seed
from app.state import LaboratoryModelState


@pytest.fixture
def world() -> LaboratoryModelState:
    return LaboratoryModelState()


def write(tmp_path: Path, document: Any) -> str:
    # Seed files are read from disk by path, so every test materialises a real file.
    file_path = tmp_path / "seed.yaml"
    file_path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return str(file_path)


# --- Topology. ---


def test_declares_devices_and_their_spots(world: LaboratoryModelState, tmp_path: Path) -> None:
    file_path = write(
        tmp_path,
        {"devices": [{"id": "dispenser", "spots": ["deck", "tube"]}, {"id": "rack", "spots": ["slot"]}]},
    )

    summary = load_seed(state=world, file_path=file_path)

    assert world.list_devices() == ["dispenser", "rack"]
    assert [spot.spot for spot in world.get_device("dispenser").spots] == ["deck", "tube"]
    assert (summary.devices, summary.spots, summary.items) == (2, 3, 0)


def test_spots_use_the_same_list_form_as_labcode(world: LaboratoryModelState, tmp_path: Path) -> None:
    # `devices: [{id, spots: [...]}]` is exactly how labcode's env.yaml writes a device, so the
    # normal case is a faithful copy and a divergence is visible by eye.
    file_path = write(tmp_path, {"devices": [{"id": "loader", "spots": ["stage"]}]})

    load_seed(state=world, file_path=file_path)

    assert world.get_location("loader.stage").occupied is False


def test_a_device_may_declare_no_spots(world: LaboratoryModelState, tmp_path: Path) -> None:
    file_path = write(tmp_path, {"devices": [{"id": "controller"}]})

    load_seed(state=world, file_path=file_path)

    assert world.get_device("controller").spots == []


def test_seeding_replaces_any_previous_world(world: LaboratoryModelState, tmp_path: Path) -> None:
    # The loader declares from scratch, so the file describes the whole world rather than a patch.
    world.declare_devices([("left-over", ["slot"])])
    file_path = write(tmp_path, {"devices": [{"id": "loader", "spots": ["stage"]}]})

    load_seed(state=world, file_path=file_path)

    assert world.list_devices() == ["loader"]


def test_an_empty_devices_list_seeds_an_empty_world(world: LaboratoryModelState, tmp_path: Path) -> None:
    world.declare_devices([("left-over", ["slot"])])
    file_path = write(tmp_path, {"devices": []})

    load_seed(state=world, file_path=file_path)

    assert world.list_devices() == []


# --- Occupancy, from a labcode-shaped boundary. ---


def test_boundary_inputs_place_the_initial_items(world: LaboratoryModelState, tmp_path: Path) -> None:
    file_path = write(
        tmp_path,
        {
            "devices": [{"id": "rack", "spots": ["slot"]}, {"id": "loader", "spots": ["stage"]}],
            "boundary": {"inputs": {"tube": {"spot": "rack.slot"}}},
        },
    )

    summary = load_seed(state=world, file_path=file_path)

    assert world.get_location("rack.slot").occupied is True
    assert world.get_location("loader.stage").occupied is False
    assert summary.items == 1


def test_a_boundary_port_without_a_spot_contributes_no_occupancy(world: LaboratoryModelState, tmp_path: Path) -> None:
    # Pure Data in labcode's terms: a value with no physical object. Skipped rather than rejected,
    # because a boundary copied verbatim from a workflow will contain such ports.
    file_path = write(
        tmp_path,
        {
            "devices": [{"id": "rack", "spots": ["slot"]}],
            "boundary": {"inputs": {"od": {}, "tube": {"spot": "rack.slot"}}},
        },
    )

    summary = load_seed(state=world, file_path=file_path)

    assert summary.items == 1


def test_a_missing_boundary_section_is_fine(world: LaboratoryModelState, tmp_path: Path) -> None:
    file_path = write(tmp_path, {"devices": [{"id": "rack", "spots": ["slot"]}]})

    summary = load_seed(state=world, file_path=file_path)

    assert summary.items == 0


def test_a_boundary_input_naming_an_undeclared_location_is_rejected(
    world: LaboratoryModelState, tmp_path: Path
) -> None:
    # Exactly the divergence this file exists to catch: the workflow believes in a spot that
    # reality does not have. Reported as a seed error, with the location named, rather than as an
    # `unknown_location` from deep inside the store.
    file_path = write(
        tmp_path,
        {"devices": [{"id": "rack", "spots": ["slot"]}], "boundary": {"inputs": {"tube": {"spot": "rack.tray"}}}},
    )

    with pytest.raises(ValueError, match="rack.tray"):
        load_seed(state=world, file_path=file_path)


def test_two_boundary_inputs_in_one_spot_are_rejected(world: LaboratoryModelState, tmp_path: Path) -> None:
    # Not a state the world can hold. Saying so here is clearer than letting the second placement
    # fail with `destination_occupied`.
    file_path = write(
        tmp_path,
        {
            "devices": [{"id": "rack", "spots": ["slot"]}],
            "boundary": {"inputs": {"tube": {"spot": "rack.slot"}, "vial": {"spot": "rack.slot"}}},
        },
    )

    with pytest.raises(ValueError, match="two objects"):
        load_seed(state=world, file_path=file_path)


# --- Opaque device state. ---


def test_device_state_is_seeded_verbatim(world: LaboratoryModelState, tmp_path: Path) -> None:
    # This is how a device's resting condition gets established. It lives in the file rather than
    # being asserted by each server at startup, so that a `/reseed` can restore it and so that no
    # server has to wait for the laboratory model to be up before it can boot.
    file_path = write(
        tmp_path,
        {
            "devices": [
                {
                    "id": "thermal-cycler",
                    "spots": ["block"],
                    "state": {"lid": "open", "cycles": 0, "ready": True, "last_error": None},
                }
            ]
        },
    )

    load_seed(state=world, file_path=file_path)

    assert world.get_device_state("thermal-cycler") == {
        "lid": "open",
        "cycles": 0,
        "ready": True,
        "last_error": None,
    }


def test_seeded_device_state_does_not_affect_accessibility(world: LaboratoryModelState, tmp_path: Path) -> None:
    # `lid: closed` in the file is opaque data, not an instruction to the store. Only
    # `closed_spots` closes a spot, which is what keeps the state bag free of hidden meaning.
    file_path = write(
        tmp_path,
        {"devices": [{"id": "thermal-cycler", "spots": ["block"], "state": {"lid": "closed"}}]},
    )

    load_seed(state=world, file_path=file_path)

    assert world.get_location("thermal-cycler.block").accessible is True


def test_a_structured_state_value_is_rejected(world: LaboratoryModelState, tmp_path: Path) -> None:
    file_path = write(
        tmp_path,
        {"devices": [{"id": "thermal-cycler", "spots": ["block"], "state": {"lid": {"open": True}}}]},
    )

    with pytest.raises(ValueError, match="scalar"):
        load_seed(state=world, file_path=file_path)


def test_an_invalid_state_key_is_rejected(world: LaboratoryModelState, tmp_path: Path) -> None:
    file_path = write(
        tmp_path,
        {"devices": [{"id": "thermal-cycler", "spots": ["block"], "state": {"bad key": "open"}}]},
    )

    with pytest.raises(ValueError, match="state key"):
        load_seed(state=world, file_path=file_path)


# --- Closed spots, and the ordering they depend on. ---


def test_closed_spots_start_inaccessible(world: LaboratoryModelState, tmp_path: Path) -> None:
    file_path = write(
        tmp_path,
        {"devices": [{"id": "station", "spots": ["slot1", "slot2"], "closed_spots": ["slot2"]}]},
    )

    load_seed(state=world, file_path=file_path)

    assert world.get_location("station.slot1").accessible is True
    assert world.get_location("station.slot2").accessible is False


def test_closed_and_occupied_is_expressible(world: LaboratoryModelState, tmp_path: Path) -> None:
    # A shut instrument that already holds a plate is a legitimate starting state, and expressing
    # it depends on the loader placing items BEFORE closing spots -- closing first would make the
    # placement fail with `location_locked`. Regression test for that ordering, carried over from
    # the previous seed format.
    file_path = write(
        tmp_path,
        {
            "devices": [{"id": "thermal-cycler", "spots": ["block"], "closed_spots": ["block"]}],
            "boundary": {"inputs": {"plate": {"spot": "thermal-cycler.block"}}},
        },
    )

    load_seed(state=world, file_path=file_path)

    seeded = world.get_location("thermal-cycler.block")
    assert seeded.occupied is True
    assert seeded.accessible is False


def test_closing_a_spot_the_device_does_not_have_is_rejected(world: LaboratoryModelState, tmp_path: Path) -> None:
    file_path = write(
        tmp_path,
        {"devices": [{"id": "station", "spots": ["slot1"], "closed_spots": ["slot2"]}]},
    )

    with pytest.raises(ValueError, match="undeclared spot"):
        load_seed(state=world, file_path=file_path)


# --- Malformed files. ---


def test_rejects_a_missing_file(world: LaboratoryModelState, tmp_path: Path) -> None:
    # A mistyped path must fail loudly at startup rather than silently booting an empty world that
    # looks like a workflow bug later.
    with pytest.raises(FileNotFoundError):
        load_seed(state=world, file_path=str(tmp_path / "absent.yaml"))


def test_rejects_a_document_that_is_not_a_mapping(world: LaboratoryModelState, tmp_path: Path) -> None:
    file_path = write(tmp_path, ["devices"])

    with pytest.raises(ValueError, match="top-level mapping"):
        load_seed(state=world, file_path=file_path)


def test_rejects_a_document_without_a_devices_list(world: LaboratoryModelState, tmp_path: Path) -> None:
    file_path = write(tmp_path, {"boundary": {"inputs": {}}})

    with pytest.raises(ValueError, match="'devices' list"):
        load_seed(state=world, file_path=file_path)


def test_rejects_a_duplicated_device(world: LaboratoryModelState, tmp_path: Path) -> None:
    file_path = write(
        tmp_path,
        {"devices": [{"id": "rack", "spots": ["slot"]}, {"id": "rack", "spots": ["tray"]}]},
    )

    with pytest.raises(ValueError, match="duplicated"):
        load_seed(state=world, file_path=file_path)


def test_rejects_an_invalid_device_id(world: LaboratoryModelState, tmp_path: Path) -> None:
    # The same grammar the live API enforces, so a device that could never be addressed cannot be
    # declared either. A dot is the location separator, so it may not appear inside a device id.
    file_path = write(tmp_path, {"devices": [{"id": "rack.extra", "spots": ["slot"]}]})

    with pytest.raises(ValueError, match="invalid id"):
        load_seed(state=world, file_path=file_path)


def test_rejects_an_invalid_spot_name(world: LaboratoryModelState, tmp_path: Path) -> None:
    file_path = write(tmp_path, {"devices": [{"id": "rack", "spots": ["bad slot"]}]})

    with pytest.raises(ValueError, match="invalid spot name"):
        load_seed(state=world, file_path=file_path)


def test_rejects_a_device_entry_that_is_not_a_mapping(world: LaboratoryModelState, tmp_path: Path) -> None:
    file_path = write(tmp_path, {"devices": ["rack"]})

    with pytest.raises(ValueError, match="must be a mapping"):
        load_seed(state=world, file_path=file_path)


def test_rejects_a_device_without_an_id(world: LaboratoryModelState, tmp_path: Path) -> None:
    file_path = write(tmp_path, {"devices": [{"spots": ["slot"]}]})

    with pytest.raises(ValueError, match="string 'id'"):
        load_seed(state=world, file_path=file_path)


# --- Wiring: the app seeds itself from the environment. ---


def test_startup_seeds_the_app_from_the_environment(write_seed: Callable[[object], str]) -> None:
    # The wiring end of the same feature: the app reads the file named by the environment during
    # startup, so a container comes up with its world already populated.
    write_seed(
        {
            "devices": [{"id": "rack", "spots": ["slot"], "state": {"lamp": "off"}}],
            "boundary": {"inputs": {"tube": {"spot": "rack.slot"}}},
        }
    )

    with TestClient(create_app()) as client:
        devices = client.get("/state").json()["devices"]

    assert len(devices) == 1
    assert devices[0]["device"] == "rack"
    assert devices[0]["state"] == {"lamp": "off"}
    assert devices[0]["spots"][0]["occupied"] is True


def test_startup_without_a_seed_file_leaves_an_empty_world(unseeded_client: TestClient) -> None:
    # The default path (the `clean_world` fixture clears the variable): no seed file configured
    # means a world with no devices, so a reused process starts clean rather than inheriting.
    assert unseeded_client.get("/state").json() == {"devices": []}


def test_a_broken_seed_file_stops_the_app_from_starting(write_seed: Callable[[object], str]) -> None:
    # A server that came up with a world nobody asked for would be worse than one that refuses to
    # start, so a configured-but-malformed file is left to raise out of the lifespan.
    write_seed({"boundary": {"inputs": {}}})

    with pytest.raises(ValueError, match="'devices' list"), TestClient(create_app()):
        pass  # pragma: no cover - the context manager is what raises
