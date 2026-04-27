from __future__ import annotations

from common import (
    DEFAULT_LABORATORY_MODEL_URL,
    build_parser,
    connect,
    ensure_item_at_location,
    print_server_identity,
    wait_for_observable,
)


DEFAULT_PORT = 50053
DEFAULT_LOCATION = "plateloc:1"


def main() -> int:
    parser = build_parser("Smoke test the PlateLoc SiLA2 server directly.", DEFAULT_PORT)
    parser.add_argument(
        "--laboratory-model-url",
        default=DEFAULT_LABORATORY_MODEL_URL,
        help="Laboratory model base URL used to seed required test items",
    )
    parser.add_argument(
        "--laboratory-model-location",
        default=DEFAULT_LOCATION,
        help="Laboratory model location required by the PlateLoc server",
    )
    args = parser.parse_args()

    seeded_item = ensure_item_at_location(
        laboratory_model_url=args.laboratory_model_url,
        location=args.laboratory_model_location,
    )
    print(f"Seeded laboratory model item: {seeded_item}")

    with connect(args.host, args.port, insecure=args.insecure) as client:
        print_server_identity(client, host=args.host, port=args.port)

        feature = client.PlateLocController
        print(f"Initial sealing temperature: {feature.SealingTemperature.get()}")
        print(f"Initial sealing time: {feature.SealingTime.get()}")
        print(f"Profiles: {feature.EnumerateProfiles()}")

        feature.SetSealingTemperature(SealingTemperature=180)
        feature.SetSealingTime(SealingTime=2.0)
        print(f"Updated sealing temperature: {feature.SealingTemperature.get()}")
        print(f"Updated sealing time: {feature.SealingTime.get()}")

        wait_for_observable(
            feature.StartCycle(),
            label="PlateLocController.StartCycle",
            timeout_seconds=args.timeout,
        )
        print(f"Cycle count after StartCycle: {feature.CycleCount.get()}")

        wait_for_observable(
            feature.Reset(),
            label="PlateLocController.Reset",
            timeout_seconds=args.timeout,
        )
        print(f"Cycle count after reset: {feature.CycleCount.get()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
