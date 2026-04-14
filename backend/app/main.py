"""FastAPI application entry point."""

from backend.app.api.analysis import router as analysis_router
from backend.app.api.auth import router as auth_router
from backend.app.api.broker_auth import router as broker_auth_router
from backend.app.api.calendar import router as calendar_router
from backend.app.api.instruments import router as instruments_router
from backend.app.api.portfolio import router as portfolio_router
from backend.app.config import get_settings
from fastapi import FastAPI

settings = get_settings()
app = FastAPI(title=settings.app_name, debug=settings.debug)

app.include_router(auth_router)
app.include_router(broker_auth_router)
app.include_router(instruments_router)
app.include_router(calendar_router)
app.include_router(portfolio_router)
app.include_router(analysis_router)


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe for orchestrators and load balancers."""
    return {"status": "ok", "environment": settings.environment}
