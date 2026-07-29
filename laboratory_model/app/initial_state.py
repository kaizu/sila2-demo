"""Startup seeding of the world model from a JSON file.

`load_initial_state` is called once at server startup (see `main.py`) to populate the
initial "reality": which locations already hold an item and which start locked. The file
is a `{"locations": [{location, occupied?, accessible?}, ...]}` document. This is the
only source of initial contents -- the store is otherwise empty and never reloads the
file (a `/reset` clears back to empty rather than re-seeding).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .models import validate_location
from .state import LaboratoryModelState


logger = logging.getLogger(__name__)


def load_initial_state(*, state: LaboratoryModelState, file_path: str) -> None:
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"Initial state file does not exist: {file_path}")

    # Parse and require the top-level `locations` list up front.
    payload = json.loads(path.read_text(encoding="utf-8"))
    locations = payload.get("locations")
    if not isinstance(locations, list):
        raise ValueError("Initial state file must contain a 'locations' list")

    # Start from a clean world, then apply each entry. `seen_locations` catches a file
    # that lists the same location twice (which would otherwise seed it ambiguously).
    state.reset()
    seen_locations: set[str] = set()
    initialized_count = 0

    for index, entry in enumerate(locations):
        if not isinstance(entry, dict):
            raise ValueError(f"Initial state entry at index {index} must be an object")

        # Location is required and must pass the same grammar as the live API.
        raw_location = entry.get("location")
        if not isinstance(raw_location, str):
            raise ValueError(f"Initial state entry at index {index} is missing a string 'location'")
        location = validate_location(raw_location)
        if location in seen_locations:
            raise ValueError(f"Initial state location is duplicated: {location}")
        seen_locations.add(location)

        # `occupied` and `accessible` are optional; default to empty and accessible.
        occupied = _read_bool(entry=entry, key="occupied", default=False, index=index)
        accessible = _read_bool(entry=entry, key="accessible", default=True, index=index)

        # Place the item first (while the location is still accessible), THEN set the
        # accessibility. `add_item` requires an accessible location, so seeding in this
        # order is what lets a "locked and occupied" location be expressed: put the item
        # in, then lock it. Locking first would make the add raise `location_locked`.
        if occupied:
            state.add_item(location)

        if accessible is False:
            state.lock_location(location)
        else:
            state.unlock_location(location)

        initialized_count += 1

    logger.info("Loaded laboratory model initial state from %s with %s locations", file_path, initialized_count)


def _read_bool(*, entry: dict[str, Any], key: str, default: bool, index: int) -> bool:
    # Optional boolean field reader: absent => default, present-but-not-bool => error
    # (so a stray "true" string is rejected rather than silently coerced).
    value = entry.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"Initial state entry at index {index} has non-boolean '{key}'")
    return value
