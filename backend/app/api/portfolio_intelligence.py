"""Portfolio Intelligence API (Mode D).

Exposes a single endpoint::

    GET /api/portfolio/intelligence

which returns:

* Sector allocation per market (US, IN)
* Diversification (HHI + geography split)
* Per-market alpha (Indian holdings vs ^NSEI in INR, US holdings vs ^GSPC in
  USD — NO FX conflation on these numbers)
* Blended benchmark return in the user's base currency (IN% × Nifty-in-base +
  US% × SP500-in-base)
* Portfolio alpha = portfolio_return − blended_benchmark_return
* Rebalancing suggestions (display only, with disclaimer)

A distinct prefix (``/api/portfolio/intelligence`` with a root GET) is used
to avoid a route-order collision with the existing portfolio router which
already mounts multiple paths under ``/api/portfolio``.
"""

from __future__ import annotations

from backend.app.auth.dependencies import get_current_user
from backend.app.config import get_settings
from backend.app.db import get_session
from backend.app.intelligence.portfolio import PortfolioIntelligenceService
from backend.app.models.users import User
from backend.app.redis_client import get_redis
from backend.app.schemas.portfolio_intelligence import PortfolioIntelligenceResponse
from backend.app.services.benchmark import BenchmarkService
from backend.app.services.fx import FxService
from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/portfolio/intelligence", tags=["portfolio"])


@router.get("", response_model=PortfolioIntelligenceResponse)
async def get_portfolio_intelligence(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> PortfolioIntelligenceResponse:
    """Return diversification, per-market alpha, blended benchmark, and rebalancing.

    Rebalancing suggestions are **display only** and each carries the
    "For informational purposes only. Not investment advice." disclaimer.
    """
    base = get_settings().default_base_currency.upper()
    service = PortfolioIntelligenceService(
        session=session,
        fx=FxService(session),
        benchmark_service=BenchmarkService(redis),
    )
    return await service.compute(user_id=current_user.id, base_currency=base)


__all__ = ["router"]
