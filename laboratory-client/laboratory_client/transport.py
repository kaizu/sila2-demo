"""HTTP transport for talking to the shared laboratory model.

Every mock SiLA2 server has to reach the laboratory model over HTTP, and each one used to
carry its own copy of the same urlopen / JSON / timeout / error-translation code. This
module is that code extracted once -- and deliberately ONLY that code.

It knows how to address the laboratory model and how to turn a failed call into one
exception type. It knows nothing about what the world *means*: occupancy preconditions,
lid and door semantics, and device state transitions stay in each server's own
implementation. That split is a design rule for this environment, not an accident --
generalising transitions across servers or commands is explicitly out of scope, because
the world model is a generic state store and every interpretation of it belongs to the
command that performs it.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

# Every call goes to a container on the same compose network, so a short timeout is the
# right default: a laboratory model that cannot answer within this window is a failure
# worth reporting, not something to sit and wait out inside a SiLA2 command.
DEFAULT_TIMEOUT_SECONDS = 2.0


class LaboratoryModelRequestError(RuntimeError):
    """A call to the laboratory model did not complete (transport failure, error status, or
    a body that would not decode).

    Callers are expected to catch this and re-raise with a message naming the command and
    the precondition or physical effect that therefore did not happen. That wording is
    server-specific, so it is not built here -- this type only says "the call failed".
    """


def request_laboratory_model(
    *,
    base_url: str,
    path: str,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Call the laboratory model and return its decoded JSON body.

    `base_url` and `path` are joined tolerantly (a trailing slash on one and a leading
    slash on the other are both fine) so callers can pass either form. A `payload` is sent
    as a JSON body; without one no body and no content-type header is sent, which keeps a
    plain GET a plain GET.
    """
    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"

    # Body and header travel together: set neither for a read, both for a write.
    data = None
    headers: dict[str, str] = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = Request(url, data=data, headers=headers, method=method)  # noqa: S310, fixed http(s) URL from config
    # HTTPError covers a 4xx/5xx from the model, URLError a network-level failure,
    # TimeoutError the deadline above, and JSONDecodeError a body we cannot read. All four
    # mean the same thing to a caller -- the call did not happen -- so they collapse into
    # one exception type.
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310, see above
            decoded: dict[str, Any] = json.load(response)
            return decoded
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
        raise LaboratoryModelRequestError(f"laboratory model request to {url} failed: {error}") from error


def get_location(
    *,
    base_url: str,
    location: str,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Read one location's state (`GET /locations/{location}`).

    A location is `device.spot` (`centrifuge.deck`) and goes into a path segment, so it is
    percent-encoded here with `safe=""` -- the single place that encoding has to be right for
    every server, and the reason a device or spot name containing something a path would read
    as structure cannot address the wrong location.
    """
    return request_laboratory_model(
        base_url=base_url,
        path=f"/locations/{quote(location, safe='')}",
        timeout=timeout,
    )
