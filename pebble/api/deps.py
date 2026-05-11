"""FastAPI dependency providers.

Routes resolve their concrete services through these functions; nothing
in the API layer reaches into module-level globals. The MCP adapter
will build the same `Services` and pass it as the tool context.
"""

from __future__ import annotations

from fastapi import HTTPException, Request, status

from pebble.bootstrap import Services


def require_services(request: Request) -> Services:
    services: Services | None = getattr(request.app.state, "services", None)
    if services is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="services are still initialising; check /ready",
        )
    return services
