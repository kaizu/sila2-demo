"""Tests for the build-time duration slicer, and for the duration files themselves.

Two different things are checked here, and the second is the reason this file exists at all.

`slice_device` gets the ordinary treatment: what it accepts, what it refuses, and what it does
with an absent device or command.

The coverage tests are the interesting ones. An unlisted command waits for nothing, which means
a command that gains a wait in the implementation but is never added to the duration files
silently loses its Running window -- a polling client would then never observe the Status
transition, and nothing would fail. There is no way for the slicer to catch that (it cannot know
a server's command surface), so it is caught here instead, by reading the implementations: every
command whose body waits must appear in every profile, and nothing else may. That makes the two
descriptions of the same fact impossible to drift apart.
"""

from __future__ import annotations

import ast
import pathlib

import pytest
import yaml

from slice_durations import slice_device

REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parents[2]
CONFIG_DIRECTORY = REPOSITORY_ROOT / "config"
# Both profiles are held to the same coverage rule: they describe the same lab at different
# speeds, so they must cover the same commands.
PROFILES = ["command_durations.yaml", "command_durations.realistic.yaml"]

# Which device each server package acts as. The same mapping is written into each Dockerfile's
# builder stage; this copy is what lets the coverage tests below read the implementations without
# guessing.
DEVICE_BY_PACKAGE = {
    "microplate_centrifuge_server": "centrifuge",
    "automated_thermal_cycler_server": "thermal-cycler",
    "plateloc_server": "plateloc",
    "automated_plate_seal_remover_server": "seal-remover",
    "trolley_arm_server": "trolley-arm",
    "station_server": "station",
}

# Calls that make a command wait: the sleep itself, and the centrifuge's two helpers which wrap
# it (its commands share those rather than sleeping inline).
_WAITING_CALLS = frozenset({"sleep", "_begin_running", "_begin_quiet", "sleep_for"})


def timed_commands(package: str) -> set[str]:
    """Command names in `package`'s feature implementation whose body waits.

    Read from the source rather than by importing it: these packages are not installed in this
    environment, and the question is a syntactic one anyway."""
    implementation_directory = REPOSITORY_ROOT / "servers" / package / package / "feature_implementations"
    found: set[str] = set()
    for path in sorted(implementation_directory.glob("*_impl.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for class_node in (node for node in tree.body if isinstance(node, ast.ClassDef)):
            for method in (node for node in class_node.body if isinstance(node, ast.FunctionDef)):
                # SiLA2 commands are the public CamelCase methods; helpers and property getters
                # are not commands and never appear in a duration file.
                if method.name.startswith("_") or method.name.startswith("get_"):
                    continue
                calls = (sub for sub in ast.walk(method) if isinstance(sub, ast.Call))
                if any(isinstance(call.func, ast.Attribute) and call.func.attr in _WAITING_CALLS for call in calls):
                    found.add(method.name)
    return found


def load_profile(name: str) -> dict:
    return yaml.safe_load((CONFIG_DIRECTORY / name).read_text(encoding="utf-8"))


# --- Coverage: the duration files and the implementations must agree. ---


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize("package", sorted(DEVICE_BY_PACKAGE))
def test_every_waiting_command_has_a_duration(profile: str, package: str) -> None:
    # The failure this prevents: a command that waits but is unlisted takes no time, so its
    # Running window collapses and a polling client stops being able to see the transition.
    device = DEVICE_BY_PACKAGE[package]
    configured = set(slice_device(load_profile(profile), device)["commands"])

    missing = timed_commands(package) - configured
    assert not missing, f"{profile} is missing durations for {device}: {sorted(missing)}"


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize("package", sorted(DEVICE_BY_PACKAGE))
def test_no_duration_is_configured_for_a_command_that_does_not_wait(profile: str, package: str) -> None:
    # The other direction, which catches a typo in a command name and an entry left behind after
    # a command stopped waiting. Either way the number would silently do nothing.
    device = DEVICE_BY_PACKAGE[package]
    configured = set(slice_device(load_profile(profile), device)["commands"])

    unexpected = configured - timed_commands(package)
    assert not unexpected, f"{profile} configures non-waiting commands for {device}: {sorted(unexpected)}"


@pytest.mark.parametrize("profile", PROFILES)
def test_profiles_describe_only_devices_that_exist(profile: str) -> None:
    # A device name that matches no server is either a typo or a leftover; either way nothing
    # reads it. The seed file is the authority on which devices exist, so it is what this checks
    # against rather than a list repeated here.
    seed = yaml.safe_load((CONFIG_DIRECTORY / "laboratory_model.seed.yaml").read_text(encoding="utf-8"))
    declared = {entry["id"] for entry in seed["devices"]}

    configured = set(load_profile(profile).get("devices") or {})

    assert configured <= declared, f"{profile} names undeclared devices: {sorted(configured - declared)}"


def test_the_two_profiles_cover_the_same_commands() -> None:
    # They are two speeds of one lab, so a command added to one and forgotten in the other is a
    # mistake even when the per-server checks above happen to pass.
    def command_names(profile: str) -> set[tuple[str, str]]:
        devices = load_profile(profile).get("devices") or {}
        return {(device, command) for device, section in devices.items() for command in section.get("commands") or {}}

    assert command_names(PROFILES[0]) == command_names(PROFILES[1])


def test_the_default_profile_reproduces_the_previous_fixed_wait() -> None:
    # The default profile exists to leave behaviour exactly as it was before durations became
    # configurable, so that the samples stay fast and their 10 s ceiling stays meaningful.
    devices = load_profile("command_durations.yaml")["devices"]
    durations = {
        entry["duration"] for section in devices.values() for entry in (section.get("commands") or {}).values()
    }

    assert durations == {0.05}


# --- The slicer itself. ---


def test_slices_only_the_requested_device() -> None:
    document = {
        "devices": {
            "centrifuge": {"commands": {"SpinCycle": {"duration": 20}}},
            "plateloc": {"commands": {"StartCycle": {"duration": 15}}},
        }
    }

    assert slice_device(document, "centrifuge") == {"commands": {"SpinCycle": {"duration": 20.0}}}


def test_keeps_the_mapping_shape_rather_than_flattening() -> None:
    # Flattening to name -> seconds would read better today and would have to be undone the
    # moment a second per-command setting (jitter) arrives.
    sliced = slice_device({"devices": {"centrifuge": {"commands": {"Home": {"duration": 5}}}}}, "centrifuge")

    assert sliced["commands"]["Home"] == {"duration": 5.0}


def test_preserves_settings_it_does_not_know_about() -> None:
    # So a setting added to the lab-wide file reaches the servers without this script having to
    # learn about it first.
    document = {"devices": {"centrifuge": {"commands": {"Home": {"duration": 5, "jitter": 0.2}}}}}

    assert slice_device(document, "centrifuge")["commands"]["Home"] == {"duration": 5.0, "jitter": 0.2}


def test_an_absent_device_waits_for_nothing() -> None:
    # Not an error: "no timing at all" has to be a configuration rather than a special case.
    assert slice_device({"devices": {"plateloc": {"commands": {}}}}, "centrifuge") == {"commands": {}}


def test_an_empty_document_waits_for_nothing() -> None:
    # An intentionally blank profile parses to None.
    assert slice_device(None, "centrifuge") == {"commands": {}}


def test_a_missing_duration_defaults_to_no_wait() -> None:
    assert slice_device({"devices": {"c": {"commands": {"X": {}}}}}, "c") == {"commands": {"X": {"duration": 0.0}}}


def test_rejects_a_bare_number_instead_of_a_mapping() -> None:
    with pytest.raises(ValueError, match="must be a mapping"):
        slice_device({"devices": {"c": {"commands": {"X": 3}}}}, "c")


def test_rejects_a_non_numeric_duration() -> None:
    with pytest.raises(ValueError, match="non-numeric"):
        slice_device({"devices": {"c": {"commands": {"X": {"duration": "3"}}}}}, "c")


def test_rejects_a_boolean_duration() -> None:
    # bool is an int in Python, so without an explicit check `duration: true` would mean 1 second.
    with pytest.raises(ValueError, match="non-numeric"):
        slice_device({"devices": {"c": {"commands": {"X": {"duration": True}}}}}, "c")


def test_rejects_a_negative_duration() -> None:
    with pytest.raises(ValueError, match="negative"):
        slice_device({"devices": {"c": {"commands": {"X": {"duration": -1}}}}}, "c")


def test_rejects_a_non_mapping_document() -> None:
    with pytest.raises(ValueError, match="top-level mapping"):
        slice_device(["devices"], "c")
