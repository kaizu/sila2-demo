"""FastAPI HTTP facade over the in-memory `LaboratoryModelState`.

This module wires the world model (`state.py`) to HTTP so the SiLA2 servers (and test
scripts) can read and mutate the shared world over the network. It owns three concerns:
startup seeding, error translation (domain errors -> stable JSON + status codes), and
the route handlers that delegate to the single module-level `state` instance.
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .initial_state import load_initial_state
from .models import (
    AddItemRequest,
    AddItemResponse,
    ErrorResponse,
    LocationControlRequest,
    LocationControlResponse,
    LocationState,
    MoveItemRequest,
    MoveItemResponse,
    RemoveItemRequest,
    RemoveItemResponse,
    ResetResponse,
    StateResponse,
    validate_location,
)
from .state import LaboratoryModelError, LaboratoryModelState


logger = logging.getLogger(__name__)
# One process-wide world instance, shared by every request (the store is thread-safe).
state = LaboratoryModelState()


class LaboratoryModelAPIError(Exception):
    """Carrier that pairs an already-chosen HTTP status with a ready error payload, so a
    single exception handler can render it. Distinct from the domain `LaboratoryModelError`
    (which knows nothing about HTTP)."""

    def __init__(self, status_code: int, payload: dict[str, object]):
        super().__init__(payload["error"]["message"])
        self.status_code = status_code
        self.payload = payload


def raise_http_error(error: LaboratoryModelError) -> None:
    """Translate a domain error into an HTTP one. Bad input (invalid name, degenerate
    move) is a 400; every other world-rule violation (occupied/empty/locked) is a 409
    conflict."""
    status_code = 409
    if error.code in {"invalid_location", "same_source_and_destination"}:
        status_code = 400
    raise LaboratoryModelAPIError(
        status_code=status_code,
        payload={"error": {"code": error.code, "message": error.message, "details": error.details}},
    )


def create_app() -> FastAPI:
    app = FastAPI(
        title="Laboratory Model API",
        version="0.1.0",
        responses={
            400: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
        },
    )

    @app.on_event("startup")
    async def initialize_state_from_file() -> None:
        # Seed the world from the file named by LABORATORY_MODEL_INITIAL_STATE_FILE.
        # Unset => start empty (still reset, so a reused process begins clean).
        file_path = os.getenv("LABORATORY_MODEL_INITIAL_STATE_FILE")
        if not file_path:
            logger.info("Starting laboratory model with empty initial state")
            state.reset()
            return

        load_initial_state(state=state, file_path=file_path)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Malformed request bodies/params: report as our error envelope with code
        # `invalid_request` rather than FastAPI's default 422 shape.
        logger.info("Rejected invalid request for path=%s", request.url.path)
        # jsonable_encoder is required, not cosmetic: when a field validator raises (as
        # `validate_location` does for a bad name) pydantic puts the original exception
        # object into the error's `ctx`, which JSON cannot serialise. Encoding first
        # coerces it to a string -- the same thing FastAPI's own default handler does --
        # so a bad location comes back as a 400 instead of failing to render.
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
            record = state.add_item(request.location)
        except LaboratoryModelError as error:
            raise_http_error(error)
        # Return the full resulting location state (occupancy + accessibility).
        location_state = state.get_location(record.location)
        return AddItemResponse(**location_state.model_dump())

    @app.post("/items/move", response_model=MoveItemResponse)
    def move_item(request: MoveItemRequest) -> MoveItemResponse:
        logger.info("Moving item from source=%s to destination=%s", request.source, request.destination)
        try:
            record = state.move_item(request.source, request.destination)
        except LaboratoryModelError as error:
            raise_http_error(error)
        return MoveItemResponse(source=request.source, destination=request.destination, moved=True, item_id=record.item_id)

    @app.delete("/items/remove", response_model=RemoveItemResponse)
    def remove_item(request: RemoveItemRequest) -> RemoveItemResponse:
        logger.info("Removing item at location=%s", request.location)
        try:
            record = state.remove_item(request.location)
        except LaboratoryModelError as error:
            raise_http_error(error)
        return RemoveItemResponse(location=request.location, removed=True, item_id=record.item_id)

    # --- Accessibility control (a lid/door closing or opening, driven by servers). ---

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

    @app.get("/locations/{location}", response_model=LocationState)
    def get_location(location: str) -> LocationState:
        # Path param bypasses the request-model validators, so validate the name here
        # (an invalid name becomes a 400 via `invalid_location`).
        try:
            location = validate_location(location)
            logger.info("Reading location=%s", location)
            return state.get_location(location)
        except ValueError as error:
            raise_http_error(
                LaboratoryModelError(
                    "invalid_location",
                    str(error),
                    {"location": location},
                )
            )
        except LaboratoryModelError as error:
            raise_http_error(error)

    @app.get("/state", response_model=StateResponse)
    def get_state() -> StateResponse:
        # Whole-world snapshot for debugging and test assertions.
        logger.info("Reading complete laboratory state")
        return StateResponse(locations=state.snapshot())

    @app.post("/reset", response_model=ResetResponse)
    def reset() -> ResetResponse:
        # Clear the world to empty. Does NOT re-seed from the startup file (see state.reset).
        logger.info("Resetting laboratory state")
        state.reset()
        return ResetResponse(cleared=True)

    return app


# Module-level ASGI app object uvicorn imports (`app.main:app`).
app = create_app()
