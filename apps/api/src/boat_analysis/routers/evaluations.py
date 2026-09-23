from datetime import date, timedelta

from fastapi import APIRouter, HTTPException

from ..database import DbSession
from ..schemas import EvaluationSummary, TwoBoatEvaluation
from ..services.evaluation import evaluate
from ..services.two_boat_flow import evaluate_two_boat_strategy

router = APIRouter(prefix="/evaluations", tags=["evaluations"])


@router.get("/summary", response_model=EvaluationSummary)
def evaluation_summary(
    db: DbSession,
    date_from: date | None = None,
    date_to: date | None = None,
) -> EvaluationSummary:
    return evaluate(db, date_from, date_to)


@router.get("/two-boat-flow", response_model=TwoBoatEvaluation)
def two_boat_flow_evaluation(
    date_from: date,
    date_to: date,
) -> TwoBoatEvaluation:
    if date_to < date_from:
        raise HTTPException(status_code=422, detail="終了日は開始日以降にしてください")
    if date_to - date_from > timedelta(days=90):
        raise HTTPException(status_code=422, detail="評価期間は最大90日です")
    return TwoBoatEvaluation.model_validate(evaluate_two_boat_strategy(date_from, date_to))
