"""Pydantic request/response schemas and the shared location-name rule.

These types are the HTTP contract of the laboratory-model API (see `main.py`). The
request models validate input at the edge; the response models shape what callers get
back. `validate_location` is the single place the location-string grammar is enforced,
reused by both the request models and the `GET /locations/{location}` path handler.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


def validate_location(location: str) -> str:
    """Normalise and validate a location string, or raise ValueError.

    Rules: non-empty, no surrounding whitespace, <=128 chars, and restricted to an
    ASCII whitelist (letters, digits, and `:`, `_`, `-`). Note the whitelist does NOT
    include `.`, so dotted labcode spot names (e.g. `dispenser.deck`) are rejected as-is
    -- a point the device-centric refactor will have to revisit."""
    normalized = location.strip()
    if not normalized:
        raise ValueError("location must not be empty")
    # Reject rather than silently trim, so callers cannot pass sloppy padded strings.
    if normalized != location:
        raise ValueError("location must not contain leading or trailing whitespace")
    if len(normalized) > 128:
        raise ValueError("location must be 128 characters or fewer")
    allowed_characters = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789:_-")
    if any(character not in allowed_characters for character in normalized):
        raise ValueError("location contains unsupported characters")
    return normalized


# --- Request bodies. Each runs `validate_location` on its location field(s) so a bad
#     name is rejected with a 422 before reaching the state layer. ---

class AddItemRequest(BaseModel):
    location: str = Field(..., description="Target location")

    @field_validator("location")
    @classmethod
    def _validate_location(cls, value: str) -> str:
        return validate_location(value)


class MoveItemRequest(BaseModel):
    source: str = Field(..., description="Source location")
    destination: str = Field(..., description="Destination location")

    @field_validator("source", "destination")
    @classmethod
    def _validate_location(cls, value: str) -> str:
        return validate_location(value)


class RemoveItemRequest(BaseModel):
    location: str = Field(..., description="Location to clear")

    @field_validator("location")
    @classmethod
    def _validate_location(cls, value: str) -> str:
        return validate_location(value)


class LocationControlRequest(BaseModel):
    location: str = Field(..., description="Location to lock or unlock")

    @field_validator("location")
    @classmethod
    def _validate_location(cls, value: str) -> str:
        return validate_location(value)


# --- Response bodies. `LocationState` is the canonical per-location view; the others
#     describe the outcome of a specific mutation. ---

class LocationState(BaseModel):
    # `from_attributes` lets FastAPI build this straight from the state layer's
    # `LocationState` dataclass-like object without a manual dict conversion.
    model_config = ConfigDict(from_attributes=True)

    location: str
    occupied: bool
    item_id: UUID | None
    accessible: bool


class AddItemResponse(LocationState):
    # An add returns the full resulting location state.
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
    # The whole-world snapshot (`GET /state`).
    locations: list[LocationState]


class ResetResponse(BaseModel):
    cleared: bool


class LocationControlResponse(BaseModel):
    location: str
    accessible: bool


# --- Error envelope. `LaboratoryModelError`s are rendered into this shape by the API
#     layer so every error response has a stable {code, message, details} body. ---

class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, str | int | bool | None] | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail
