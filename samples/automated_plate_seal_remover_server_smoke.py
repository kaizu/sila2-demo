from __future__ import annotations

from common import build_parser, connect, print_server_identity, wait_for_observable


DEFAULT_PORT = 50054


def main() -> int:
    parser = build_parser("Smoke test the Automated Plate Seal Remover SiLA2 server directly.", DEFAULT_PORT)
    args = parser.parse_args()

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
