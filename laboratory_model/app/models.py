"""Pydantic request/response schemas and the name grammar the whole API shares.

These types are the HTTP contract of the laboratory-model API (see `main.py`). The request
models validate input at the edge; the response models shape what callers get back.

The name rules live here because they are the one thing every layer has to agree on. A
location is always `device.spot` -- there is no such thing as a bare device name standing in
for "its only spot", because an implicit-spot special case would then have to be understood
by the store, the API, the seed loader, the servers and every test. Splitting is therefore
total: `validate_location` accepts exactly one dot with a valid name on each side, and
`split_location` can never fail on a string that passed it.

A consequence worth knowing: the previous generation of names (`centrifuge:1`) has no dot, so
it is *rejected* rather than quietly reinterpreted. Any place that was missed during the
rename fails loudly instead of addressing something unintended.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Opaque device state values (see `state.py`). Deliberately scalars only: the store never
# interprets these, and allowing nested structures would invite callers to model meaning
# inside a value that nothing validates. `bool` precedes `int` so pydantic keeps `true` a
# boolean rather than coercing it to 1.
StateValue = bool | int | float | str | None

# Names are restricted to an ASCII whitelist. `.` is NOT in it: the dot is the separator
# between the two halves of a location, so it may not appear inside either half.
_NAME_CHARACTERS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789:_-")
# State keys are addressed in a URL path segment, so they keep an even narrower set.
_STATE_KEY_CHARACTERS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")

MAX_LOCATION_LENGTH = 128
MAX_STATE_KEY_LENGTH = 64


def validate_name(value: str, *, kind: str) -> str:
    """Shared rule for a device name and a spot name: non-empty, unpadded, whitelisted.

    Public because the seed loader validates the two halves separately -- it reads them as
    separate fields (`id` and `spots`) rather than as one joined location."""
    if not value:
        raise ValueError(f"{kind} must not be empty")
    # Reject padding rather than trimming it, so a caller cannot address one name while
    # believing it passed another.
    if value != value.strip():
        raise ValueError(f"{kind} must not contain leading or trailing whitespace")
    if any(character not in _NAME_CHARACTERS for character in value):
        raise ValueError(f"{kind} contains unsupported characters")
    return value


def validate_location(location: str) -> str:
    """Normalise and validate a `device.spot` location string, or raise ValueError."""
    if len(location) > MAX_LOCATION_LENGTH:
        raise ValueError(f"location must be {MAX_LOCATION_LENGTH} characters or fewer")
    # Exactly one dot. Counting rather than splitting-and-checking gives the caller a
    # message that names the actual problem (none vs. several).
    dot_count = location.count(".")
    if dot_count != 1:
        raise ValueError("location must be of the form 'device.spot' with exactly one dot")

    device, spot = location.split(".", 1)
    validate_name(device, kind="device")
    validate_name(spot, kind="spot")
    return location


def split_location(location: str) -> tuple[str, str]:
    """Split a location that has already passed `validate_location` into (device, spot).

    Total by construction -- validation guarantees exactly one dot -- so callers need no
    error handling here."""
    device, spot = location.split(".", 1)
    return device, spot


def join_location(device: str, spot: str) -> str:
    """Build a location from its halves. The inverse of `split_location`, kept next to it so
    the separator is written down in exactly one place."""
    return f"{device}.{spot}"


def validate_state_key(key: str) -> str:
    """Validate a device-state key. The key is opaque to the store, but it travels in a URL
    path segment, so its shape is still constrained."""
    if not key:
        raise ValueError("state key must not be empty")
    if len(key) > MAX_STATE_KEY_LENGTH:
        raise ValueError(f"state key must be {MAX_STATE_KEY_LENGTH} characters or fewer")
    if any(character not in _STATE_KEY_CHARACTERS for character in key):
        raise ValueError("state key contains unsupported characters")
    return key


# --- Request bodies. Each runs `validate_location` on its location field(s) so a bad name
#     is rejected with a 400 before reaching the state layer. ---


class AddItemRequest(BaseModel):
    location: str = Field(..., description="Target location, as device.spot")

    @field_validator("location")
    @classmethod
    def _validate_location(cls, value: str) -> str:
        return validate_location(value)


class MoveItemRequest(BaseModel):
    source: str = Field(..., description="Source location, as device.spot")
    destination: str = Field(..., description="Destination location, as device.spot")

    @field_validator("source", "destination")
    @classmethod
    def _validate_location(cls, value: str) -> str:
        return validate_location(value)


class RemoveItemRequest(BaseModel):
    location: str = Field(..., description="Location to clear, as device.spot")

    @field_validator("location")
    @classmethod
    def _validate_location(cls, value: str) -> str:
        return validate_location(value)


class LocationControlRequest(BaseModel):
    location: str = Field(..., description="Location to lock or unlock, as device.spot")

    @field_validator("location")
    @classmethod
    def _validate_location(cls, value: str) -> str:
        return validate_location(value)


class DeviceStateValueRequest(BaseModel):
    # Wrapped in an object rather than sent bare so a future field (a comment, a timestamp)
    # can be added without changing the shape of what is already there.
    value: StateValue = Field(..., description="Opaque scalar the store keeps verbatim")


# --- Response bodies. `SpotState` is the canonical per-spot view and `DeviceStateView` the
#     canonical per-device one; the rest describe the outcome of a specific mutation. ---


class SpotState(BaseModel):
    # `from_attributes` lets FastAPI build this straight from the state layer's own
    # dataclass-like objects without a manual dict conversion.
    model_config = ConfigDict(from_attributes=True)

    device: str
    spot: str
    # The joined name is included as well as its halves so a caller can assert on one string
    # instead of reassembling it, and so responses round-trip into the request bodies above.
    location: str
    occupied: bool
    item_id: UUID | None
    accessible: bool


class DeviceStateView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    device: str
    # Opaque key-value state. The store never reads these; only the server that wrote a key
    # knows what it means.
    state: dict[str, StateValue]
    spots: list[SpotState]


class AddItemResponse(SpotState):
    # An add returns the full resulting spot state.
    pass


class MoveItemResponse(BaseModel):
    source: str
    destination: str
    moved: bool
    item_id: UUID


class RemoveItemResponse(BaseModel):
    location: str
    removed: bool
    item_id: UUID


class StateResponse(BaseModel):
    # The whole-world snapshot (`GET /state`). Every declared device appears, whether or not
    # anything has touched it -- with a declared topology there is nothing sparse to report.
    devices: list[DeviceStateView]


class DeviceListResponse(BaseModel):
    devices: list[str]


class DeviceStateResponse(BaseModel):
    device: str
    state: dict[str, StateValue]


class DeviceStateKeyResponse(BaseModel):
    device: str
    key: str
    value: StateValue


class LocationControlResponse(BaseModel):
    location: str
    accessible: bool


class ResetResponse(BaseModel):
    cleared: bool


class ReseedResponse(BaseModel):
    # Counts rather than the whole world: enough to confirm at a glance that a reseed read
    # the file it was meant to, without duplicating `GET /state`.
    reseeded: bool
    devices: int
    spots: int
    items: int


# --- Error envelope. `LaboratoryModelError`s are rendered into this shape by the API layer
#     so every error response has a stable {code, message, details} body. ---


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, str | int | bool | None] | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail
