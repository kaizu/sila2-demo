from __future__ import annotations

import asyncio
from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException, Query
from sila2.discovery import SilaDiscoveryBrowser

router = APIRouter()


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
                station_feature = getattr(client, "StationProvider", None)
                if station_feature is not None:
                    status_prop = getattr(station_feature, "Status", None)
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
    insecure: bool = Query(True, description="Use insecure discovery (match servers started with --insecure)"),
):
    """
    Discover reachable SiLA2 servers and return basic info as JSON.
    """
    try:
        data = await asyncio.to_thread(_discover, timeout or 0.0, insecure)
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=503, detail=f"Discovery failed: {exc}") from exc
    return {"servers": data, "count": len(data)}


def _find_matching_client(
    server_name: Optional[str], server_uuid: Optional[str], timeout: float, insecure: bool
):
    if server_name is None and server_uuid is None:
        raise ValueError("Either server_name or server_uuid must be provided")
    start = None
    if timeout > 0:
        import time

        start = time.time()

    with SilaDiscoveryBrowser(insecure=insecure) as browser:
        while True:
            for client in browser.clients:
                if server_name is not None and client.SiLAService.ServerName.get() != server_name:
                    continue
                if server_uuid is not None and client.SiLAService.ServerUUID.get() != server_uuid:
                    continue
                return client

            if timeout == 0:
                break
            import time

            time.sleep(0.1)
            if start is not None and (time.time() - start) >= timeout:
                break

    raise TimeoutError("No matching SiLA2 server found")


def _reset(server_name: Optional[str], server_uuid: Optional[str], timeout: float, insecure: bool) -> dict[str, Any]:
    client = _find_matching_client(server_name, server_uuid, timeout, insecure)
    feature = getattr(client, "StationProvider", None)
    if feature is None:
        raise RuntimeError("StationProvider feature not available on target server")

    # Fire the Reset command without waiting for completion
    feature.Reset()

    return {
        "name": client.SiLAService.ServerName.get(),
        "uuid": client.SiLAService.ServerUUID.get(),
        "type": client.SiLAService.ServerType.get(),
    }


@router.post("/reset")
async def reset(
    server_name: Optional[str] = Query(None, description="SiLA Server name to reset"),
    server_uuid: Optional[str] = Query(None, description="SiLA Server UUID to reset"),
    timeout: Optional[float] = Query(5.0, ge=0.0, description="Seconds to wait for a matching server"),
    insecure: bool = Query(True, description="Use insecure discovery (match servers started with --insecure)"),
):
    """
    Trigger the StationProvider Reset command on a matching SiLA2 server.
    Returns immediately after invoking the command (does not wait for completion).
    """
    try:
        target = await asyncio.to_thread(_reset, server_name, server_uuid, timeout or 0.0, insecure)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=503, detail=f"Reset failed: {exc}") from exc

    return {"server": target}
