from __future__ import annotations

from dataclasses import dataclass
import logging
from threading import Lock
from uuid import UUID, uuid4

from .models import LocationState


logger = logging.getLogger(__name__)


class LaboratoryModelError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, str | int | bool | None] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


@dataclass(frozen=True)
class ItemRecord:
    item_id: UUID
    location: str


class LaboratoryModelState:
    def __init__(self) -> None:
        self._lock = Lock()
        self._items_by_location: dict[str, ItemRecord] = {}
        self._accessibility_by_location: dict[str, bool] = {}

    def _get_accessibility(self, location: str) -> bool:
        return self._accessibility_by_location.get(location, True)

    def add_item(self, location: str) -> ItemRecord:
        with self._lock:
            if location in self._items_by_location:
                raise LaboratoryModelError(
                    "destination_occupied",
                    "An item already exists at the requested location.",
                    {"location": location},
                )

            record = ItemRecord(item_id=uuid4(), location=location)
            self._items_by_location[location] = record
            self._accessibility_by_location.setdefault(location, True)
            return record

    def move_item(self, source: str, destination: str) -> ItemRecord:
        with self._lock:
            if source == destination:
                raise LaboratoryModelError(
                    "same_source_and_destination",
                    "Source and destination must be different.",
                    {"source": source, "destination": destination},
                )
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

            moved = ItemRecord(item_id=record.item_id, location=destination)
            del self._items_by_location[source]
            self._items_by_location[destination] = moved
            self._accessibility_by_location.setdefault(source, True)
            self._accessibility_by_location.setdefault(destination, True)
            return moved

    def remove_item(self, location: str) -> ItemRecord:
        with self._lock:
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
        with self._lock:
            self._items_by_location.clear()
            self._accessibility_by_location.clear()
