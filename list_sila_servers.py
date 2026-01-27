"""List reachable SiLA2 servers using discovery."""

from __future__ import annotations

import argparse
import time

from sila2.discovery import SilaDiscoveryBrowser


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="List reachable SiLA2 servers via discovery")
    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="Seconds to listen for servers before printing the list (0 means no wait)",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Use insecure discovery (no TLS). Set this if servers are started with --insecure.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    wait_seconds = max(0.0, args.timeout)

    with SilaDiscoveryBrowser(insecure=args.insecure) as browser:
        if wait_seconds > 0:
            time.sleep(wait_seconds)

        clients = browser.clients

    if not clients:
        print("No SiLA2 servers found.")
        return

    print("Discovered SiLA2 servers:")
    for client in clients:
        server_name = client.SiLAService.ServerName.get()
        server_uuid = client.SiLAService.ServerUUID.get()
        server_type = client.SiLAService.ServerType.get()
        print(f"- {server_name} ({server_type}, UUID: {server_uuid}) @ {client.address}:{client.port}")


if __name__ == "__main__":
    main()
