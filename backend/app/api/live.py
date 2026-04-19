"""Live Signals API.

Endpoints:
  GET  /api/live/instruments                  — list live instruments
  POST /api/live/instruments/yfinance         — add via yfinance
  POST /api/live/instruments/upload           — add via file upload
  DELETE /api/live/instruments/{id}           — remove
  POST /api/live/compute                      — compute signals for an instrument
"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Body, File, Form, HTTPException, UploadFile

from app.schemas.live import (
    AddLiveYfinanceRequest,
    LiveComputeRequest,
    LiveComputeResult,
    LiveInstrument,
    LiveInstrumentList,
)
from app.services import live_instrument_service, signal_service
from app.services.instrument_service import InstrumentError

router = APIRouter(prefix="/live", tags=["live"])


@router.get("/instruments", response_model=LiveInstrumentList)
def list_instruments() -> LiveInstrumentList:
    return LiveInstrumentList(
        instruments=live_instrument_service.list_instruments()
    )


@router.post("/instruments/yfinance", response_model=LiveInstrument, status_code=201)
def add_yfinance(req: AddLiveYfinanceRequest = Body(...)) -> LiveInstrument:
    try:
        return live_instrument_service.add_from_yfinance(req.ticker)
    except InstrumentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/instruments/upload", response_model=LiveInstrument, status_code=201)
async def add_upload(
    label: str = Form(...),
    file: UploadFile = File(...),
) -> LiveInstrument:
    raw = await file.read()
    try:
        return live_instrument_service.add_from_upload(
            label, raw, file.filename or ""
        )
    except InstrumentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/instruments/{instrument_id}/refresh", response_model=LiveInstrument)
def refresh_instrument(instrument_id: str) -> LiveInstrument:
    try:
        return live_instrument_service.refresh_from_yfinance(instrument_id)
    except InstrumentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/instruments/{instrument_id}", status_code=204)
def delete_instrument(instrument_id: str) -> None:
    try:
        live_instrument_service.delete_instrument(instrument_id)
    except InstrumentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/compute", response_model=LiveComputeResult)
def compute(req: LiveComputeRequest = Body(...)) -> LiveComputeResult:
    try:
        inst = live_instrument_service.get_instrument(req.instrument_id)
        df = live_instrument_service.load_instrument_frame(req.instrument_id)
    except InstrumentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    date_end = req.date_end or date.today()
    date_start = req.date_start or (date_end - timedelta(days=2 * 365))

    return signal_service.compute_live(
        df=df,
        label=inst.label,
        instrument_id=inst.id,
        date_start=date_start,
        date_end=date_end,
        strategies=req.strategies,
    )
