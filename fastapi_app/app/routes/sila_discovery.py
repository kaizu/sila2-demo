from __future__ import annotations

import asyncio
import ipaddress
from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException, Query
from sila2.client import SilaClient
from sila2.discovery import SilaDiscoveryBrowser

router = APIRouter()


def _get_control_feature(client: Any):
    # Support both legacy StationProvider and renamed TrolleyArmProvider.
    for feature_name in ("StationProvider", "TrolleyArmProvider"):
        feature = getattr(client, feature_name, None)
        if feature is not None:
            return feature
    return None


def _discover(timeout: float, insecure: bool) -> List[dict[str, Any]]:
    results: List[dict[str, Any]] = []
    with SilaDiscoveryBrowser(insecure=insecure) as browser:
        if timeout > 0:
            # Blocking wait to collect broadcasts
            import time

            time.sleep(timeout)
        for client in browser.clients:
            status_value = -1
            try:
                control_feature = _get_control_feature(client)
                if control_feature is not None:
                    status_prop = getattr(control_feature, "Status", None)
                    if status_prop is not None:
                        status_value = int(status_prop.get())
            except Exception:
                status_value = -1

            results.append(
                {
                    "name": client.SiLAService.ServerName.get(),
                    "uuid": client.SiLAService.ServerUUID.get(),
                    "type": client.SiLAService.ServerType.get(),
                    "address": {"ip": client.address, "port": client.port},
                    "status": status_value,
                }
            )
    return results


@router.get("/discover")
async def discover(
    timeout: Optional[float] = Query(5.0, ge=0.0, description="Seconds to listen for servers (0 = immediate)"),
    insecure: bool = Query(True, description="Use insecure gRPC connection (match servers started with --insecure)"),
):
    """
    Discover reachable SiLA2 servers and return basic info as JSON.
    """
    try:
        data = await asyncio.to_thread(_discover, timeout or 0.0, insecure)
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=503, detail=f"Discovery failed: {exc}") from exc
    return {"servers": data, "count": len(data)}


# Kept for possible future reuse with discovery-based reset by name/UUID.
# def _find_matching_client(
#     server_name: Optional[str], server_uuid: Optional[str], timeout: float, insecure: bool
# ):
#     if server_name is None and server_uuid is None:
#         raise ValueError("Either server_name or server_uuid must be provided")
#     start = None
#     if timeout > 0:
#         import time
#
#         start = time.time()
#
#     with SilaDiscoveryBrowser(insecure=insecure) as browser:
#         while True:
#             for client in browser.clients:
#                 if server_name is not None and client.SiLAService.ServerName.get() != server_name:
#                     continue
#                 if server_uuid is not None and client.SiLAService.ServerUUID.get() != server_uuid:
#                     continue
#                 return client
#
#             if timeout == 0:
#                 break
#             import time
#
#             time.sleep(0.1)
#             if start is not None and (time.time() - start) >= timeout:
#                 break
#
#     raise TimeoutError("No matching SiLA2 server found")
#
#
def _reset(ip: str, port: int, insecure: bool) -> dict[str, Any]:
    with SilaClient(ip, port, insecure=insecure) as client:
        feature = _get_control_feature(client)
        if feature is None:
            raise RuntimeError("No supported control feature found on target server")

        # Fire the Reset command without waiting for completion
        feature.Reset()

        return {
            "name": client.SiLAService.ServerName.get(),
            "uuid": client.SiLAService.ServerUUID.get(),
            "type": client.SiLAService.ServerType.get(),
            "address": {"ip": ip, "port": port},
        }


@router.post("/reset")
async def reset(
    ip: str = Query(..., description="SiLA Server IPv4/IPv6 address"),
    port: int = Query(..., ge=1, le=65535, description="SiLA Server port"),
    insecure: bool = Query(True, description="Use insecure discovery (match servers started with --insecure)"),
):
    """
    Trigger the reset command on a SiLA2 server specified by IP and port.
    Returns immediately after invoking the command (does not wait for completion).
    """
    try:
        normalized_ip = str(ipaddress.ip_address(ip))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid IP address: {ip}") from exc

    try:
        target = await asyncio.to_thread(_reset, normalized_ip, port, insecure)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=503, detail=f"Reset failed: {exc}") from exc

    return {"server": target}
