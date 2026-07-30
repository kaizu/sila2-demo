"""Loading the world's t=0 description from a YAML seed file.

`load_seed` is called at server startup and again by `POST /reseed` (see `main.py`). It is the
only source of world contents: nothing is persisted, `POST /reset` empties the world without
restoring anything, and re-seeding always means reading this file again.

The file carries four things, which is why it exists as one document rather than several:

* the **topology** -- which devices exist and which spots each has. Written in the same shape
  labcode's `env.yaml` uses (`devices: [{id, spots: [...]}]`), so the two can be compared, or
  copied, by eye.
* the **opaque device state** at t=0 (`state:`), which is how a device's resting condition
  (a lid open, a door closed) gets established. It belongs in the file rather than being
  asserted by each server at startup, for two reasons: a server-written value would be lost by
  the next `/reset` or `/reseed` with nothing to restore it, and having servers write at boot
  would make them depend on the laboratory model being up first, which today they do not.
* which spots start **closed** (`closed_spots:`), so that "a shut instrument already holding a
  plate" is expressible as a starting state.
* the initial **occupancy**, taken from `boundary.inputs` in the same shape as labcode's
  `boundary.yaml`: each Object-bearing port names the spot its object starts in.

This file is deliberately *not* the labcode document itself. It has the same shape so the
normal case is a faithful copy, but keeping it separate is what allows a divergence to be
introduced on purpose -- a spot the workflow believes in and reality does not, say -- which is
the whole reason for running a second model of the world.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .models import StateValue, validate_location, validate_name, validate_state_key
from .state import LaboratoryModelState

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SeedSummary:
    """What a load produced. Returned so startup can log it and `/reseed` can answer with it,
    which is enough to confirm the intended file was read without dumping the whole world."""

    devices: int
    spots: int
    items: int


def load_seed(*, state: LaboratoryModelState, file_path: str) -> SeedSummary:
    """Read `file_path` and rebuild the world from it. Raises on anything malformed."""
    path = Path(file_path)
    if not path.is_file():
        # A mistyped path must fail loudly rather than silently booting an empty world that
        # looks like a workflow bug much later.
        raise FileNotFoundError(f"Seed file does not exist: {file_path}")

    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("Seed file must contain a top-level mapping")

    # Parse and validate the whole document before touching the store, so a malformed file
    # cannot leave a half-built world behind.
    declarations = _parse_devices(document.get("devices"))
    occupied_locations = _parse_boundary_inputs(document.get("boundary"))

    _check_declared(declarations, occupied_locations)

    # Apply in an order the world model can accept. Items are placed BEFORE spots are closed,
    # because `add_item` refuses a closed spot -- so seeding the other way round would make
    # "closed and occupied" impossible to express.
    state.declare_devices((device.identifier, device.spots) for device in declarations)
    for device in declarations:
        if device.state:
            state.replace_device_state(device=device.identifier, state=device.state)
    for location in occupied_locations:
        state.add_item(location)
    for device in declarations:
        for spot in device.closed_spots:
            state.lock_location(f"{device.identifier}.{spot}")

    summary = SeedSummary(
        devices=len(declarations),
        spots=sum(len(device.spots) for device in declarations),
        items=len(occupied_locations),
    )
    logger.info(
        "Loaded laboratory model seed from %s: %s devices, %s spots, %s items",
        file_path,
        summary.devices,
        summary.spots,
        summary.items,
    )
    return summary


@dataclass(frozen=True)
class _DeviceDeclaration:
    identifier: str
    spots: tuple[str, ...]
    state: dict[str, StateValue]
    closed_spots: tuple[str, ...]


def _parse_devices(raw: Any) -> list[_DeviceDeclaration]:
    # `devices` is required and is the topology: everything else in the file refers to it.
    if not isinstance(raw, list):
        raise ValueError("Seed file must contain a 'devices' list")

    declarations: list[_DeviceDeclaration] = []
    seen_devices: set[str] = set()
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise ValueError(f"Seed device at index {index} must be a mapping")

        identifier = entry.get("id")
        if not isinstance(identifier, str):
            raise ValueError(f"Seed device at index {index} is missing a string 'id'")
        # The same grammar the live API enforces, so a device that could never be addressed
        # cannot be declared either.
        try:
            validate_name(identifier, kind="device")
        except ValueError as error:
            raise ValueError(f"Seed device at index {index} has an invalid id: {error}") from error
        if identifier in seen_devices:
            raise ValueError(f"Seed device is duplicated: {identifier}")
        seen_devices.add(identifier)

        spots = _parse_spots(entry.get("spots"), device=identifier)
        declarations.append(
            _DeviceDeclaration(
                identifier=identifier,
                spots=spots,
                state=_parse_state(entry.get("state"), device=identifier),
                closed_spots=_parse_closed_spots(entry.get("closed_spots"), device=identifier, spots=spots),
            )
        )
    return declarations


def _parse_spots(raw: Any, *, device: str) -> tuple[str, ...]:
    # Written as labcode writes it: `spots: [deck, tube]`. A device with no spots is allowed --
    # something that only carries state and never holds an item is a legitimate thing to model.
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError(f"Seed device '{device}' has a non-list 'spots'")

    spots: list[str] = []
    for spot in raw:
        if not isinstance(spot, str):
            raise ValueError(f"Seed device '{device}' has a non-string spot name")
        try:
            validate_name(spot, kind="spot")
        except ValueError as error:
            raise ValueError(f"Seed device '{device}' has an invalid spot name: {error}") from error
        if spot in spots:
            raise ValueError(f"Seed device '{device}' declares spot '{spot}' more than once")
        spots.append(spot)
    return tuple(spots)


def _parse_state(raw: Any, *, device: str) -> dict[str, StateValue]:
    # Opaque to this loader as much as to the store: keys are checked for shape and values for
    # being scalars, and nothing looks at what they mean.
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"Seed device '{device}' has a non-mapping 'state'")

    parsed: dict[str, StateValue] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            raise ValueError(f"Seed device '{device}' has a non-string state key")
        try:
            validate_state_key(key)
        except ValueError as error:
            raise ValueError(f"Seed device '{device}' has an invalid state key: {error}") from error
        # Structured values are refused rather than stored: a nested value invites callers to
        # model meaning inside something nothing validates.
        if not isinstance(value, bool | int | float | str) and value is not None:
            raise ValueError(f"Seed device '{device}' state key '{key}' must be a scalar")
        parsed[key] = value
    return parsed


def _parse_closed_spots(raw: Any, *, device: str, spots: tuple[str, ...]) -> tuple[str, ...]:
    # Optional; the default is that every spot starts reachable.
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError(f"Seed device '{device}' has a non-list 'closed_spots'")

    closed: list[str] = []
    for spot in raw:
        if not isinstance(spot, str):
            raise ValueError(f"Seed device '{device}' has a non-string closed spot name")
        # Must be one of this device's own spots -- otherwise the file says something about a
        # place that does not exist, which is exactly the kind of mistake worth reporting.
        if spot not in spots:
            raise ValueError(f"Seed device '{device}' closes undeclared spot '{spot}'")
        if spot in closed:
            raise ValueError(f"Seed device '{device}' closes spot '{spot}' more than once")
        closed.append(spot)
    return tuple(closed)


def _parse_boundary_inputs(raw: Any) -> list[str]:
    """Pull the initial occupancy out of a labcode-shaped `boundary` section.

    Only `inputs` matters at t=0: outputs describe where objects end up. A port without a
    `spot` is Pure Data (labcode's term for a value with no physical object), so it contributes
    no occupancy and is skipped rather than rejected."""
    if raw is None:
        return []
    if not isinstance(raw, dict):
        raise ValueError("Seed file has a non-mapping 'boundary'")

    inputs = raw.get("inputs")
    if inputs is None:
        return []
    if not isinstance(inputs, dict):
        raise ValueError("Seed file has a non-mapping 'boundary.inputs'")

    locations: list[str] = []
    for port, entry in inputs.items():
        if not isinstance(entry, dict):
            raise ValueError(f"Seed boundary input '{port}' must be a mapping")
        location = entry.get("spot")
        if location is None:
            continue
        if not isinstance(location, str):
            raise ValueError(f"Seed boundary input '{port}' has a non-string 'spot'")
        try:
            validate_location(location)
        except ValueError as error:
            raise ValueError(f"Seed boundary input '{port}' has an invalid spot: {error}") from error
        # Two ports starting in one spot is not a state the world can hold; saying so here is
        # clearer than letting the second `add_item` fail with `destination_occupied`.
        if location in locations:
            raise ValueError(f"Seed boundary inputs place two objects at '{location}'")
        locations.append(location)
    return locations


def _check_declared(declarations: list[_DeviceDeclaration], locations: list[str]) -> None:
    # Cross-check the boundary against the topology before applying anything, so an input
    # naming a spot the file never declared is reported as a seed error rather than as an
    # `unknown_location` from deep inside the store.
    declared = {
        f"{device.identifier}.{spot}" for device in declarations for spot in device.spots
    }
    for location in locations:
        if location not in declared:
            raise ValueError(f"Seed boundary input names undeclared location '{location}'")
