"""FastAPI HTTP facade over the in-memory `LaboratoryModelState`.

This module wires the world model (`state.py`) to HTTP so the SiLA2 servers (and the sample
scripts) can read and mutate the shared world over the network. It owns four concerns: startup
seeding, error translation (domain errors -> stable JSON + status codes), the route handlers
that delegate to the single module-level `state` instance, and the two lifecycle operations.

The two lifecycle operations are deliberately different, and picking the wrong one is the easy
mistake to make here:

* `POST /reseed` rereads the seed file and rebuilds t=0 -- topology, occupancy, device state
  and closed spots. This is what a second run of a workflow wants.
* `POST /reset` empties the world but **keeps the declared topology**. Dropping the topology
  would leave every location unknown and nothing able to run, so a reset is a blank world, not
  an absent one.
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, NoReturn

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .models import (
    AddItemRequest,
    AddItemResponse,
    DeviceListResponse,
    DeviceStateKeyResponse,
    DeviceStateResponse,
    DeviceStateValueRequest,
    DeviceStateView,
    ErrorResponse,
    LocationControlRequest,
    LocationControlResponse,
    MoveItemRequest,
    MoveItemResponse,
    RemoveItemRequest,
    RemoveItemResponse,
    ReseedResponse,
    ResetResponse,
    SpotState,
    StateResponse,
    validate_location,
    validate_name,
    validate_state_key,
)
from .seed import load_seed
from .state import LaboratoryModelError, LaboratoryModelState

logger = logging.getLogger(__name__)
# One process-wide world instance, shared by every request (the store is thread-safe).
state = LaboratoryModelState()

# The seed file is named by the environment so compose can mount one and point at it.
SEED_FILE_VARIABLE = "LABORATORY_MODEL_SEED_FILE"

# Domain errors that are the caller's bad input rather than a state conflict, and those that
# mean "no such thing". Everything else is a 409: the world said no.
_BAD_REQUEST_CODES = frozenset(
    {"invalid_location", "invalid_device", "invalid_state_key", "same_source_and_destination"}
)
_NOT_FOUND_CODES = frozenset({"unknown_location", "unknown_device", "unknown_state_key"})


class LaboratoryModelAPIError(Exception):
    """Carrier that pairs an already-chosen HTTP status with a ready error payload, so a single
    exception handler can render it. Distinct from the domain `LaboratoryModelError` (which
    knows nothing about HTTP)."""

    # The payload is always the one-key envelope {"error": {code, message, details}}, so it is
    # typed as a nested mapping rather than an opaque object: the handler below reads through it.
    def __init__(self, status_code: int, payload: dict[str, dict[str, Any]]):
        super().__init__(payload["error"]["message"])
        self.status_code = status_code
        self.payload = payload


def raise_http_error(error: LaboratoryModelError) -> NoReturn:
    """Translate a domain error into an HTTP one.

    Declared NoReturn because it always raises -- that is what lets the callers below use it as
    the whole body of an `except` clause and still be seen to return a value."""
    if error.code in _BAD_REQUEST_CODES:
        status_code = 400
    elif error.code in _NOT_FOUND_CODES:
        status_code = 404
    else:
        status_code = 409
    raise LaboratoryModelAPIError(
        status_code=status_code,
        payload={"error": {"code": error.code, "message": error.message, "details": error.details}},
    )


def _raise_invalid(code: str, error: ValueError, details: dict[str, str | int | bool | None]) -> NoReturn:
    # Path parameters bypass the pydantic request models, so handlers validate them by hand and
    # funnel the resulting ValueError through the same envelope as everything else.
    raise_http_error(LaboratoryModelError(code, str(error), details))


def _seed_file() -> str | None:
    return os.getenv(SEED_FILE_VARIABLE)


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Seed the world from the file named by the environment. Unset => start with an empty
        # world (still reset, so a reused process begins clean). A configured-but-broken file is
        # left to raise: a server that came up with a world nobody asked for would be worse than
        # one that refused to start.
        file_path = _seed_file()
        if file_path:
            load_seed(state=state, file_path=file_path)
        else:
            logger.info("Starting laboratory model with no seed file configured")
            state.declare_devices(())
        yield

    app = FastAPI(
        title="Laboratory Model API",
        version="0.2.0",
        lifespan=lifespan,
        responses={
            400: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
        },
    )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Malformed request bodies/params: report as our error envelope with code
        # `invalid_request` rather than FastAPI's default 422 shape.
        logger.info("Rejected invalid request for path=%s", request.url.path)
        # jsonable_encoder is required, not cosmetic: when a field validator raises (as
        # `validate_location` does for a bad name) pydantic puts the original exception object
        # into the error's `ctx`, which JSON cannot serialise. Encoding first coerces it to a
        # string -- the same thing FastAPI's own default handler does -- so a bad location comes
        # back as a 400 instead of failing to render.
        details = jsonable_encoder(exc.errors())
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "code": "invalid_request",
                    "message": "The request body or parameters are invalid.",
                    "details": {"errors": details},
                }
            },
        )

    @app.exception_handler(LaboratoryModelAPIError)
    async def handle_api_error(request: Request, exc: LaboratoryModelAPIError) -> JSONResponse:
        # Render a translated domain error (from `raise_http_error`) as JSON.
        logger.info("Rejected request for path=%s with code=%s", request.url.path, exc.payload["error"]["code"])
        return JSONResponse(status_code=exc.status_code, content=exc.payload)

    @app.get("/health")
    def health() -> dict[str, str]:
        # Liveness probe used by compose/ops to tell the world model is up.
        return {"status": "healthy"}

    # --- Item mutations. Each catches the domain error and re-raises it as HTTP. ---

    @app.post("/items/add", response_model=AddItemResponse, status_code=201)
    def add_item(request: AddItemRequest) -> AddItemResponse:
        logger.info("Adding item at location=%s", request.location)
        try:
            state.add_item(request.location)
            # Return the full resulting spot state (occupancy + accessibility), so a caller
            # needs no follow-up read.
            location_state = state.get_location(request.location)
        except LaboratoryModelError as error:
            raise_http_error(error)
        return AddItemResponse(**location_state.model_dump())

    @app.post("/items/move", response_model=MoveItemResponse)
    def move_item(request: MoveItemRequest) -> MoveItemResponse:
        logger.info("Moving item from source=%s to destination=%s", request.source, request.destination)
        try:
            record = state.move_item(request.source, request.destination)
        except LaboratoryModelError as error:
            raise_http_error(error)
        return MoveItemResponse(
            source=request.source,
            destination=request.destination,
            moved=True,
            item_id=record.item_id,
        )

    @app.delete("/items/remove", response_model=RemoveItemResponse)
    def remove_item(request: RemoveItemRequest) -> RemoveItemResponse:
        logger.info("Removing item at location=%s", request.location)
        try:
            record = state.remove_item(request.location)
        except LaboratoryModelError as error:
            raise_http_error(error)
        return RemoveItemResponse(location=request.location, removed=True, item_id=record.item_id)

    # --- Accessibility control (a lid/door closing or opening, driven by servers). Per spot:
    # --- a device whose lid covers several spots locks each of them, because which spots a lid
    # --- covers is that instrument's business rather than the world model's. ---

    @app.post("/locations/lock", response_model=LocationControlResponse)
    def lock_location(request: LocationControlRequest) -> LocationControlResponse:
        logger.info("Locking location=%s", request.location)
        try:
            location_state = state.lock_location(request.location)
        except LaboratoryModelError as error:
            raise_http_error(error)
        return LocationControlResponse(location=location_state.location, accessible=location_state.accessible)

    @app.post("/locations/unlock", response_model=LocationControlResponse)
    def unlock_location(request: LocationControlRequest) -> LocationControlResponse:
        logger.info("Unlocking location=%s", request.location)
        try:
            location_state = state.unlock_location(request.location)
        except LaboratoryModelError as error:
            raise_http_error(error)
        return LocationControlResponse(location=location_state.location, accessible=location_state.accessible)

    # --- Reads. ---

    @app.get("/locations/{location}", response_model=SpotState)
    def get_location(location: str) -> SpotState:
        # Path param bypasses the request-model validators, so validate the name here (an
        # invalid name is a 400, a well-formed name for a place that does not exist a 404).
        try:
            validate_location(location)
        except ValueError as error:
            _raise_invalid("invalid_location", error, {"location": location})
        logger.info("Reading location=%s", location)
        try:
            return state.get_location(location)
        except LaboratoryModelError as error:
            raise_http_error(error)

    @app.get("/state", response_model=StateResponse)
    def get_state() -> StateResponse:
        # Whole-world snapshot for debugging and test assertions: every declared device, each
        # with its opaque state and its spots.
        logger.info("Reading complete laboratory state")
        return StateResponse(devices=state.snapshot())

    @app.get("/devices", response_model=DeviceListResponse)
    def list_devices() -> DeviceListResponse:
        return DeviceListResponse(devices=state.list_devices())

    @app.get("/devices/{device}", response_model=DeviceStateView)
    def get_device(device: str) -> DeviceStateView:
        try:
            validate_name(device, kind="device")
        except ValueError as error:
            _raise_invalid("invalid_device", error, {"device": device})
        try:
            return state.get_device(device)
        except LaboratoryModelError as error:
            raise_http_error(error)

    # --- Opaque device state. The store keeps these verbatim and no world rule reads them; a
    # --- key means whatever the server that wrote it decides it means. ---

    @app.get("/devices/{device}/state", response_model=DeviceStateResponse)
    def get_device_state(device: str) -> DeviceStateResponse:
        try:
            validate_name(device, kind="device")
        except ValueError as error:
            _raise_invalid("invalid_device", error, {"device": device})
        try:
            return DeviceStateResponse(device=device, state=state.get_device_state(device))
        except LaboratoryModelError as error:
            raise_http_error(error)

    @app.put("/devices/{device}/state/{key}", response_model=DeviceStateKeyResponse)
    def set_device_state(device: str, key: str, request: DeviceStateValueRequest) -> DeviceStateKeyResponse:
        try:
            validate_name(device, kind="device")
        except ValueError as error:
            _raise_invalid("invalid_device", error, {"device": device})
        try:
            validate_state_key(key)
        except ValueError as error:
            _raise_invalid("invalid_state_key", error, {"device": device, "key": key})
        logger.info("Setting state key=%s on device=%s", key, device)
        try:
            value = state.set_device_state(device=device, key=key, value=request.value)
        except LaboratoryModelError as error:
            raise_http_error(error)
        return DeviceStateKeyResponse(device=device, key=key, value=value)

    @app.delete("/devices/{device}/state/{key}", response_model=DeviceStateResponse)
    def unset_device_state(device: str, key: str) -> DeviceStateResponse:
        try:
            validate_name(device, kind="device")
        except ValueError as error:
            _raise_invalid("invalid_device", error, {"device": device})
        try:
            validate_state_key(key)
        except ValueError as error:
            _raise_invalid("invalid_state_key", error, {"device": device, "key": key})
        logger.info("Unsetting state key=%s on device=%s", key, device)
        try:
            state.unset_device_state(device=device, key=key)
            return DeviceStateResponse(device=device, state=state.get_device_state(device))
        except LaboratoryModelError as error:
            raise_http_error(error)

    # --- Lifecycle. See the module docstring for why these two are not the same thing. ---

    @app.post("/reset", response_model=ResetResponse)
    def reset() -> ResetResponse:
        # Empty every spot and clear every state bag, keeping the declared topology.
        logger.info("Resetting laboratory state")
        state.reset()
        return ResetResponse(cleared=True)

    @app.post("/reseed", response_model=ReseedResponse)
    def reseed() -> ReseedResponse:
        # Reread the seed file, so consecutive runs can each start from t=0 without restarting
        # the container. Rereading rather than replaying a startup snapshot is deliberate: the
        # file can be edited between runs and the next reseed should honour that.
        file_path = _seed_file()
        if not file_path:
            raise_http_error(
                LaboratoryModelError(
                    "seed_file_not_configured",
                    f"Cannot reseed because {SEED_FILE_VARIABLE} is not set.",
                    None,
                )
            )
        logger.info("Reseeding laboratory state from %s", file_path)
        # A file that has become unreadable or malformed since startup is the caller's problem
        # to fix, not a reason to take the service down, so it answers 400 rather than raising.
        try:
            summary = load_seed(state=state, file_path=file_path)
        except (OSError, ValueError) as error:
            raise_http_error(LaboratoryModelError("invalid_seed", str(error), {"file": file_path}))
        return ReseedResponse(
            reseeded=True,
            devices=summary.devices,
            spots=summary.spots,
            items=summary.items,
        )

    return app


# Module-level ASGI app object uvicorn imports (`app.main:app`).
app = create_app()
