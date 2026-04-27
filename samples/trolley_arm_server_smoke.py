from __future__ import annotations

from common import build_parser, connect, print_server_identity, wait_for_observable


DEFAULT_PORT = 50057


def main() -> int:
    parser = build_parser("Smoke test the Trolley Arm SiLA2 server directly.", DEFAULT_PORT)
    args = parser.parse_args()

    with connect(args.host, args.port, insecure=args.insecure) as client:
        print_server_identity(client, host=args.host, port=args.port)

        feature = client.TrolleyArmProvider
        original_position = feature.TrolleyPosition.get()
        print(f"Original trolley position: {original_position}")

        temporary_position = original_position + 1
        feature.SetTrolleyPosition(Position=temporary_position)
        print(f"Trolley position after move: {feature.TrolleyPosition.get()}")

        feature.SetTrolleyPosition(Position=original_position)
        print(f"Trolley position restored: {feature.TrolleyPosition.get()}")

        wait_for_observable(feature.Reset(), label="TrolleyArmProvider.Reset", timeout_seconds=args.timeout)
        print(f"Status after reset: {feature.Status.get()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
