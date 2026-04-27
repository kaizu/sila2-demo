from __future__ import annotations

from common import (
    DEFAULT_LABORATORY_MODEL_URL,
    build_parser,
    connect,
    ensure_item_at_location,
    print_server_identity,
    wait_for_observable,
)


DEFAULT_PORT = 50054
DEFAULT_LOCATION = "seal-remover:1"


def main() -> int:
    parser = build_parser("Smoke test the Automated Plate Seal Remover SiLA2 server directly.", DEFAULT_PORT)
    parser.add_argument(
        "--laboratory-model-url",
        default=DEFAULT_LABORATORY_MODEL_URL,
        help="Laboratory model base URL used to seed required test items",
    )
    parser.add_argument(
        "--laboratory-model-location",
        default=DEFAULT_LOCATION,
        help="Laboratory model location required by the seal remover server",
    )
    args = parser.parse_args()

    seeded_item = ensure_item_at_location(
        laboratory_model_url=args.laboratory_model_url,
        location=args.laboratory_model_location,
    )
    print(f"Seeded laboratory model item: {seeded_item}")

    with connect(args.host, args.port, insecure=args.insecure) as client:
        print_server_identity(client, host=args.host, port=args.port)

        feature = client.AutomatedPlateSealRemoverController
        tape_before = wait_for_observable(
            feature.GetTapeLeft(),
            label="AutomatedPlateSealRemoverController.GetTapeLeft",
            timeout_seconds=args.timeout,
        )
        print(f"Tape before peel: {tape_before}")

        peel_result = wait_for_observable(
            feature.Peel(BeginPeelLocation=1, AdhesionTime=1),
            label="AutomatedPlateSealRemoverController.Peel",
            timeout_seconds=args.timeout,
        )
        print(f"Peel result: {peel_result}")

        tape_after = wait_for_observable(
            feature.GetTapeLeft(),
            label="AutomatedPlateSealRemoverController.GetTapeLeft",
            timeout_seconds=args.timeout,
        )
        print(f"Tape after peel: {tape_after}")

        wait_for_observable(
            feature.Reset(),
            label="AutomatedPlateSealRemoverController.Reset",
            timeout_seconds=args.timeout,
        )
        print(f"Status after reset: {feature.Status.get()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
