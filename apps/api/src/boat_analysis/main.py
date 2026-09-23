import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .routers import analysis, evaluations, health, imports, races, reports
from .services.daily_excel import DailyExcelNotReady, generate_due_daily_excel
from .services.official_exhibitions import refresh_official_exhibitions
from .services.official_laps import refresh_boatcast_laps
from .services.official_results import refresh_official_results
from .services.official_win_odds import refresh_official_win_odds

settings = get_settings()

logger = logging.getLogger(__name__)


async def _poll_official_data() -> None:
    while True:
        try:
            if settings.official_win_odds_fetch_enabled:
                await asyncio.to_thread(refresh_official_win_odds)
            if settings.official_exhibition_fetch_enabled:
                await asyncio.to_thread(refresh_official_exhibitions)
            if settings.boatcast_lap_fetch_enabled:
                await asyncio.to_thread(refresh_boatcast_laps)
            if settings.official_result_fetch_enabled:
                await asyncio.to_thread(refresh_official_results)
            if settings.daily_excel_enabled:
                try:
                    await asyncio.to_thread(generate_due_daily_excel)
                except DailyExcelNotReady:
                    logger.info("Daily Excel is waiting for all official results")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Official data polling failed")
        await asyncio.sleep(settings.official_result_poll_seconds)


@asynccontextmanager
async def lifespan(_: FastAPI):
    task = (
        asyncio.create_task(_poll_official_data())
        if settings.official_result_fetch_enabled
        or settings.official_exhibition_fetch_enabled
        or settings.official_win_odds_fetch_enabled
        or settings.boatcast_lap_fetch_enabled
        or settings.daily_excel_enabled
        else None
    )
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


app = FastAPI(
    title="ボートレース展示分析 API",
    version="0.1.0",
    description="展示情報を用いた説明可能な統計分析API。結果や利益を保証しません。",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.api_cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
app.include_router(health.router)
app.include_router(imports.router, prefix="/api")
app.include_router(races.router, prefix="/api")
app.include_router(analysis.router, prefix="/api")
app.include_router(evaluations.router, prefix="/api")
app.include_router(reports.router, prefix="/api")
