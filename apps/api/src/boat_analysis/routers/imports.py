from dataclasses import asdict
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException

from ..config import get_settings
from ..schemas import (
    BoatcastLapRefreshOut,
    ImportBatchOut,
    LiveRefreshOut,
    OfficialExhibitionRefreshOut,
    OfficialResultRefreshOut,
    OfficialWinOddsRefreshOut,
    SourceInspection,
)
from ..services.brd_importer import ImportAlreadyRunning
from ..services.importer import run_import
from ..services.official_exhibitions import refresh_official_exhibitions
from ..services.official_laps import refresh_boatcast_laps
from ..services.official_results import refresh_official_results
from ..services.official_win_odds import refresh_official_win_odds
from ..services.source_inspector import inspect_source

router = APIRouter(prefix="/imports", tags=["imports"])


@router.get("/source-schema", response_model=SourceInspection)
def source_schema() -> SourceInspection:
    try:
        return inspect_source()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/live-refresh", response_model=LiveRefreshOut)
def live_refresh() -> LiveRefreshOut:
    today = datetime.now(ZoneInfo(get_settings().app_timezone)).date()
    try:
        batch = ImportBatchOut.model_validate(run_import(date_from=today))
        official_win_odds = refresh_official_win_odds(today)
        official_exhibitions = refresh_official_exhibitions(today)
        boatcast_laps = refresh_boatcast_laps(today)
        official_results = refresh_official_results(today)
        return LiveRefreshOut(
            **batch.model_dump(),
            official_exhibitions=OfficialExhibitionRefreshOut(
                **asdict(official_exhibitions),
            ),
            official_results=OfficialResultRefreshOut(
                **asdict(official_results),
            ),
            official_win_odds=OfficialWinOddsRefreshOut(
                **asdict(official_win_odds),
            ),
            boatcast_laps=BoatcastLapRefreshOut(
                **asdict(boatcast_laps),
            ),
        )
    except ImportAlreadyRunning as exc:
        raise HTTPException(status_code=409, detail="更新処理はすでに実行中です") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
