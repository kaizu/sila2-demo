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
