"""In-memory world-state model shared by every mock SiLA2 server.

This is the "reality" the SiLA2 servers act on. It is organised around **devices**, each
holding a fixed set of **spots** (where an item can sit) plus an opaque bag of **state**. The
instrument servers push physical effects here (a lid opening makes a spot accessible; a Pick
removes an item) and gate their commands on it (a run requires an item present). It is a
simulator of the physical world, deliberately independent of any labcode workflow.

Four design points worth knowing:

* **The topology is declared, not discovered.** Which devices exist and which spots each one
  has comes from the seed (see `seed.py`) and does not grow at runtime. Addressing a device
  or spot that was never declared is an error, and that is the point: when a workflow asks to
  move a plate somewhere that does not physically exist, the mistake surfaces here instead of
  succeeding against a location conjured into being by the request itself.
* **`accessible` is a first-class, enforced property of a spot.** The store refuses to reach
  into a spot that is not accessible, which makes it the one piece of physical meaning this
  module owns. It is per spot rather than per device: a device whose lid covers several spots
  is expressed by its server locking each of them, which keeps the "what does a lid mean"
  judgement in the server where it belongs.
* **`state` is the opposite: completely opaque.** Keys and values are stored verbatim and are
  read by no rule in this file. `lid`, `door`, `up` and anything else are meaningful only to
  the server that wrote them. Nothing here may ever branch on a state key -- that separation
  is what keeps this a generic store rather than a second, competing model of each instrument.
* All state is one dict guarded by a single lock. Nothing is persisted: the seed is the only
  source of initial contents, `reset()` empties the world while keeping the topology, and
  re-seeding is `seed.py`'s job.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from threading import Lock
from uuid import UUID, uuid4

from .models import DeviceStateView, SpotState, StateValue, join_location, split_location

logger = logging.getLogger(__name__)


class LaboratoryModelError(Exception):
    """A world-rule violation (unknown location, occupied destination, locked spot, ...).

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


@dataclass
class _Spot:
    """Internal per-spot cell. `item_id is None` means empty; accessibility defaults to open,
    because a spot only becomes unreachable once something explicitly closes it."""

    item_id: UUID | None = None
    accessible: bool = True


@dataclass
class _Device:
    """Internal per-device record: its declared spots, and its opaque state bag."""

    spots: dict[str, _Spot] = field(default_factory=dict)
    state: dict[str, StateValue] = field(default_factory=dict)


class LaboratoryModelState:
    def __init__(self) -> None:
        # One lock serialises every mutation and read, so the servers (each on its own request
        # thread) see a consistent world.
        self._lock = Lock()
        self._devices: dict[str, _Device] = {}

    # --- Topology. Declared once per seed; never grows through ordinary use. ---

    def declare_devices(self, declarations: Iterable[tuple[str, Iterable[str]]]) -> None:
        """Replace the whole world with the given devices and their spots.

        Takes (device, spots) pairs rather than a mapping so the seed loader can report a
        duplicate device with the position it appeared at. Names are expected to have been
        validated by the caller; this method owns the structure, not the grammar."""
        with self._lock:
            devices: dict[str, _Device] = {}
            for device, spots in declarations:
                # A device declared twice would silently lose the earlier spot set, so the
                # store refuses instead of picking a winner.
                if device in devices:
                    raise LaboratoryModelError(
                        "duplicate_device",
                        "A device is declared more than once.",
                        {"device": device},
                    )
                record = _Device()
                for spot in spots:
                    if spot in record.spots:
                        raise LaboratoryModelError(
                            "duplicate_spot",
                            "A spot is declared more than once on the same device.",
                            {"device": device, "spot": spot},
                        )
                    record.spots[spot] = _Spot()
                devices[device] = record
            # Swap in only once every declaration validated, so a bad declaration cannot
            # leave the world half-built.
            self._devices = devices

    def list_devices(self) -> list[str]:
        with self._lock:
            return sorted(self._devices)

    # --- Internal lookups. All callers below hold the lock. ---

    def _require_device(self, device: str) -> _Device:
        record = self._devices.get(device)
        if record is None:
            raise LaboratoryModelError(
                "unknown_device",
                "No such device is declared.",
                {"device": device},
            )
        return record

    def _require_spot(self, location: str) -> _Spot:
        """Resolve a location to its spot, or raise `unknown_location`.

        An undeclared device and an undeclared spot collapse into one code on purpose: from a
        caller's point of view both mean "that place does not exist", and the location it
        asked for is in the details either way."""
        device, spot = split_location(location)
        device_record = self._devices.get(device)
        cell = None if device_record is None else device_record.spots.get(spot)
        if cell is None:
            raise LaboratoryModelError(
                "unknown_location",
                "No such location is declared.",
                {"location": location},
            )
        return cell

    def _require_accessible(self, *, location: str, cell: _Spot, error_code: str, error_message: str) -> None:
        # Guard used before any operation that physically reaches into a spot.
        if cell.accessible is False:
            raise LaboratoryModelError(error_code, error_message, {"location": location})

    def _spot_state(self, location: str, cell: _Spot) -> SpotState:
        device, spot = split_location(location)
        return SpotState(
            device=device,
            spot=spot,
            location=location,
            occupied=cell.item_id is not None,
            item_id=cell.item_id,
            accessible=cell.accessible,
        )

    # --- Item mutations. ---

    def add_item(self, location: str) -> ItemRecord:
        with self._lock:
            cell = self._require_spot(location)
            # Cannot place into a closed spot, nor onto an already-occupied one.
            self._require_accessible(
                location=location,
                cell=cell,
                error_code="location_locked",
                error_message="The requested location is locked.",
            )
            if cell.item_id is not None:
                raise LaboratoryModelError(
                    "destination_occupied",
                    "An item already exists at the requested location.",
                    {"location": location},
                )

            # Mint a fresh identity for the new item. This id is the world model's own
            # occupancy token; it is unrelated to any identifier a workflow may carry.
            cell.item_id = uuid4()
            return ItemRecord(item_id=cell.item_id, location=location)

    def move_item(self, source: str, destination: str) -> ItemRecord:
        with self._lock:
            # A move must actually go somewhere.
            if source == destination:
                raise LaboratoryModelError(
                    "same_source_and_destination",
                    "Source and destination must be different.",
                    {"source": source, "destination": destination},
                )
            # Both ends must exist before anything else is considered: "there is no such
            # place" is a different class of mistake from "the place is busy or closed", and
            # reporting it first is what makes a typo in a location name obvious.
            source_cell = self._require_spot(source)
            destination_cell = self._require_spot(destination)
            # Then both ends must be reachable, before any occupancy is looked at.
            self._require_accessible(
                location=source,
                cell=source_cell,
                error_code="source_locked",
                error_message="The source location is locked.",
            )
            self._require_accessible(
                location=destination,
                cell=destination_cell,
                error_code="destination_locked",
                error_message="The destination location is locked.",
            )
            # Finally the source must hold an item and the destination must be free.
            if source_cell.item_id is None:
                raise LaboratoryModelError(
                    "source_empty",
                    "No item exists at the source location.",
                    {"source": source},
                )
            if destination_cell.item_id is not None:
                raise LaboratoryModelError(
                    "destination_occupied",
                    "An item already exists at the destination location.",
                    {"destination": destination},
                )

            # Carry the same identity across, which is what makes tracking one plate through a
            # workflow meaningful.
            item_id = source_cell.item_id
            source_cell.item_id = None
            destination_cell.item_id = item_id
            return ItemRecord(item_id=item_id, location=destination)

    def remove_item(self, location: str) -> ItemRecord:
        with self._lock:
            cell = self._require_spot(location)
            # Cannot reach into a closed spot; there must be something to remove.
            self._require_accessible(
                location=location,
                cell=cell,
                error_code="location_locked",
                error_message="The requested location is locked.",
            )
            if cell.item_id is None:
                raise LaboratoryModelError(
                    "source_empty",
                    "No item exists at the requested location.",
                    {"location": location},
                )
            item_id = cell.item_id
            cell.item_id = None
            return ItemRecord(item_id=item_id, location=location)

    # --- Accessibility. Driven by the servers' door/lid commands. ---

    def lock_location(self, location: str) -> SpotState:
        # Make a spot unreachable (e.g. a lid closing). Idempotent: locking an already-locked
        # spot is a no-op beyond a log line. Any item stays in place, because "occupied and
        # unreachable" is exactly what a closed instrument holding a plate is.
        with self._lock:
            cell = self._require_spot(location)
            if cell.accessible is False:
                logger.info("Location %s is already locked", location)
            cell.accessible = False
            return self._spot_state(location, cell)

    def unlock_location(self, location: str) -> SpotState:
        # Inverse of lock_location (e.g. a lid opening). Also idempotent.
        with self._lock:
            cell = self._require_spot(location)
            if cell.accessible is True:
                logger.info("Location %s is already unlocked", location)
            cell.accessible = True
            return self._spot_state(location, cell)

    # --- Opaque device state. No rule in this module reads any of it. ---

    def set_device_state(self, *, device: str, key: str, value: StateValue) -> StateValue:
        with self._lock:
            record = self._require_device(device)
            record.state[key] = value
            return value

    def unset_device_state(self, *, device: str, key: str) -> None:
        with self._lock:
            record = self._require_device(device)
            # Absent is the same as never-set for an opaque bag, so removing a key that is not
            # there is refused rather than silently accepted: it means the caller believed
            # something about the world that is not so.
            if key not in record.state:
                raise LaboratoryModelError(
                    "unknown_state_key",
                    "No such state key is set on this device.",
                    {"device": device, "key": key},
                )
            del record.state[key]

    def get_device_state(self, device: str) -> dict[str, StateValue]:
        with self._lock:
            record = self._require_device(device)
            # A copy, so a caller cannot mutate the world by holding on to the result.
            return dict(record.state)

    def replace_device_state(self, *, device: str, state: Mapping[str, StateValue]) -> None:
        """Set a device's whole state bag at once. Used by the seed loader, which knows the
        complete t=0 state and should not have to clear and re-add key by key."""
        with self._lock:
            record = self._require_device(device)
            record.state = dict(state)

    # --- Reads. ---

    def get_location(self, location: str) -> SpotState:
        with self._lock:
            cell = self._require_spot(location)
            return self._spot_state(location, cell)

    def get_device(self, device: str) -> DeviceStateView:
        with self._lock:
            record = self._require_device(device)
            return self._device_view(device, record)

    def _device_view(self, device: str, record: _Device) -> DeviceStateView:
        # Spots are sorted so the view is stable to assert on; the device's own state is
        # copied for the same reason as in `get_device_state`.
        return DeviceStateView(
            device=device,
            state=dict(record.state),
            spots=[
                self._spot_state(join_location(device, spot), record.spots[spot]) for spot in sorted(record.spots)
            ],
        )

    def snapshot(self) -> list[DeviceStateView]:
        # Full world view for debugging and assertions. Every declared device appears, sorted:
        # with the topology declared there is no "untouched and therefore absent" case left to
        # reason about, so a snapshot is the whole world rather than a sparse subset of it.
        with self._lock:
            return [self._device_view(device, self._devices[device]) for device in sorted(self._devices)]

    # --- Lifecycle. ---

    def reset(self) -> None:
        """Empty the world while keeping the declared topology.

        Every spot becomes empty and accessible and every device's state bag is cleared, but
        the devices and their spots remain. Keeping the topology is what makes this usable as a
        between-tests wipe: dropping it would leave every location unknown and nothing able to
        run. Note this does NOT restore the seed's contents -- that is `POST /reseed`."""
        with self._lock:
            for record in self._devices.values():
                record.state.clear()
                for spot in record.spots.values():
                    spot.item_id = None
                    spot.accessible = True
