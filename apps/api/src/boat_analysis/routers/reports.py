from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..config import get_settings
from ..services.daily_excel import DailyExcelNotReady, generate_daily_excel

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/daily.xlsx")
def download_daily_excel(race_date: date | None = None) -> FileResponse:
    timezone = ZoneInfo(get_settings().app_timezone)
    target_date = race_date or (datetime.now(timezone).date() - timedelta(days=1))
    try:
        path = generate_daily_excel(target_date)
    except DailyExcelNotReady as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return FileResponse(
        path,
        filename=path.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
