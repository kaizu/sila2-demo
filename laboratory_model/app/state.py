from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from uuid import UUID, uuid4

from .models import LocationState


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
            return record

    def get_location(self, location: str) -> LocationState:
        with self._lock:
            record = self._items_by_location.get(location)
            if record is None:
                return LocationState(location=location, occupied=False, item_id=None)
            return LocationState(location=location, occupied=True, item_id=record.item_id)

    def snapshot(self) -> list[LocationState]:
        with self._lock:
            return [
                LocationState(location=location, occupied=True, item_id=record.item_id)
                for location, record in sorted(self._items_by_location.items())
            ]

    def reset(self) -> None:
        with self._lock:
            self._items_by_location.clear()
