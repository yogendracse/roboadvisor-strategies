from fastapi import APIRouter, Body, File, Form, HTTPException, UploadFile

from app.core.config import SECTORS
from app.schemas.common import (
    AddResponse,
    AddYfinanceRequest,
    Instrument,
    InstrumentKind,
    InstrumentList,
    InstrumentSeries,
    SeriesPoint,
    UpdateSectorRequest,
)
from app.services import instrument_service
from app.services.instrument_service import InstrumentError

router = APIRouter(prefix="/instruments", tags=["instruments"])


@router.get("", response_model=InstrumentList)
def list_all(kind: InstrumentKind) -> InstrumentList:
    return InstrumentList(instruments=instrument_service.list_instruments(kind))


@router.get("/sectors", response_model=list[str])
def list_sectors() -> list[str]:
    return SECTORS


@router.get("/{kind}/{instrument_id}", response_model=Instrument)
def get_one(kind: InstrumentKind, instrument_id: str) -> Instrument:
    try:
        return instrument_service.get_instrument(kind, instrument_id)
    except InstrumentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{kind}/{instrument_id}/series", response_model=InstrumentSeries)
def get_series(kind: InstrumentKind, instrument_id: str) -> InstrumentSeries:
    try:
        inst = instrument_service.get_instrument(kind, instrument_id)
        df = instrument_service.load_instrument_frame(kind, instrument_id)
    except InstrumentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    points = [
        SeriesPoint(date=row.Date.date(), close=float(row.Close))
        for row in df.itertuples(index=False)
    ]
    return InstrumentSeries(
        id=inst.id, label=inst.label, kind=inst.kind, points=points
    )


@router.post("/yfinance", response_model=AddResponse, status_code=201)
def add_yfinance(req: AddYfinanceRequest = Body(...)) -> AddResponse:
    try:
        inst = instrument_service.add_from_yfinance(req.ticker, req.kind, req.sector)
    except InstrumentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AddResponse(instrument=inst)


@router.post("/upload", response_model=AddResponse, status_code=201)
async def add_upload(
    label: str = Form(...),
    kind: InstrumentKind = Form(...),
    sector: str | None = Form(default=None),
    file: UploadFile = File(...),
) -> AddResponse:
    raw = await file.read()
    try:
        inst = instrument_service.add_from_upload(
            label, kind, sector, raw, file.filename or ""
        )
    except InstrumentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AddResponse(instrument=inst)


@router.patch("/vol/{instrument_id}/sector", response_model=Instrument)
def update_sector(instrument_id: str, req: UpdateSectorRequest) -> Instrument:
    try:
        return instrument_service.update_sector(instrument_id, req.sector)
    except InstrumentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{kind}/{instrument_id}", status_code=204)
def delete_one(kind: InstrumentKind, instrument_id: str) -> None:
    try:
        instrument_service.delete_instrument(kind, instrument_id)
    except InstrumentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
