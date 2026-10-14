import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .routers import analysis, evaluations, health, imports, lab, races, reports
from .services.brd_importer import ImportAlreadyRunning
from .services.course_start_stats import ensure_course_start_stats
from .services.daily_excel import DailyExcelNotReady, generate_due_daily_excel
from .services.importer import run_import
from .services.official_exhibitions import refresh_official_exhibitions
from .services.official_laps import refresh_boatcast_laps
from .services.official_results import refresh_official_results
from .services.official_win_odds import refresh_official_trifecta_odds
from .services.strategy_lab import refresh_strategy_lab
from .services.telegram_notifications import refresh_ticket_notifications

settings = get_settings()

logger = logging.getLogger(__name__)


async def _poll_official_data() -> None:
    while True:
        try:
            today = datetime.now(ZoneInfo(settings.app_timezone)).date()
            try:
                await asyncio.to_thread(run_import, date_from=today)
            except ImportAlreadyRunning:
                logger.info("Source import is already running")
            except Exception:
                logger.exception("Source import refresh failed")
            if settings.official_trifecta_odds_fetch_enabled:
                await asyncio.to_thread(refresh_official_trifecta_odds)
            if settings.official_exhibition_fetch_enabled:
                await asyncio.to_thread(refresh_official_exhibitions)
            if settings.boatcast_lap_fetch_enabled:
                await asyncio.to_thread(refresh_boatcast_laps)
            if settings.official_result_fetch_enabled:
                await asyncio.to_thread(refresh_official_results)
            try:
                await asyncio.to_thread(
                    ensure_course_start_stats,
                    today,
                )
            except Exception:
                logger.exception("Course start statistics refresh failed")
            if settings.live_strategy_lab_enabled:
                try:
                    await asyncio.to_thread(refresh_strategy_lab)
                except Exception:
                    logger.exception("LIVE strategy lab refresh failed")
            try:
                await asyncio.to_thread(refresh_ticket_notifications)
            except Exception:
                logger.exception("Telegram ticket notification refresh failed")
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
        or settings.official_trifecta_odds_fetch_enabled
        or settings.boatcast_lap_fetch_enabled
        or settings.daily_excel_enabled
        or settings.telegram_notifications_enabled
        or settings.live_strategy_lab_enabled
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
app.include_router(lab.router, prefix="/api")
