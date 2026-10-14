from dataclasses import asdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query

from ..config import get_settings
from ..database import DbSession
from ..schemas import LabDashboardOut, LabRefreshOut
from ..services.strategy_lab import lab_dashboard, refresh_strategy_lab

router = APIRouter(prefix="/lab", tags=["strategy-lab"])


@router.get("/dashboard", response_model=LabDashboardOut)
def dashboard(
    db: DbSession,
    date_from: date | None = None,
    date_to: date | None = None,
    recent_limit: int = Query(default=100, ge=1, le=500),
) -> LabDashboardOut:
    end = date_to or datetime.now(ZoneInfo(get_settings().app_timezone)).date()
    start = date_from or end - timedelta(days=29)
    if start > end:
        raise HTTPException(status_code=422, detail="開始日は終了日以前にしてください")
    if (end - start).days > 89:
        raise HTTPException(status_code=422, detail="集計期間は最大90日です")
    return LabDashboardOut.model_validate(
        lab_dashboard(db, start, end, recent_limit)
    )


@router.post("/refresh", response_model=LabRefreshOut)
def refresh() -> LabRefreshOut:
    if not get_settings().live_strategy_lab_enabled:
        raise HTTPException(status_code=503, detail="LIVE買い方検証は無効です")
    return LabRefreshOut(**asdict(refresh_strategy_lab()))
