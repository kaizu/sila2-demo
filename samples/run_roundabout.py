from __future__ import annotations

from contextlib import ExitStack

from common import (
    DEFAULT_LABORATORY_MODEL_URL,
    add_item_to_location,
    build_parser,
    connect,
    get_location_state,
    print_server_identity,
    request_laboratory_model,
    reset_laboratory_model,
    wait_for_observable,
)


TROLLEY_ARM_PORT = 50057
PLATE_SEAL_REMOVER_PORT = 50054
PLATELOC_PORT = 50053
THERMAL_CYCLER_PORT = 50055
CENTRIFUGE_PORT = 50052

STATION_SOURCE = "station:1"
STATION_RETURN = "station:1"
SEAL_REMOVER_LOCATION = "seal-remover:1"
PLATELOC_LOCATION = "plateloc:1"
THERMAL_CYCLER_LOCATION = "thermal-cycler:1"
CENTRIFUGE_LOCATION = "centrifuge:1"


def setup_initial_laboratory_state(*, laboratory_model_url: str) -> str:
    print("Preparing initial laboratory state via laboratory model.")
    reset_laboratory_model(laboratory_model_url=laboratory_model_url)
    initial_state = add_item_to_location(
        laboratory_model_url=laboratory_model_url,
        location=STATION_SOURCE,
    )
    item_id = str(initial_state["item_id"])
    print(f"Initial state: {initial_state}")
    return item_id


def verify_final_laboratory_state(*, laboratory_model_url: str, expected_item_id: str) -> None:
    print("Verifying final laboratory state via laboratory model.")
    final_station = get_location_state(laboratory_model_url=laboratory_model_url, location=STATION_RETURN)
    if final_station["occupied"] is not True:
        raise RuntimeError(f"Expected an item at {STATION_RETURN}, but found: {final_station}")
    if str(final_station["item_id"]) != expected_item_id:
        raise RuntimeError(
            f"Expected item {expected_item_id} at {STATION_RETURN}, but found {final_station['item_id']}"
        )

    for location in (
        SEAL_REMOVER_LOCATION,
        PLATELOC_LOCATION,
        THERMAL_CYCLER_LOCATION,
        CENTRIFUGE_LOCATION,
    ):
        state = get_location_state(laboratory_model_url=laboratory_model_url, location=location)
        if state["occupied"] is True:
            raise RuntimeError(f"Expected no item at {location}, but found: {state}")

    snapshot = request_laboratory_model(laboratory_model_url=laboratory_model_url, path="/state")
    print(f"Final state snapshot: {snapshot}")


def move_with_trolley(*, trolley_feature, laboratory_model_url: str, source: str, destination: str) -> None:
    print(f"Moving item with trolley arm: {source} -> {destination}")
    trolley_feature.Pick(LocationSpecifier=source)
    trolley_feature.Place(LocationSpecifier=destination)

    pick_source_state = get_location_state(
        laboratory_model_url=laboratory_model_url,
        location=source,
    )
    place_destination_state = get_location_state(
        laboratory_model_url=laboratory_model_url,
        location=destination,
    )
    print(f"State after move: source={pick_source_state} destination={place_destination_state}")


def run_roundabout_sequence(*, host: str, insecure: bool, timeout_seconds: float, laboratory_model_url: str) -> None:
    with ExitStack() as stack:
        centrifuge_client = stack.enter_context(connect(host, CENTRIFUGE_PORT, insecure=insecure))
        plateloc_client = stack.enter_context(connect(host, PLATELOC_PORT, insecure=insecure))
        seal_remover_client = stack.enter_context(connect(host, PLATE_SEAL_REMOVER_PORT, insecure=insecure))
        thermal_cycler_client = stack.enter_context(connect(host, THERMAL_CYCLER_PORT, insecure=insecure))
        trolley_client = stack.enter_context(connect(host, TROLLEY_ARM_PORT, insecure=insecure))

        print_server_identity(centrifuge_client, host=host, port=CENTRIFUGE_PORT)
        print_server_identity(plateloc_client, host=host, port=PLATELOC_PORT)
        print_server_identity(seal_remover_client, host=host, port=PLATE_SEAL_REMOVER_PORT)
        print_server_identity(thermal_cycler_client, host=host, port=THERMAL_CYCLER_PORT)
        print_server_identity(trolley_client, host=host, port=TROLLEY_ARM_PORT)

        centrifuge = centrifuge_client.MicroplateCentrifugeController
        plateloc = plateloc_client.PlateLocController
        seal_remover = seal_remover_client.AutomatedPlateSealRemoverController
        thermal_cycler = thermal_cycler_client.AutomatedThermalCyclerController
        trolley = trolley_client.TrolleyArmProvider

        wait_for_observable(
            thermal_cycler.Load(ProtocolFileData=b"mock protocol"),
            label="AutomatedThermalCyclerController.Load",
            timeout_seconds=timeout_seconds,
        )
        wait_for_observable(
            thermal_cycler.Validate(MaxSampleVolume=10.0),
            label="AutomatedThermalCyclerController.Validate",
            timeout_seconds=timeout_seconds,
        )

        move_with_trolley(
            trolley_feature=trolley,
            laboratory_model_url=laboratory_model_url,
            source=STATION_SOURCE,
            destination=SEAL_REMOVER_LOCATION,
        )
        wait_for_observable(
            seal_remover.Peel(BeginPeelLocation=1, AdhesionTime=1),
            label="AutomatedPlateSealRemoverController.Peel",
            timeout_seconds=timeout_seconds,
        )
        print("Peel completed.")

        move_with_trolley(
            trolley_feature=trolley,
            laboratory_model_url=laboratory_model_url,
            source=SEAL_REMOVER_LOCATION,
            destination=PLATELOC_LOCATION,
        )
        plateloc.SetSealingTemperature(SealingTemperature=180)
        plateloc.SetSealingTime(SealingTime=2.0)
        wait_for_observable(
            plateloc.StartCycle(),
            label="PlateLocController.StartCycle",
            timeout_seconds=timeout_seconds,
        )
        print("PlateLoc cycle completed.")

        wait_for_observable(
            thermal_cycler.OpenLid(),
            label="AutomatedThermalCyclerController.OpenLid",
            timeout_seconds=timeout_seconds,
        )
        move_with_trolley(
            trolley_feature=trolley,
            laboratory_model_url=laboratory_model_url,
            source=PLATELOC_LOCATION,
            destination=THERMAL_CYCLER_LOCATION,
        )
        wait_for_observable(
            thermal_cycler.CloseLid(),
            label="AutomatedThermalCyclerController.CloseLid",
            timeout_seconds=timeout_seconds,
        )
        wait_for_observable(
            thermal_cycler.StartRun(),
            label="AutomatedThermalCyclerController.StartRun",
            timeout_seconds=timeout_seconds,
        )
        wait_for_observable(
            thermal_cycler.StopRun(),
            label="AutomatedThermalCyclerController.StopRun",
            timeout_seconds=timeout_seconds,
        )
        wait_for_observable(
            thermal_cycler.OpenLid(),
            label="AutomatedThermalCyclerController.OpenLid",
            timeout_seconds=timeout_seconds,
        )
        print("Thermal cycler run completed.")

        wait_for_observable(
            centrifuge.OpenDoor(BucketNumber=1),
            label="MicroplateCentrifugeController.OpenDoor",
            timeout_seconds=timeout_seconds,
        )
        move_with_trolley(
            trolley_feature=trolley,
            laboratory_model_url=laboratory_model_url,
            source=THERMAL_CYCLER_LOCATION,
            destination=CENTRIFUGE_LOCATION,
        )
        wait_for_observable(
            centrifuge.CloseDoor(),
            label="MicroplateCentrifugeController.CloseDoor",
            timeout_seconds=timeout_seconds,
        )
        wait_for_observable(
            centrifuge.SpinCycle(
                VelocityPercent=50.0,
                AccelerationPercent=50.0,
                DecelerationPercent=50.0,
                TimerMode=1,
                Time=1,
                BucketNumberToLoad=1,
                BucketNumberToUnload=1,
                GripperOffsetToLoad=8.0,
                GripperOffsetToUnload=8.0,
                PlateHeightToLoad=15.0,
                PlateHeightToUnload=15.0,
                SpeedToLoad=1,
                SpeedToUnload=1,
                OptionsToLoad=0,
                OptionsToUnload=0,
            ),
            label="MicroplateCentrifugeController.SpinCycle",
            timeout_seconds=timeout_seconds,
        )
        wait_for_observable(
            centrifuge.OpenDoor(BucketNumber=1),
            label="MicroplateCentrifugeController.OpenDoor",
            timeout_seconds=timeout_seconds,
        )
        print("Centrifuge cycle completed.")

        move_with_trolley(
            trolley_feature=trolley,
            laboratory_model_url=laboratory_model_url,
            source=CENTRIFUGE_LOCATION,
            destination=STATION_RETURN,
        )
        print("Roundabout completed.")


def main() -> int:
    parser = build_parser("Run an end-to-end roundabout workflow using the SiLA2 servers directly.", TROLLEY_ARM_PORT)
    parser.add_argument(
        "--laboratory-model-url",
        default=DEFAULT_LABORATORY_MODEL_URL,
        help="Laboratory model base URL used only for setup and verification",
    )
    args = parser.parse_args()

    expected_item_id = setup_initial_laboratory_state(laboratory_model_url=args.laboratory_model_url)
    run_roundabout_sequence(
        host=args.host,
        insecure=args.insecure,
        timeout_seconds=args.timeout,
        laboratory_model_url=args.laboratory_model_url,
    )
    verify_final_laboratory_state(
        laboratory_model_url=args.laboratory_model_url,
        expected_item_id=expected_item_id,
    )
    print("Roundabout workflow passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
