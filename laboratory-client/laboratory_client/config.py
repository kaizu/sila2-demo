"""How a server is told where the laboratory model is, and which location it acts on.

Both values come from the environment (`LABORATORY_MODEL_URL`,
`LABORATORY_MODEL_LOCATION`), set by docker-compose alongside `SILA_SERVER_NAME` and
`SILA_SERVER_TYPE`. They used to arrive as `--laboratory-model-*` options on each server's
generated `__main__.py`, which pushed them into `os.environ` for the constructor to read
back: the environment was always the real channel, and the CLI a hand-written detour
through a file that is otherwise pure code-generator output. Reading the environment
directly removes that detour and puts the validation somewhere it can be tested.

The rules below distinguish "not configured" from "configured wrongly", because the two
deserve different outcomes. A server may legitimately run with no world model at all (the
instrument servers then skip their world checks and say so in the log), so an absent
variable is not an error. A variable that is present but blank, or padded with whitespace,
is a mistake in whoever set it -- silently accepting it would produce a server that quietly
enforces nothing, or one that acts on a location no other component can name.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

URL_VARIABLE = "LABORATORY_MODEL_URL"
LOCATION_VARIABLE = "LABORATORY_MODEL_LOCATION"


class LaboratoryModelConfigError(ValueError):
    """A laboratory-model environment variable is present but unusable.

    Raised while a server is being constructed, so a misconfigured container fails at
    startup with the reason rather than running on and failing later at the first command.
    """


@dataclass(frozen=True)
class LaboratoryModelConfig:
    """Where the laboratory model is, and which location this server acts on.

    Both are optional: `None` means "not configured", which each server interprets for
    itself (the instrument servers skip their world checks; Ardea refuses to transfer,
    because a transfer that does not reach the world model has not happened).
    """

    url: str | None
    location: str | None


def load_laboratory_model_config(environ: Mapping[str, str] | None = None) -> LaboratoryModelConfig:
    """Read and validate both variables. `environ` defaults to the process environment and
    is a parameter so tests need not mutate global state."""
    source = os.environ if environ is None else environ
    return LaboratoryModelConfig(
        url=_read_optional(source, URL_VARIABLE),
        location=_read_optional(source, LOCATION_VARIABLE),
    )


def _read_optional(source: Mapping[str, str], name: str) -> str | None:
    # Absent means "not configured" -- the one case that is allowed to be quiet.
    if name not in source:
        return None

    value = source[name]
    # Set-but-blank is a mistake, not a way of saying "unset": something built this value
    # and produced nothing, and treating it as unset would hide that.
    if not value.strip():
        raise LaboratoryModelConfigError(f"{name} is set but empty")
    # Reject padding rather than trimming it, matching how the world model validates a
    # location name: a caller that passes a padded value has a bug worth surfacing, and
    # trimming here would make this server and the world model disagree about the name.
    if value != value.strip():
        raise LaboratoryModelConfigError(f"{name} must not contain leading or trailing whitespace")
    return value
