"""In-memory world-state model shared by every mock SiLA2 server.

This is the "reality" the SiLA2 servers act on: it tracks, per location, whether an
item is present and whether the location is accessible. The instrument servers push
physical effects here (e.g. a lid opening makes a location accessible; a Pick removes
an item) and gate their commands on it (e.g. a run requires an item present). It is a
simulator of the physical world, deliberately independent of any labcode workflow.

Two design points worth knowing:

* The location universe is **not pre-declared**. Locations are plain strings that spring
  into existence on first use; an unseen location reads as empty and accessible. So this
  store never needs a schema of "which locations exist".
* All state is a pair of in-memory dicts guarded by a single lock. Nothing is persisted:
  startup seeding (see `initial_state.py`) is the only source of initial contents, and
  `reset()` clears back to empty rather than reloading.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from threading import Lock
from uuid import UUID, uuid4

from .models import LocationState


logger = logging.getLogger(__name__)


class LaboratoryModelError(Exception):
    """A world-rule violation (occupied destination, locked location, empty source, ...).

    Carries a stable `code` (mapped to an HTTP status by the API layer) plus a
    human-readable `message` and optional structured `details` for the caller."""

    def __init__(self, code: str, message: str, details: dict[str, str | int | bool | None] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


@dataclass(frozen=True)
class ItemRecord:
    """One item and where it currently sits. Immutable: a move produces a new record
    (same `item_id`, new `location`) rather than mutating in place."""

    item_id: UUID
    location: str


class LaboratoryModelState:
    def __init__(self) -> None:
        # One lock serialises every mutation/read, so the servers (each on its own
        # request thread) see a consistent world. `_items_by_location` holds only
        # occupied locations; `_accessibility_by_location` holds only locations whose
        # accessibility has been touched -- both are sparse over the dynamic universe.
        self._lock = Lock()
        self._items_by_location: dict[str, ItemRecord] = {}
        self._accessibility_by_location: dict[str, bool] = {}

    def _get_accessibility(self, location: str) -> bool:
        # Unknown / untouched locations default to accessible: a location only becomes
        # inaccessible once something (a lid/door close) explicitly locks it.
        return self._accessibility_by_location.get(location, True)

    def _require_accessible(self, *, location: str, error_code: str, error_message: str) -> None:
        # Guard used before any operation that physically reaches into a location.
        if self._get_accessibility(location) is False:
            raise LaboratoryModelError(
                error_code,
                error_message,
                {"location": location},
            )

    def add_item(self, location: str) -> ItemRecord:
        with self._lock:
            # Cannot place into a locked location, nor onto an already-occupied one.
            self._require_accessible(
                location=location,
                error_code="location_locked",
                error_message="The requested location is locked.",
            )
            if location in self._items_by_location:
                raise LaboratoryModelError(
                    "destination_occupied",
                    "An item already exists at the requested location.",
                    {"location": location},
                )

            # Mint a fresh identity for the new item. This id is the world model's own
            # occupancy token; it is unrelated to any identifier a workflow may carry.
            record = ItemRecord(item_id=uuid4(), location=location)
            self._items_by_location[location] = record
            # Register the location's default accessibility so it shows up in snapshots.
            self._accessibility_by_location.setdefault(location, True)
            return record

    def move_item(self, source: str, destination: str) -> ItemRecord:
        with self._lock:
            # A move must actually go somewhere.
            if source == destination:
                raise LaboratoryModelError(
                    "same_source_and_destination",
                    "Source and destination must be different.",
                    {"source": source, "destination": destination},
                )
            # Both ends must be reachable before we touch anything.
            self._require_accessible(
                location=source,
                error_code="source_locked",
                error_message="The source location is locked.",
            )
            self._require_accessible(
                location=destination,
                error_code="destination_locked",
                error_message="The destination location is locked.",
            )
            # The source must hold an item and the destination must be free.
            record = self._items_by_location.get(source)
            if record is None:
                raise LaboratoryModelError(
                    "source_empty",
                    "No item exists at the source location.",
                    {"source": source},
                )
            if destination in self._items_by_location:
                raise LaboratoryModelError(
                    "destination_occupied",
                    "An item already exists at the destination location.",
                    {"destination": destination},
                )

            # Carry the same identity across: delete at source, recreate at destination.
            moved = ItemRecord(item_id=record.item_id, location=destination)
            del self._items_by_location[source]
            self._items_by_location[destination] = moved
            self._accessibility_by_location.setdefault(source, True)
            self._accessibility_by_location.setdefault(destination, True)
            return moved

    def remove_item(self, location: str) -> ItemRecord:
        with self._lock:
            # Cannot reach into a locked location; there must be something to remove.
            self._require_accessible(
                location=location,
                error_code="location_locked",
                error_message="The requested location is locked.",
            )
            record = self._items_by_location.get(location)
            if record is None:
                raise LaboratoryModelError(
                    "source_empty",
                    "No item exists at the requested location.",
                    {"location": location},
                )
            del self._items_by_location[location]
            self._accessibility_by_location.setdefault(location, True)
            return record

    def get_location(self, location: str) -> LocationState:
        # Read-only view of one location. Absent from the items dict => empty (but still
        # reports its accessibility, which defaults to True for an untouched location).
        with self._lock:
            record = self._items_by_location.get(location)
            if record is None:
                return LocationState(
                    location=location,
                    occupied=False,
                    item_id=None,
                    accessible=self._get_accessibility(location),
                )
            return LocationState(
                location=location,
                occupied=True,
                item_id=record.item_id,
                accessible=self._get_accessibility(location),
            )

    def lock_location(self, location: str) -> LocationState:
        # Make a location inaccessible (e.g. a lid/door closing). Idempotent: locking an
        # already-locked location is a no-op beyond a log line. Any item stays in place.
        with self._lock:
            if self._get_accessibility(location) is False:
                logger.info("Location %s is already locked", location)
            self._accessibility_by_location[location] = False
            record = self._items_by_location.get(location)
            return LocationState(
                location=location,
                occupied=record is not None,
                item_id=record.item_id if record is not None else None,
                accessible=False,
            )

    def unlock_location(self, location: str) -> LocationState:
        # Inverse of lock_location (e.g. a lid/door opening). Also idempotent.
        with self._lock:
            if self._get_accessibility(location) is True:
                logger.info("Location %s is already unlocked", location)
            self._accessibility_by_location[location] = True
            record = self._items_by_location.get(location)
            return LocationState(
                location=location,
                occupied=record is not None,
                item_id=record.item_id if record is not None else None,
                accessible=True,
            )

    def snapshot(self) -> list[LocationState]:
        # Full world view for debugging / assertions: every location that is either
        # occupied or has had its accessibility set, sorted for stable output.
        with self._lock:
            all_locations = sorted(set(self._items_by_location) | set(self._accessibility_by_location))
            return [
                LocationState(
                    location=location,
                    occupied=location in self._items_by_location,
                    item_id=self._items_by_location[location].item_id if location in self._items_by_location else None,
                    accessible=self._get_accessibility(location),
                )
                for location in all_locations
            ]

    def reset(self) -> None:
        # Clear the world back to empty. Note this does NOT reload the startup seed file;
        # re-seeding after a reset is the caller's responsibility.
        with self._lock:
            self._items_by_location.clear()
            self._accessibility_by_location.clear()
