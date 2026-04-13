"""FastAPI application entry point."""

from backend.app.api.auth import router as auth_router
from backend.app.api.broker_auth import router as broker_auth_router
from backend.app.api.instruments import router as instruments_router
from backend.app.config import get_settings
from fastapi import FastAPI

settings = get_settings()
app = FastAPI(title=settings.app_name, debug=settings.debug)

app.include_router(auth_router)
app.include_router(broker_auth_router)
app.include_router(instruments_router)


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe for orchestrators and load balancers."""
    return {"status": "ok", "environment": settings.environment}
