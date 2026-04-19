from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = BACKEND_ROOT / "data"
TREND_DATA_DIR = DATA_DIR / "trend"
METADATA_PATH = DATA_DIR / "_metadata.json"

SP500_XLSX = BACKEND_ROOT / "SP data.xlsx"
TREND_XLSX = BACKEND_ROOT / "TREND_data.xlsx"

LIVE_DATA_DIR = DATA_DIR / "live"

DATA_DIR.mkdir(exist_ok=True)
TREND_DATA_DIR.mkdir(exist_ok=True)
LIVE_DATA_DIR.mkdir(exist_ok=True)

SP500_BUILTIN_ID = "sp500-builtin"
SP500_BUILTIN_LABEL = "S&P 500 (built-in)"

# Trend built-in instruments loaded from TREND_data.xlsx. Each sheet → (id, display label).
TREND_BUILTIN_SHEETS: dict[str, tuple[str, str]] = {
    "uro": ("euro-fx-builtin",    "Euro FX"),
    "ty":  ("10yr-note-builtin",  "10-Year Note"),
    "sp":  ("sp500-trend-builtin", "S&P 500"),
}

SECTORS = [
    "Unclassified",
    "Broad Market / Index",
    "Technology",
    "Financials",
    "Healthcare",
    "Consumer Discretionary",
    "Consumer Staples",
    "Energy",
    "Industrials",
    "Materials",
    "Real Estate",
    "Utilities",
    "Communication Services",
    "Commodities / Futures",
    "Fixed Income / Bonds",
    "Crypto",
]
