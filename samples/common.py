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


def ensure_item_at_location(*, laboratory_model_url: str, location: str) -> dict[str, Any]:
    reset_request = Request(f"{laboratory_model_url.rstrip('/')}/reset", method="POST")
    with urlopen(reset_request, timeout=2.0):
        pass

    payload = json.dumps({"location": location}).encode("utf-8")
    add_request = Request(
        f"{laboratory_model_url.rstrip('/')}/items/add",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(add_request, timeout=2.0) as response:
        return json.load(response)


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
