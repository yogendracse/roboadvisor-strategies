from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health, instruments, live, strategies

app = FastAPI(
    title="Volatility Dashboard API",
    version="0.1.0",
    description="Multi-strategy backtesting & analysis backend",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api")
app.include_router(instruments.router, prefix="/api")
app.include_router(strategies.router, prefix="/api")
app.include_router(live.router, prefix="/api")
