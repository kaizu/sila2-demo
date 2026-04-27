from __future__ import annotations

import argparse
import json
import time
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen

from sila2.client import SilaClient


DEFAULT_HOST = "127.0.0.1"
DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_LABORATORY_MODEL_URL = "http://127.0.0.1:8001"


def build_parser(description: str, default_port: int) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--host", default=DEFAULT_HOST, help="SiLA2 server host")
    parser.add_argument("--port", type=int, default=default_port, help="SiLA2 server port")
    parser.add_argument(
        "--insecure",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Use an insecure gRPC connection",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Timeout in seconds for observable commands",
    )
    return parser


def connect(host: str, port: int, *, insecure: bool) -> SilaClient:
    return SilaClient(host, port, insecure=insecure)


def request_laboratory_model(
    *,
    laboratory_model_url: str,
    path: str,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    request_data = None
    headers: dict[str, str] = {}
    if payload is not None:
        request_data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = Request(
        f"{laboratory_model_url.rstrip('/')}/{path.lstrip('/')}",
        data=request_data,
        headers=headers,
        method=method,
    )
    with urlopen(request, timeout=2.0) as response:
        return json.load(response)


def get_laboratory_model_health(*, laboratory_model_url: str) -> dict[str, Any]:
    return request_laboratory_model(laboratory_model_url=laboratory_model_url, path="/health")


def reset_laboratory_model(*, laboratory_model_url: str) -> dict[str, Any]:
    return request_laboratory_model(laboratory_model_url=laboratory_model_url, path="/reset", method="POST")


def add_item_to_location(*, laboratory_model_url: str, location: str) -> dict[str, Any]:
    return request_laboratory_model(
        laboratory_model_url=laboratory_model_url,
        path="/items/add",
        method="POST",
        payload={"location": location},
    )


def move_item_between_locations(*, laboratory_model_url: str, source: str, destination: str) -> dict[str, Any]:
    return request_laboratory_model(
        laboratory_model_url=laboratory_model_url,
        path="/items/move",
        method="POST",
        payload={"source": source, "destination": destination},
    )


def remove_item_from_location(*, laboratory_model_url: str, location: str) -> dict[str, Any]:
    return request_laboratory_model(
        laboratory_model_url=laboratory_model_url,
        path="/items/remove",
        method="DELETE",
        payload={"location": location},
    )


def ensure_item_at_location(*, laboratory_model_url: str, location: str) -> dict[str, Any]:
    reset_laboratory_model(laboratory_model_url=laboratory_model_url)
    return add_item_to_location(laboratory_model_url=laboratory_model_url, location=location)


def get_location_state(*, laboratory_model_url: str, location: str) -> dict[str, Any]:
    encoded_location = quote(location, safe="")
    with urlopen(f"{laboratory_model_url.rstrip('/')}/locations/{encoded_location}", timeout=2.0) as response:
        return json.load(response)


def print_server_identity(client: SilaClient, *, host: str, port: int) -> None:
    server_name = client.SiLAService.ServerName.get()
    server_type = client.SiLAService.ServerType.get()
    server_uuid = client.SiLAService.ServerUUID.get()
    print(f"Connected to {server_name} ({server_type}, {server_uuid}) at {host}:{port}")


def wait_for_observable(instance: Any, *, label: str, timeout_seconds: float) -> Any:
    deadline = time.monotonic() + timeout_seconds
    while not instance.done:
        if time.monotonic() > deadline:
            raise TimeoutError(f"{label} did not finish within {timeout_seconds:.1f} seconds")
        time.sleep(0.05)
    return instance.get_responses()
