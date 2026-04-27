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

    payload = json.loads(path.read_text(encoding="utf-8"))
    locations = payload.get("locations")
    if not isinstance(locations, list):
        raise ValueError("Initial state file must contain a 'locations' list")

    state.reset()
    seen_locations: set[str] = set()
    initialized_count = 0

    for index, entry in enumerate(locations):
        if not isinstance(entry, dict):
            raise ValueError(f"Initial state entry at index {index} must be an object")

        raw_location = entry.get("location")
        if not isinstance(raw_location, str):
            raise ValueError(f"Initial state entry at index {index} is missing a string 'location'")
        location = validate_location(raw_location)
        if location in seen_locations:
            raise ValueError(f"Initial state location is duplicated: {location}")
        seen_locations.add(location)

        occupied = _read_bool(entry=entry, key="occupied", default=False, index=index)
        accessible = _read_bool(entry=entry, key="accessible", default=True, index=index)

        if accessible is False:
            state.lock_location(location)
        else:
            state.unlock_location(location)

        if occupied:
            state.add_item(location)

        initialized_count += 1

    logger.info("Loaded laboratory model initial state from %s with %s locations", file_path, initialized_count)


def _read_bool(*, entry: dict[str, Any], key: str, default: bool, index: int) -> bool:
    value = entry.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"Initial state entry at index {index} has non-boolean '{key}'")
    return value
