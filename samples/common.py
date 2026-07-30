"""Shared helpers for the sample scripts in this directory.

The samples reach the mock lab over two channels, and this module wraps both:

* **SiLA2** -- `connect()` builds a `sila2` client for one mock instrument server, and
  `wait_for_observable()` drives an observable command to completion.
* **Laboratory model** -- a small stdlib-only HTTP client for the shared world-state
  service. The samples use it to *arrange* the physical world before a test and to
  *assert* on it afterwards. During a run it is the instrument servers that mutate the
  world; reaching into it directly is a test-harness privilege, not something a real
  workflow client would do.

`build_parser()` gives every sample the same base command line so `run_all_smoke_tests.py`
can launch them uniformly.
"""

from __future__ import annotations

import argparse
import json
import time
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from sila2.client import SilaClient

# The stack is reached through the ports docker-compose publishes on the host, so the
# defaults are localhost-based; --host/--port/--laboratory-model-url retarget a remote one.
DEFAULT_HOST = "127.0.0.1"
# Every mock command finishes in well under a second, so 10s is a generous ceiling whose
# only job is to turn a hung server into a prompt failure instead of a stuck script.
DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_LABORATORY_MODEL_URL = "http://127.0.0.1:8001"


def build_parser(description: str, default_port: int) -> argparse.ArgumentParser:
    """Base command line shared by every SiLA2 sample.

    Each script supplies its own description and the port its server is published on, and
    may add script-specific options on top of the returned parser."""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--host", default=DEFAULT_HOST, help="SiLA2 server host")
    parser.add_argument("--port", type=int, default=default_port, help="SiLA2 server port")
    # All mock servers are started with --insecure (no certificates), so the client must
    # match; the flag exists for pointing a sample at a TLS-enabled server instead.
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
    """Open a SiLA2 client. The client is a context manager, so callers use
    `with connect(...) as client:` to guarantee the connection is closed."""
    return SilaClient(host, port, insecure=insecure)


def request_laboratory_model(
    *,
    laboratory_model_url: str,
    path: str,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call the laboratory model and return its decoded JSON body.

    Raises on any non-2xx response (urllib turns those into `HTTPError`), which is what
    the samples want: an unexpected world-rule rejection should fail the test loudly."""
    # A body is sent only when there is a payload; GET/DELETE-without-body calls stay bare.
    request_data = None
    headers: dict[str, str] = {}
    if payload is not None:
        request_data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    # Join base URL and path defensively so callers may pass either with or without slashes.
    request = Request(
        f"{laboratory_model_url.rstrip('/')}/{path.lstrip('/')}",
        data=request_data,
        headers=headers,
        method=method,
    )
    # Fixed 2s ceiling: the world model is an in-memory service reached over the local
    # network, so a healthy call answers in milliseconds. (The one call that can legitimately
    # exceed it is the very first one after `docker compose up`, while the container is
    # still starting -- rerun the sample in that case.)
    with urlopen(request, timeout=2.0) as response:
        return json.load(response)


def expect_laboratory_model_error(
    *,
    laboratory_model_url: str,
    path: str,
    method: str,
    payload: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    """Negative-path counterpart of `request_laboratory_model`: assert that a call is
    *rejected* and hand the caller the status code and error body to inspect.

    The request is built exactly as above, but the outcome is inverted -- a successful
    response is the failure here, because it means a world rule did not hold."""
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
    try:
        with urlopen(request, timeout=2.0) as response:
            raise RuntimeError(f"Expected laboratory model error but request succeeded: {response.status}")
    except HTTPError as error:
        # The error object is also a readable file, so the JSON envelope
        # ({"error": {"code", "message", "details"}}) is parsed straight from it.
        return error.code, json.load(error)


# --- One thin wrapper per laboratory model endpoint, so the samples below read as lab
# --- actions ("add an item here", "lock that location") rather than as URLs and verbs.


def get_laboratory_model_health(*, laboratory_model_url: str) -> dict[str, Any]:
    return request_laboratory_model(laboratory_model_url=laboratory_model_url, path="/health")


def reset_laboratory_model(*, laboratory_model_url: str) -> dict[str, Any]:
    # Clears the world to empty. Note this does NOT reload the startup seed file, so the
    # caller owns re-establishing whatever state it needs afterwards.
    return request_laboratory_model(laboratory_model_url=laboratory_model_url, path="/reset", method="POST")


def add_item_to_location(*, laboratory_model_url: str, location: str) -> dict[str, Any]:
    # Materialise a plate out of nothing at `location`. Only the harness may do this; in a
    # real run items only ever arrive by a transport move.
    return request_laboratory_model(
        laboratory_model_url=laboratory_model_url,
        path="/items/add",
        method="POST",
        payload={"location": location},
    )


def move_item_between_locations(*, laboratory_model_url: str, source: str, destination: str) -> dict[str, Any]:
    # Direct world-model move, bypassing the trolley arm. Used to check the model's own
    # rules; workflow-level transport goes through TrolleyArmProvider Pick/Place instead.
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


def lock_location(*, laboratory_model_url: str, location: str) -> dict[str, Any]:
    # Make a location inaccessible by hand. The instrument servers normally drive this via
    # their door/lid commands; the samples call it directly to test the rule in isolation.
    return request_laboratory_model(
        laboratory_model_url=laboratory_model_url,
        path="/locations/lock",
        method="POST",
        payload={"location": location},
    )


def unlock_location(*, laboratory_model_url: str, location: str) -> dict[str, Any]:
    return request_laboratory_model(
        laboratory_model_url=laboratory_model_url,
        path="/locations/unlock",
        method="POST",
        payload={"location": location},
    )


def ensure_item_at_location(*, laboratory_model_url: str, location: str) -> dict[str, Any]:
    """Put the world into exactly the state a single-server smoke test needs: wipe it
    (so a previously-run sample cannot leave an item or a closed door behind) and then
    place one plate at the location that server acts on.

    Wiping first is why the per-server smoke tests can be run in any order, repeatedly,
    and individually."""
    reset_laboratory_model(laboratory_model_url=laboratory_model_url)
    return add_item_to_location(laboratory_model_url=laboratory_model_url, location=location)


def get_location_state(*, laboratory_model_url: str, location: str) -> dict[str, Any]:
    # Read one location's occupancy + accessibility. The name goes into a path segment and
    # contains a colon ("centrifuge:1"), so it must be percent-encoded; safe="" also escapes
    # any "/". This is a bare GET with no body, hence urlopen directly rather than the
    # request helper above.
    encoded_location = quote(location, safe="")
    with urlopen(f"{laboratory_model_url.rstrip('/')}/locations/{encoded_location}", timeout=2.0) as response:
        return json.load(response)


def print_server_identity(client: SilaClient, *, host: str, port: int) -> None:
    # Read the three SiLAService properties every SiLA2 server must expose. Besides being
    # useful log context, this doubles as the connectivity check: reaching the wrong port
    # or a server that is not up yet fails here, before any feature command is attempted.
    server_name = client.SiLAService.ServerName.get()
    server_type = client.SiLAService.ServerType.get()
    server_uuid = client.SiLAService.ServerUUID.get()
    print(f"Connected to {server_name} ({server_type}, {server_uuid}) at {host}:{port}")


def wait_for_observable(instance: Any, *, label: str, timeout_seconds: float) -> Any:
    """Drive an observable command instance to completion and return its responses.

    Polling with a deadline (rather than blocking on the instance) is what lets a sample
    fail loudly: a server that never finishes a command would otherwise hang the script
    for ever. `label` names the command in the timeout message so the failing step is
    identifiable in `run_all_smoke_tests.py` output, where only stdout is collected."""
    deadline = time.monotonic() + timeout_seconds
    while not instance.done:
        if time.monotonic() > deadline:
            raise TimeoutError(f"{label} did not finish within {timeout_seconds:.1f} seconds")
        # 50 ms keeps the polling cheap while still returning promptly for the mocks'
        # sub-second commands.
        time.sleep(0.05)
    return instance.get_responses()
