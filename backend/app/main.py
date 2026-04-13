"""FastAPI application entry point."""
from fastapi import FastAPI

from .config import get_settings

settings = get_settings()
app = FastAPI(title=settings.app_name, debug=settings.debug)


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe for orchestrators and load balancers."""
    return {"status": "ok", "environment": settings.environment}
