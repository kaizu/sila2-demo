from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .models import (
    AddItemRequest,
    AddItemResponse,
    ErrorResponse,
    LocationState,
    MoveItemRequest,
    MoveItemResponse,
    RemoveItemRequest,
    RemoveItemResponse,
    ResetResponse,
    StateResponse,
    validate_location,
)
from .state import LaboratoryStatusError, LaboratoryStatusState


logger = logging.getLogger(__name__)
state = LaboratoryStatusState()


class LaboratoryStatusAPIError(Exception):
    def __init__(self, status_code: int, payload: dict[str, object]):
        super().__init__(payload["error"]["message"])
        self.status_code = status_code
        self.payload = payload


def raise_http_error(error: LaboratoryStatusError) -> None:
    status_code = 409
    if error.code in {"invalid_location", "same_source_and_destination"}:
        status_code = 400
    raise LaboratoryStatusAPIError(
        status_code=status_code,
        payload={"error": {"code": error.code, "message": error.message, "details": error.details}},
    )


def create_app() -> FastAPI:
    app = FastAPI(
        title="Laboratory Status API",
        version="0.1.0",
        responses={
            400: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
        },
    )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        logger.info("Rejected invalid request for path=%s", request.url.path)
        details = exc.errors()
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

    @app.exception_handler(LaboratoryStatusAPIError)
    async def handle_api_error(request: Request, exc: LaboratoryStatusAPIError) -> JSONResponse:
        logger.info("Rejected request for path=%s with code=%s", request.url.path, exc.payload["error"]["code"])
        return JSONResponse(status_code=exc.status_code, content=exc.payload)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "healthy"}

    @app.post("/items/add", response_model=AddItemResponse, status_code=201)
    def add_item(request: AddItemRequest) -> AddItemResponse:
        logger.info("Adding item at location=%s", request.location)
        try:
            record = state.add_item(request.location)
        except LaboratoryStatusError as error:
            raise_http_error(error)
        return AddItemResponse(location=record.location, occupied=True, item_id=record.item_id)

    @app.post("/items/move", response_model=MoveItemResponse)
    def move_item(request: MoveItemRequest) -> MoveItemResponse:
        logger.info("Moving item from source=%s to destination=%s", request.source, request.destination)
        try:
            record = state.move_item(request.source, request.destination)
        except LaboratoryStatusError as error:
            raise_http_error(error)
        return MoveItemResponse(source=request.source, destination=request.destination, moved=True, item_id=record.item_id)

    @app.delete("/items/remove", response_model=RemoveItemResponse)
    def remove_item(request: RemoveItemRequest) -> RemoveItemResponse:
        logger.info("Removing item at location=%s", request.location)
        try:
            record = state.remove_item(request.location)
        except LaboratoryStatusError as error:
            raise_http_error(error)
        return RemoveItemResponse(location=request.location, removed=True, item_id=record.item_id)

    @app.get("/locations/{location}", response_model=LocationState)
    def get_location(location: str) -> LocationState:
        try:
            location = validate_location(location)
            logger.info("Reading location=%s", location)
            return state.get_location(location)
        except ValueError as error:
            raise_http_error(
                LaboratoryStatusError(
                    "invalid_location",
                    str(error),
                    {"location": location},
                )
            )
        except LaboratoryStatusError as error:
            raise_http_error(error)

    @app.get("/state", response_model=StateResponse)
    def get_state() -> StateResponse:
        logger.info("Reading complete laboratory state")
        return StateResponse(locations=state.snapshot())

    @app.post("/reset", response_model=ResetResponse)
    def reset() -> ResetResponse:
        logger.info("Resetting laboratory state")
        state.reset()
        return ResetResponse(cleared=True)

    return app


app = create_app()
