from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


def validate_location(location: str) -> str:
    normalized = location.strip()
    if not normalized:
        raise ValueError("location must not be empty")
    if normalized != location:
        raise ValueError("location must not contain leading or trailing whitespace")
    if len(normalized) > 128:
        raise ValueError("location must be 128 characters or fewer")
    allowed_characters = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789:_-")
    if any(character not in allowed_characters for character in normalized):
        raise ValueError("location contains unsupported characters")
    return normalized


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


class LocationState(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    location: str
    occupied: bool
    item_id: UUID | None


class AddItemResponse(LocationState):
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
    locations: list[LocationState]


class ResetResponse(BaseModel):
    cleared: bool


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, str | int | bool | None] | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail
