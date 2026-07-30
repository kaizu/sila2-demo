"""Tests for laboratory-model configuration (`laboratory_client.config`).

The loader's job is to tell "not configured" apart from "configured wrongly", because the
two have to end differently: a server with no world model wired up is a supported way to
run, while a variable that is set to nothing is a mistake that should stop startup rather
than produce a server which quietly enforces nothing.

Every test passes an explicit mapping instead of touching `os.environ`, which is the reason
`load_laboratory_model_config` takes one.
"""

from __future__ import annotations

import pytest

from laboratory_client import config


def test_reads_both_variables() -> None:
    loaded = config.load_laboratory_model_config(
        {"LABORATORY_MODEL_URL": "http://laboratory-model:8001", "LABORATORY_MODEL_LOCATION": "centrifuge:1"}
    )

    assert loaded.url == "http://laboratory-model:8001"
    assert loaded.location == "centrifuge:1"


def test_absent_variables_are_not_configured_rather_than_an_error() -> None:
    # Running without a world model is legitimate -- the instrument servers then skip their
    # world checks -- so an empty environment must load cleanly.
    loaded = config.load_laboratory_model_config({})

    assert loaded.url is None
    assert loaded.location is None


def test_either_variable_may_be_configured_alone() -> None:
    # The two are read independently; a server that knows the model's address but not its
    # own location is a state the servers already handle (they check for both).
    loaded = config.load_laboratory_model_config({"LABORATORY_MODEL_URL": "http://laboratory-model:8001"})

    assert loaded.url == "http://laboratory-model:8001"
    assert loaded.location is None


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_a_set_but_blank_variable_is_an_error(blank: str) -> None:
    # Set-but-blank is not a way of saying "unset": something produced this value and it
    # came out empty. Accepting it would silently disable the world checks.
    with pytest.raises(config.LaboratoryModelConfigError) as error:
        config.load_laboratory_model_config({"LABORATORY_MODEL_LOCATION": blank})

    assert "LABORATORY_MODEL_LOCATION" in str(error.value)


@pytest.mark.parametrize("padded", [" centrifuge:1", "centrifuge:1 ", "\tcentrifuge:1"])
def test_a_padded_location_is_rejected_not_trimmed(padded: str) -> None:
    # Trimming would leave this server acting on `centrifuge:1` while whoever set the
    # variable believes it is the padded string -- and the world model rejects padded names
    # too, so accepting one here just moves the failure somewhere less obvious.
    with pytest.raises(config.LaboratoryModelConfigError):
        config.load_laboratory_model_config({"LABORATORY_MODEL_LOCATION": padded})


def test_a_padded_url_is_rejected_too() -> None:
    # Same rule for both variables: the previous CLI options only validated the location,
    # which meant a padded URL became an unreachable address discovered at the first command.
    with pytest.raises(config.LaboratoryModelConfigError):
        config.load_laboratory_model_config({"LABORATORY_MODEL_URL": " http://laboratory-model:8001"})


def test_internal_whitespace_is_left_alone() -> None:
    # Only the edges are policed. The world model has its own grammar for what a location
    # name may contain, and duplicating it here would be a second place to keep in step.
    loaded = config.load_laboratory_model_config({"LABORATORY_MODEL_LOCATION": "odd name"})

    assert loaded.location == "odd name"
