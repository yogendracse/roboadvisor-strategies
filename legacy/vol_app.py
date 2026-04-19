"""
Systematic Volatility Analysis — Interactive Streamlit Dashboard
S&P 500 · Lead-Lag between normalised volatility and future equity returns
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import timedelta

# ─────────────────────────────────────────────────────────────────────────────
# Page config
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Vol Analysis Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────────────────────────
# Colour palette (consistent across charts)
# ─────────────────────────────────────────────────────────────────────────────
PALETTE = {
    "price":   "#1565C0",
    "ret1":    "#2E7D32",
    "vol20":   "#7B1FA2",
    "ret20":   "#00838F",
    "fret20":  "#E65100",
    "zvol20":  "#7B1FA2",
    "zret20":  "#00838F",
    "zfret20": "#E65100",
    "strat":   "#D84315",
    "bh":      "#546E7A",
    "q":       ["#1565C0", "#5C9BD6", "#90A4AE", "#EF9A9A", "#C62828"],
}

# ─────────────────────────────────────────────────────────────────────────────
# Data loading — multiple sources
# ─────────────────────────────────────────────────────────────────────────────
import os, re, json

DATA_PATH      = "SP data.xlsx"
DATA_DIR       = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
TREND_DATA_DIR = os.path.join(DATA_DIR, "trend")
os.makedirs(DATA_DIR,       exist_ok=True)
os.makedirs(TREND_DATA_DIR, exist_ok=True)

METADATA_PATH = os.path.join(DATA_DIR, "_metadata.json")

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

SECTOR_COLOURS = {
    "Broad Market / Index":      "#1565C0",
    "Technology":                "#7B1FA2",
    "Financials":                "#1B5E20",
    "Healthcare":                "#BF360C",
    "Consumer Discretionary":    "#E65100",
    "Consumer Staples":          "#F9A825",
    "Energy":                    "#4E342E",
    "Industrials":               "#00695C",
    "Materials":                 "#37474F",
    "Real Estate":               "#880E4F",
    "Utilities":                 "#0D47A1",
    "Communication Services":    "#6A1B9A",
    "Commodities / Futures":     "#558B2F",
    "Fixed Income / Bonds":      "#00838F",
    "Crypto":                    "#FF6F00",
    "Unclassified":              "#9E9E9E",
}

def _safe_filename(label: str) -> str:
    """Convert an instrument label to a safe filename stem."""
    return re.sub(r"[^\w\-]", "_", label)

# ── Metadata helpers (sector tags + added date) ───────────────────────────────
def load_metadata() -> dict:
    if os.path.exists(METADATA_PATH):
        with open(METADATA_PATH) as f:
            return json.load(f)
    return {}

def save_metadata(meta: dict) -> None:
    with open(METADATA_PATH, "w") as f:
        json.dump(meta, f, indent=2)

def set_instrument_meta(label: str, sector: str) -> None:
    meta = load_metadata()
    meta[label] = {"sector": sector}
    save_metadata(meta)

def delete_instrument_meta(label: str) -> None:
    meta = load_metadata()
    meta.pop(label, None)
    save_metadata(meta)

def get_sector(label: str) -> str:
    return load_metadata().get(label, {}).get("sector", "Unclassified")

# ── Instrument CSV helpers ────────────────────────────────────────────────────
def save_instrument(label: str, df: pd.DataFrame) -> None:
    """Persist an instrument's Date+Close to data/<label>.csv."""
    path = os.path.join(DATA_DIR, f"{_safe_filename(label)}.csv")
    df[["Date", "Close"]].to_csv(path, index=False)

def delete_instrument(label: str) -> None:
    """Remove a saved instrument CSV from disk."""
    path = os.path.join(DATA_DIR, f"{_safe_filename(label)}.csv")
    if os.path.exists(path):
        os.remove(path)

def list_saved_instruments() -> dict:
    """Return {label: DataFrame} for every CSV saved in DATA_DIR."""
    result = {}
    for fname in sorted(os.listdir(DATA_DIR)):
        if not fname.endswith(".csv"):
            continue
        label = fname[:-4]          # strip .csv
        path  = os.path.join(DATA_DIR, fname)
        try:
            df = pd.read_csv(path, parse_dates=["Date"])
            df = df.sort_values("Date").reset_index(drop=True)
            df["ret1"] = df["Close"].pct_change()
            result[label] = df
        except Exception:
            pass
    return result

def _trend_csv_path(label: str) -> str:
    return os.path.join(TREND_DATA_DIR, f"{_safe_filename(label)}.csv")

def save_trend_instrument(label: str, df: pd.DataFrame) -> None:
    """Persist Date+Close to data/trend/<label>.csv."""
    df[["Date", "Close"]].to_csv(_trend_csv_path(label), index=False)

def delete_trend_instrument(label: str) -> None:
    p = _trend_csv_path(label)
    if os.path.exists(p):
        os.remove(p)

def list_saved_trend_instruments() -> dict:
    """Return {label: DataFrame(Date,Close,log_ret)} for every CSV in data/trend/."""
    result = {}
    for fname in sorted(os.listdir(TREND_DATA_DIR)):
        if not fname.endswith(".csv"):
            continue
        label = fname[:-4]
        try:
            df = pd.read_csv(os.path.join(TREND_DATA_DIR, fname), parse_dates=["Date"])
            df = (df.sort_values("Date")
                    .drop_duplicates("Date")
                    .reset_index(drop=True))
            df["log_ret"] = np.log(df["Close"] / df["Close"].shift(1))
            result[label] = df
        except Exception:
            pass
    return result

@st.cache_data
def load_sp500_excel() -> pd.DataFrame:
    df = pd.read_excel(DATA_PATH, usecols=["Date", "Close"])
    df = df.sort_values("Date").reset_index(drop=True)
    df["ret1"] = df["Close"].pct_change()
    return df

@st.cache_data(ttl=3600)
def fetch_ticker(ticker: str) -> pd.DataFrame:
    import yfinance as yf
    raw = yf.Ticker(ticker).history(period="max")[["Close"]].copy()
    raw.index = pd.to_datetime(raw.index).tz_localize(None)
    raw = raw.reset_index().rename(columns={"Date": "Date", "Close": "Close"})
    raw = raw.sort_values("Date").reset_index(drop=True)
    raw["ret1"] = raw["Close"].pct_change()
    return raw

@st.cache_data
def load_uploaded(file_bytes: bytes, filename: str) -> pd.DataFrame:
    if filename.endswith(".csv"):
        df = pd.read_csv(pd.io.common.BytesIO(file_bytes))
    else:
        df = pd.read_excel(pd.io.common.BytesIO(file_bytes))
    # Normalise column names — accept "Date"/"date", "Close"/"close"/"Adj Close"
    df.columns = [c.strip() for c in df.columns]
    col_map = {}
    for c in df.columns:
        if c.lower() in ("date", "time", "datetime"):
            col_map[c] = "Date"
        elif c.lower() in ("close", "adj close", "adjusted close", "price"):
            col_map[c] = "Close"
    df = df.rename(columns=col_map)[["Date", "Close"]].copy()
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values("Date").reset_index(drop=True)
    df["ret1"] = df["Close"].pct_change()
    return df

# ─────────────────────────────────────────────────────────────────────────────
# Trend Following — data loading, signals, backtest, portfolio
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_data
def load_trend_data():
    """Parse TREND_data.xlsx: sheets uro/sp/ty → {name: DataFrame(Date,Syn,log_ret)}."""
    xl = pd.ExcelFile("TREND_data.xlsx")
    SHEET_MAP = {"uro": "Euro FX", "sp": "S&P 500", "ty": "10-Year Note"}
    assets = {}
    for sheet, name in SHEET_MAP.items():
        raw = xl.parse(sheet, header=None)
        # Row 0 = group labels (ignored), Row 1 = real column names, Row 2+ = data
        df = raw.iloc[2:].reset_index(drop=True)
        # Column layout: 0=Date, 1=Open, 2=High, 3=Low, 4=Close, ..., 8=SynXXX
        df = df.iloc[:, [0, 8]].copy()
        df.columns = ["Date", "Syn"]
        df["Date"] = pd.to_datetime(df["Date"].astype(str).str.strip(),
                                    format="%Y%m%d", errors="coerce")
        df["Syn"]  = pd.to_numeric(df["Syn"], errors="coerce")
        df = (df.dropna()
                .sort_values("Date")
                .drop_duplicates(subset=["Date"], keep="last")
                .reset_index(drop=True))
        df["log_ret"] = np.log(df["Syn"] / df["Syn"].shift(1))
        assets[name] = df
    return assets


def _ma(series, window, use_ema):
    return series.ewm(span=window, adjust=False).mean() if use_ema else series.rolling(window).mean()


def calc_ma_signal(price, fast, slow, use_ema=False):
    """±1 MA-crossover signal; NaN for the first `slow` rows (burn-in)."""
    fast_ma = _ma(price, fast, use_ema)
    slow_ma = _ma(price, slow, use_ema)
    sig = pd.Series(np.where(fast_ma > slow_ma, 1.0, -1.0), index=price.index)
    sig.iloc[:slow] = np.nan
    return sig, fast_ma, slow_ma


def calc_breakout_signal(price, window=30):
    """±1 30-day breakout signal with forward-fill; NaN for first `window` rows."""
    hi = price.rolling(window).max().shift(1)
    lo = price.rolling(window).min().shift(1)
    sig = pd.Series(np.nan, index=price.index, dtype=float)
    sig[price > hi] =  1.0
    sig[price < lo] = -1.0
    sig.iloc[:window] = np.nan
    sig = sig.ffill()
    return sig


def run_backtest(log_rets, signal, tc_bps=1):
    """
    Vectorized backtest.
    System return = prev-day signal × today log return − transaction cost.
    Returns (net_ret Series, equity curve Series, drawdown Series).
    """
    sig = signal.reindex(log_rets.index)
    sys_ret = sig.shift(1) * log_rets
    tc      = (tc_bps / 10_000) * sig.diff().abs().fillna(0)
    net_ret = (sys_ret - tc).dropna()
    eq  = np.exp(net_ret.cumsum())
    dd  = eq / eq.cummax() - 1
    return net_ret, eq, dd


def calc_trend_metrics(daily_rets):
    """Annualised Sharpe, Sortino, max-drawdown, return, vol."""
    r = daily_rets.dropna()
    if len(r) < 20:
        return dict(ann_ret=0.0, ann_vol=0.0, sharpe=0.0, sortino=0.0, max_dd=0.0)
    mu  = r.mean()
    sd  = r.std()
    ann_ret = mu * 252
    ann_vol = sd * np.sqrt(252)
    sharpe  = ann_ret / ann_vol if ann_vol > 0 else 0.0
    neg = r[r < 0]
    sor_den = neg.std() * np.sqrt(252) if len(neg) > 1 else np.nan
    sortino = ann_ret / sor_den if (sor_den and sor_den > 0) else 0.0
    eq  = np.exp(r.cumsum())
    max_dd = (eq / eq.cummax() - 1).min()
    return dict(ann_ret=ann_ret, ann_vol=ann_vol, sharpe=sharpe,
                sortino=sortino, max_dd=max_dd)


def build_portfolio(best_rets_dict, lookback_vol=20):
    """
    Combine per-asset best-system return series into:
      - equal-weight portfolio (1/3 each)
      - inverse-volatility-weight portfolio (trailing 20-day σ)
    Returns (eq_ret, iv_ret) as daily log-return Series.
    """
    df = pd.concat(best_rets_dict, axis=1).dropna()
    eq_ret = df.mean(axis=1)                          # equal weight = 1/3 each

    roll_vol = df.rolling(lookback_vol).std()
    inv_vol  = 1.0 / roll_vol.replace(0, np.nan)
    weights  = inv_vol.div(inv_vol.sum(axis=1), axis=0)
    iv_ret   = (weights.shift(1) * df).sum(axis=1)
    iv_ret   = iv_ret.iloc[lookback_vol + 1:]

    return eq_ret, iv_ret


def top_drawdowns(eq, n=5):
    """Return a DataFrame of the top-N drawdown episodes (by depth)."""
    dd   = eq / eq.cummax() - 1
    rows = []
    in_dd       = False
    peak_date   = None
    trough_date = None
    trough_val  = 0.0

    for date, val in dd.items():
        if val < 0:
            if not in_dd:
                in_dd     = True
                candidates = eq.loc[:date]
                peak_date  = candidates.idxmax()
                trough_val  = val
                trough_date = date
            elif val < trough_val:
                trough_val  = val
                trough_date = date
        else:
            if in_dd:
                peak_level  = eq[peak_date]
                future      = eq.loc[trough_date:]
                recovered   = future[future >= peak_level]
                rec_date    = recovered.index[0] if len(recovered) else None
                rows.append(dict(
                    Peak         = peak_date.date(),
                    Trough       = trough_date.date(),
                    Recovery     = rec_date.date() if rec_date else "Not recovered",
                    **{"Max Drawdown": f"{trough_val:.2%}"},
                    **{"Duration (days)": (trough_date - peak_date).days},
                    **{"Recovery (days)": (rec_date - trough_date).days if rec_date else "N/A"},
                ))
                in_dd = False; trough_val = 0.0
    if in_dd:
        rows.append(dict(
            Peak         = peak_date.date(),
            Trough       = trough_date.date(),
            Recovery     = "Not recovered",
            **{"Max Drawdown": f"{trough_val:.2%}"},
            **{"Duration (days)": (trough_date - peak_date).days},
            **{"Recovery (days)": "N/A"},
        ))
    if not rows:
        return pd.DataFrame()
    pain_df = pd.DataFrame(rows)
    pain_df["_depth"] = pain_df["Max Drawdown"].str.replace("%","").astype(float)
    return pain_df.sort_values("_depth").head(n).drop("_depth", axis=1).reset_index(drop=True)


# ─────────────────────────────────────────────────────────────────────────────
# Data pipeline — cached so it only re-runs when parameters change
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data
def build_pipeline(window: int, norm_win: int, n_quantiles: int,
                   date_start: str, date_end: str,
                   # pass raw df via hash-friendly json string to allow caching
                   _raw_df: pd.DataFrame):
    df = _raw_df.copy()

    # Apply date filter on the raw frame so rolling windows start fresh
    df = df[(df["Date"] >= date_start) & (df["Date"] <= date_end)].reset_index(drop=True)

    # ── Phase 2: indicators ──────────────────────────────────────────────────
    df["vol20"]  = df["ret1"].rolling(window).std()
    df["ret20"]  = df["Close"].pct_change(periods=window)
    df["fret20"] = df["ret20"].shift(-window)

    # ── Phase 3: Z-score normalisation ──────────────────────────────────────
    def rzs(s, w):
        return (s - s.rolling(w).mean()) / s.rolling(w).std(ddof=1)

    df["zvol20"]  = rzs(df["vol20"],  norm_win)
    df["zret20"]  = rzs(df["ret20"],  norm_win)
    df["zfret20"] = rzs(df["fret20"], norm_win)

    burned_head = window + norm_win
    burned_tail = window

    df_clean = df.dropna(subset=["zvol20", "zret20", "zfret20"]).copy().reset_index(drop=True)

    # ── Phase 4: quintiles ───────────────────────────────────────────────────
    labels = list(range(1, n_quantiles + 1))
    df_clean["quintile"] = pd.qcut(df_clean["zvol20"], q=n_quantiles,
                                   labels=labels, duplicates="drop").astype(int)

    df_sorted = df_clean.sort_values("zvol20").reset_index(drop=True)
    df_sorted["quintile"] = pd.qcut(df_sorted["zvol20"], q=n_quantiles,
                                    labels=labels, duplicates="drop").astype(int)

    qs = (df_sorted.groupby("quintile", observed=True)
          .agg(count=("zvol20","count"),
               avg_zvol20=("zvol20","mean"),
               avg_zret20=("zret20","mean"),
               avg_zfret20=("zfret20","mean"))
          .reset_index())
    qs["quintile"] = qs["quintile"].astype(int)

    return df, df_clean, qs, burned_head, burned_tail

def compute_strategy(df_clean, long_q, short_q, n_quantiles):
    """Build signal, returns, rolling IR/Sharpe, and cumulative equity."""
    dc = df_clean.copy()
    labels = list(range(1, n_quantiles + 1))
    dc["quintile"] = pd.qcut(dc["zvol20"], q=n_quantiles,
                             labels=labels, duplicates="drop").astype(int)

    dc["signal"] = np.where(dc["quintile"] == long_q,  1,
                   np.where(dc["quintile"] == short_q, -1, 0))
    dc["strat_ret"]  = dc["signal"] * dc["fret20"]
    dc["bh_ret"]     = dc["fret20"]

    # Cumulative wealth
    dc["cum_strat"] = (1 + dc["strat_ret"].fillna(0)).cumprod()
    dc["cum_bh"]    = (1 + dc["bh_ret"].fillna(0)).cumprod()

    # Rolling IR (60-obs window on active only, then reindex)
    active_ret = dc["strat_ret"].where(dc["signal"] != 0)
    roll_mean  = active_ret.rolling(60, min_periods=20).mean() * 252
    roll_std   = active_ret.rolling(60, min_periods=20).std()  * np.sqrt(252)
    dc["rolling_ir"] = roll_mean / roll_std.replace(0, np.nan)

    # Overall metrics
    active = dc.loc[dc["signal"] != 0, "strat_ret"]
    if len(active) < 5:
        ir = sharpe = 0.0
    else:
        ann_ret = active.mean() * 252
        ann_std = active.std()  * np.sqrt(252)
        ir      = ann_ret / ann_std if ann_std else 0.0
        # Sharpe: subtract a simple 0% risk-free (or pass rf as param)
        rf_daily = 0.0   # kept at 0 for simplicity; editable below
        exc      = active - rf_daily
        sharpe   = (exc.mean() * 252) / (exc.std() * np.sqrt(252)) if exc.std() else 0.0

    win_rate  = (active > 0).mean() if len(active) else 0.0
    ann_ret_v = active.mean() * 252 if len(active) else 0.0
    ann_std_v = active.std()  * np.sqrt(252) if len(active) else 0.0
    max_dd    = ((dc["cum_strat"] / dc["cum_strat"].cummax()) - 1).min()

    metrics = dict(ir=ir, sharpe=sharpe, win_rate=win_rate,
                   ann_ret=ann_ret_v, ann_std=ann_std_v, max_dd=max_dd,
                   n_active=len(active))
    return dc, metrics

# ─────────────────────────────────────────────────────────────────────────────
# Sidebar controls
# ─────────────────────────────────────────────────────────────────────────────
# ── Strategy selector (always visible at top of sidebar) ─────────────────────
with st.sidebar:
    st.title("⚙️ Controls")
    strategy_mode = st.radio(
        "Strategy",
        ["📊 Vol Analysis", "📈 Trend Following"],
        horizontal=True,
    )
    st.markdown("---")

# ── Vol Analysis sidebar (only when that strategy is selected) ────────────────
if strategy_mode == "📊 Vol Analysis":
  with st.sidebar:

    # ── Stock / instrument selector ──────────────────────────────────────────
    st.subheader("📌 Instrument")

    # Initialise the catalogue in session state — load from disk on first run
    if "catalogue" not in st.session_state:
        sp_df = load_sp500_excel()
        st.session_state.catalogue = {"S&P 500 (built-in)": sp_df}
        st.session_state.active    = "S&P 500 (built-in)"
        # Restore any previously saved instruments from data/
        for label, df in list_saved_instruments().items():
            if label not in st.session_state.catalogue:
                st.session_state.catalogue[label] = df

    # Show where data is stored
    st.caption(f"💾 Saved to: `{DATA_DIR}`")

    # Add a ticker via yfinance
    with st.expander("➕ Add ticker (yfinance)", expanded=False):
        new_ticker = st.text_input("Ticker symbol", placeholder="e.g. AAPL, MSFT, TSLA").upper().strip()
        new_sector = st.selectbox("Sector", SECTORS, key="sector_ticker")
        if st.button("Fetch & add", use_container_width=True) and new_ticker:
            with st.spinner(f"Fetching {new_ticker}…"):
                try:
                    fetched = fetch_ticker(new_ticker)
                    if len(fetched) < 100:
                        st.error(f"Too little data returned for {new_ticker}.")
                    else:
                        save_instrument(new_ticker, fetched)
                        set_instrument_meta(new_ticker, new_sector)
                        st.session_state.catalogue[new_ticker] = fetched
                        st.session_state.active = new_ticker
                        st.session_state.ds = fetched["Date"].min().date()
                        st.session_state.de = fetched["Date"].max().date()
                        st.success(f"Added {new_ticker} · {new_sector} ({len(fetched):,} rows)")
                except Exception as exc:
                    st.error(f"Could not fetch {new_ticker}: {exc}")

    # Upload a CSV / Excel file
    with st.expander("📂 Upload CSV / Excel", expanded=False):
        uploaded = st.file_uploader(
            "File must have a Date column and a Close (or Price) column",
            type=["csv", "xlsx", "xls"],
        )
        upload_name   = st.text_input("Label for this dataset", placeholder="My Stock")
        upload_sector = st.selectbox("Sector", SECTORS, key="sector_upload")
        if st.button("Add uploaded file", use_container_width=True) and uploaded and upload_name:
            try:
                up_df = load_uploaded(uploaded.read(), uploaded.name)
                save_instrument(upload_name, up_df)
                set_instrument_meta(upload_name, upload_sector)
                st.session_state.catalogue[upload_name] = up_df
                st.session_state.active = upload_name
                st.session_state.ds = up_df["Date"].min().date()
                st.session_state.de = up_df["Date"].max().date()
                st.success(f"Added '{upload_name}' · {upload_sector} ({len(up_df):,} rows)")
            except Exception as exc:
                st.error(f"Could not parse file: {exc}")

    # Edit sector of existing instrument
    with st.expander("✏️ Edit sector", expanded=False):
        edit_target = st.selectbox("Instrument", list(st.session_state.catalogue.keys()), key="edit_target")
        cur_sector  = get_sector(edit_target)
        new_sec_val = st.selectbox("New sector", SECTORS,
                                   index=SECTORS.index(cur_sector) if cur_sector in SECTORS else 0,
                                   key="edit_sector_val")
        if st.button("Save sector", use_container_width=True):
            set_instrument_meta(edit_target, new_sec_val)
            st.success(f"'{edit_target}' → {new_sec_val}")

    # Remove instruments
    removable = [k for k in st.session_state.catalogue if k != "S&P 500 (built-in)"]
    if removable:
        with st.expander("🗑️ Remove instrument", expanded=False):
            to_remove = st.selectbox("Select to remove", removable)
            if st.button("Remove", use_container_width=True):
                delete_instrument(to_remove)
                delete_instrument_meta(to_remove)
                del st.session_state.catalogue[to_remove]
                if st.session_state.active == to_remove:
                    st.session_state.active = list(st.session_state.catalogue.keys())[0]
                st.success(f"Removed '{to_remove}' from memory and disk.")

    # Active instrument selector
    active_name = st.selectbox(
        "Active instrument",
        list(st.session_state.catalogue.keys()),
        index=list(st.session_state.catalogue.keys()).index(st.session_state.active),
    )
    # If the user switches instruments, reset date window to that instrument's full range
    if active_name != st.session_state.active:
        st.session_state.active = active_name
        new_df = st.session_state.catalogue[active_name]
        st.session_state.ds = new_df["Date"].min().date()
        st.session_state.de = new_df["Date"].max().date()

    raw_df   = st.session_state.catalogue[st.session_state.active]
    min_date = raw_df["Date"].min().date()
    max_date = raw_df["Date"].max().date()

    st.markdown("---")

    # ── Date Range ───────────────────────────────────────────────────────────
    st.subheader("📅 Date Range")

    # Clamp session state to this instrument's available range
    if "ds" not in st.session_state or st.session_state.ds < min_date:
        st.session_state.ds = min_date
    if "de" not in st.session_state or st.session_state.de > max_date:
        st.session_state.de = max_date

    SHIFT_YEARS = 10
    SHIFT_DAYS  = int(SHIFT_YEARS * 365.25)

    def shift_window(days):
        new_ds = st.session_state.ds + timedelta(days=days)
        new_de = st.session_state.de + timedelta(days=days)
        if new_ds < min_date:
            delta  = min_date - new_ds
            new_ds, new_de = min_date, new_de + delta
        if new_de > max_date:
            delta  = new_de - max_date
            new_ds, new_de = new_ds - delta, max_date
        st.session_state.ds = max(new_ds, min_date)
        st.session_state.de = new_de

    period_years = round((st.session_state.de - st.session_state.ds).days / 365.25, 1)
    st.caption(f"Window: **{period_years}y** · "
               f"{st.session_state.ds} → {st.session_state.de}")

    b_prev, b_label, b_next = st.columns([1, 1.4, 1])
    with b_prev:
        if st.button(f"◀ {SHIFT_YEARS}y", use_container_width=True,
                     help=f"Shift window {SHIFT_YEARS} years earlier"):
            shift_window(-SHIFT_DAYS)
    with b_label:
        st.markdown(f"<div style='text-align:center;padding-top:6px;font-size:12px;"
                    f"color:#555'>shift {SHIFT_YEARS}-year window</div>",
                    unsafe_allow_html=True)
    with b_next:
        if st.button(f"{SHIFT_YEARS}y ▶", use_container_width=True,
                     help=f"Shift window {SHIFT_YEARS} years later"):
            shift_window(+SHIFT_DAYS)

    picked = st.date_input(
        "Or pick a custom range",
        value=(st.session_state.ds, st.session_state.de),
        min_value=min_date,
        max_value=max_date,
    )
    if isinstance(picked, (list, tuple)) and len(picked) == 2:
        st.session_state.ds, st.session_state.de = picked[0], picked[1]

    date_start = st.session_state.ds
    date_end   = st.session_state.de

    st.markdown("---")
    st.subheader("📐 Rolling Windows")
    window = st.slider("Analysis window (days)", 5, 63, 20, 1,
                       help="Window for vol20, ret20, fret20")
    norm_win = st.slider("Z-score normalisation window (days)", 60, 500, 250, 10,
                         help="Trailing window for rolling Z-score")

    st.markdown("---")
    st.subheader("🗂️ Quantile Settings")
    n_quantiles = st.slider("Number of quantiles", 3, 10, 5, 1)
    long_q  = st.selectbox("Long quantile",  list(range(1, n_quantiles + 1)),
                            index=n_quantiles - 1, format_func=lambda x: f"Q{x}")
    short_q = st.selectbox("Short quantile", list(range(1, n_quantiles + 1)),
                            index=0, format_func=lambda x: f"Q{x}")

    st.markdown("---")
    st.subheader("🔁 Chart Overlays")
    show_ret1_on_price  = st.toggle("Daily returns on price chart",   value=True)
    show_vol_on_ret20   = st.toggle("vol20 overlay on ret20 chart",   value=True)
    show_fret_on_ret20  = st.toggle("fret20 overlay on ret20 chart",  value=True)
    show_raw_on_z       = st.toggle("Raw vol20 behind zvol20 chart",  value=True)
    show_rolling_ir     = st.toggle("Rolling IR on equity curve",     value=True)

# ─────────────────────────────────────────────────────────────────────────────
# TREND FOLLOWING sidebar
# ─────────────────────────────────────────────────────────────────────────────
elif strategy_mode == "📈 Trend Following":
    with st.sidebar:
        st.subheader("⚙️ System Settings")
        tc_bps  = st.slider("Transaction cost (bps / trade)", 0, 5, 1)
        use_ema = st.toggle("Use EMA instead of SMA", value=False)

        st.markdown("---")
        st.subheader("➕ Add Instrument")

        # Initialise session state — restore any previously saved instruments from disk
        if "trend_extra" not in st.session_state:
            st.session_state.trend_extra = {}
            for _lbl, _df in list_saved_trend_instruments().items():
                st.session_state.trend_extra[_lbl] = _df

        with st.expander("➕ Add ticker (yfinance)", expanded=False):
            _tf_ticker = st.text_input("Ticker symbol", placeholder="e.g. GLD, TLT, USO",
                                       key="tf_ticker").upper().strip()
            if st.button("Fetch & add", key="tf_fetch", use_container_width=True) and _tf_ticker:
                with st.spinner(f"Fetching {_tf_ticker}…"):
                    try:
                        import yfinance as yf
                        _raw = yf.Ticker(_tf_ticker).history(period="max")[["Close"]].copy()
                        _raw.index = pd.to_datetime(_raw.index).tz_localize(None)
                        _raw = (_raw.reset_index()
                                    .sort_values("Date")
                                    .drop_duplicates("Date")
                                    .reset_index(drop=True))
                        _raw["log_ret"] = np.log(_raw["Close"] / _raw["Close"].shift(1))
                        if len(_raw) < 200:
                            st.error(f"Too little data for {_tf_ticker}.")
                        else:
                            save_trend_instrument(_tf_ticker, _raw)          # persist to disk
                            st.session_state.trend_extra[_tf_ticker] = _raw
                            st.success(
                                f"Added **{_tf_ticker}** — "
                                f"{len(_raw):,} rows · "
                                f"{_raw['Date'].min().date()} → {_raw['Date'].max().date()} · "
                                f"saved to `data/trend/`"
                            )
                    except Exception as _ex:
                        st.error(f"Could not fetch {_tf_ticker}: {_ex}")

        with st.expander("📂 Upload CSV / Excel", expanded=False):
            _tf_file = st.file_uploader(
                "Needs a Date column + Close (or Price) column",
                type=["csv", "xlsx", "xls"], key="tf_upload",
            )
            _tf_label = st.text_input("Label for this instrument", placeholder="My Asset",
                                      key="tf_ulabel")
            if st.button("Add uploaded file", key="tf_uadd", use_container_width=True) \
                    and _tf_file and _tf_label:
                try:
                    _ub = _tf_file.read()
                    _udf = (pd.read_csv(pd.io.common.BytesIO(_ub))
                            if _tf_file.name.endswith(".csv")
                            else pd.read_excel(pd.io.common.BytesIO(_ub)))
                    _udf.columns = [c.strip() for c in _udf.columns]
                    _ucm = {}
                    for _c in _udf.columns:
                        if _c.lower() in ("date", "time", "datetime"):  _ucm[_c] = "Date"
                        elif _c.lower() in ("close", "adj close", "price"): _ucm[_c] = "Close"
                    _udf = _udf.rename(columns=_ucm)[["Date", "Close"]].copy()
                    _udf["Date"] = pd.to_datetime(_udf["Date"])
                    _udf = (_udf.sort_values("Date")
                                .drop_duplicates("Date")
                                .reset_index(drop=True))
                    _udf["log_ret"] = np.log(_udf["Close"] / _udf["Close"].shift(1))
                    save_trend_instrument(_tf_label, _udf)                   # persist to disk
                    st.session_state.trend_extra[_tf_label] = _udf
                    st.success(
                        f"Added **'{_tf_label}'** — "
                        f"{len(_udf):,} rows · "
                        f"{_udf['Date'].min().date()} → {_udf['Date'].max().date()} · "
                        f"saved to `data/trend/`"
                    )
                except Exception as _ex:
                    st.error(f"Could not parse file: {_ex}")

        # Saved instruments list + remove
        _saved_trend = list_saved_trend_instruments()
        if _saved_trend:
            st.caption(f"💾 {len(_saved_trend)} instrument(s) saved in `data/trend/`")
            with st.expander("🗑️ Remove instrument", expanded=False):
                _to_rm = st.selectbox("Select to remove",
                                      list(_saved_trend.keys()),
                                      key="tf_remove")
                if st.button("Remove", key="tf_rm_btn", use_container_width=True):
                    delete_trend_instrument(_to_rm)                          # remove from disk
                    st.session_state.trend_extra.pop(_to_rm, None)
                    st.success(f"Removed '{_to_rm}' from memory and disk.")

        st.markdown("---")
        # ── Date range ────────────────────────────────────────────────────────────
        # min_value = earliest data across all instruments
        # max_value = today (picker never rejects "Past N years" shortcuts;
        #             the data slice stops at the last available row automatically)
        from datetime import date as _date_cls
        _tf_min = pd.Timestamp("1999-03-08").date()
        for _edf_tmp in st.session_state.get("trend_extra", {}).values():
            _tf_min = min(_tf_min, _edf_tmp["Date"].min().date())
        _tf_max = _date_cls.today()

        st.subheader("📅 Date Range")
        if "tf_ds" not in st.session_state or st.session_state.tf_ds < _tf_min:
            st.session_state.tf_ds = _tf_min
        if "tf_de" not in st.session_state:
            st.session_state.tf_de = _tf_max

        _tf_picked = st.date_input(
            "Select date range",
            value=(st.session_state.tf_ds, st.session_state.tf_de),
            min_value=_tf_min,
            max_value=_tf_max,
        )
        if isinstance(_tf_picked, (list, tuple)) and len(_tf_picked) == 2:
            st.session_state.tf_ds, st.session_state.tf_de = _tf_picked[0], _tf_picked[1]
        trend_ds = st.session_state.tf_ds
        trend_de = st.session_state.tf_de
        st.caption(f"{trend_ds} → {trend_de}")

        st.markdown("---")
        st.subheader("📊 Best System per Asset")
        st.caption("Used in the Portfolio tab to build the combo.")
        _SYSNAMES = ["10/30 MA", "30/100 MA", "80/160 MA", "30-Day Breakout"]
        best_uro = st.selectbox("Euro FX",       _SYSNAMES, index=2)
        best_ty  = st.selectbox("10-Year Note",  _SYSNAMES, index=2)
        best_sp  = st.selectbox("S&P 500",       _SYSNAMES, index=2)
        # Dynamic best-system selectors for added instruments
        _extra_best = {}
        for _elbl in st.session_state.get("trend_extra", {}):
            _extra_best[_elbl] = st.selectbox(
                _elbl, _SYSNAMES, index=2, key=f"best_{_elbl}"
            )

        st.markdown("---")
        st.caption(
            "Built-in data: TREND_data.xlsx · 1999–2010\n\n"
            "Instruments: Euro FX, 10-Year Note, S&P 500\n\n"
            "Systems: 3 MA crossovers + 30-Day Breakout"
        )

# ─────────────────────────────────────────────────────────────────────────────
# TREND FOLLOWING — main content
# st.stop() at the end prevents the Vol Analysis pipeline from running.
# ─────────────────────────────────────────────────────────────────────────────
if strategy_mode == "📈 Trend Following":
    # ── Load & filter data ────────────────────────────────────────────────────
    try:
        trend_assets = load_trend_data()
    except Exception as _e:
        st.error(f"Could not load TREND_data.xlsx: {_e}")
        st.stop()

    _BUILTIN_NAMES  = ["Euro FX", "10-Year Note", "S&P 500"]
    _EXTRA_NAMES    = list(st.session_state.get("trend_extra", {}).keys())
    _ASSET_NAMES    = _BUILTIN_NAMES + _EXTRA_NAMES

    # Colour palette — built-ins fixed, extras get auto-assigned from a pool
    _EXTRA_COLOUR_POOL = ["#FF6F00", "#00695C", "#6A1B9A", "#37474F", "#AD1457",
                          "#0277BD", "#558B2F", "#4E342E"]
    _ASSET_COLORS = {
        "Euro FX":       "#1565C0",
        "10-Year Note":  "#2E7D32",
        "S&P 500":       "#B71C1C",
    }
    for _i, _en in enumerate(_EXTRA_NAMES):
        _ASSET_COLORS[_en] = _EXTRA_COLOUR_POOL[_i % len(_EXTRA_COLOUR_POOL)]

    # Filter to selected date range and pre-compute all signals & backtests
    _SYSTEMS = [
        ("10/30 MA",        10,  30,  False),
        ("30/100 MA",       30,  100, False),
        ("80/160 MA",       80,  160, False),
        ("30-Day Breakout", None, None, False),
    ]
    _BEST_MAP = {
        "Euro FX":      best_uro,
        "10-Year Note": best_ty,
        "S&P 500":      best_sp,
        **_extra_best,
    }

    # results[asset][system_name] = {net_ret, eq, dd, metrics, signal, fast_ma, slow_ma}
    # Skip assets that have no data in the selected date window (e.g. built-ins when
    # the user has scrolled the window into a period covered only by added instruments).
    # ── Compute signals on FULL history, then slice results to display window ───
    # This is the correct approach: MAs need prior data for burn-in. Filtering
    # first then computing signals gives wrong/empty results for short windows.
    results       = {}
    _active_names = []
    _skipped      = {}

    _ds = pd.Timestamp(trend_ds)
    _de = pd.Timestamp(trend_de)

    for aname in _ASSET_NAMES:
        # Load FULL price history (no date filter yet)
        if aname in _BUILTIN_NAMES:
            adf   = trend_assets[aname].copy()
            price_full   = adf.set_index("Date")["Syn"]
            log_ret_full = adf.set_index("Date")["log_ret"]
        else:
            _edf = st.session_state.trend_extra[aname].copy()
            price_full   = _edf.set_index("Date")["Close"]
            log_ret_full = _edf.set_index("Date")["log_ret"]

        # Check the instrument has any data in the display window at all
        _in_window = price_full.loc[_ds:_de]
        if len(_in_window) == 0:
            _skipped[aname] = 0
            continue

        results[aname] = {}
        _active_names.append(aname)

        for sname, fast, slow, _ema in _SYSTEMS:
            # Compute signal on FULL series
            if sname == "30-Day Breakout":
                sig_full = calc_breakout_signal(price_full, window=30)
                fm_full = sm_full = None
            else:
                sig_full, fm_full, sm_full = calc_ma_signal(
                    price_full, fast, slow, use_ema=use_ema
                )

            # Run backtest on FULL series (equity curve starts from day 1)
            net_full, eq_full, dd_full = run_backtest(
                log_ret_full, sig_full, tc_bps=tc_bps
            )

            # Slice everything to the display window
            sig     = sig_full.loc[_ds:_de]
            net_ret = net_full.loc[_ds:_de]
            price_w = price_full.loc[_ds:_de]
            fm      = fm_full.loc[_ds:_de]  if fm_full is not None else None
            sm      = sm_full.loc[_ds:_de]  if sm_full is not None else None

            # Re-base equity curve so it starts at 1.0 within the window
            if len(net_ret) > 0:
                eq  = np.exp(net_ret.cumsum())
                eq  = eq / eq.iloc[0]          # re-base to 1.0
                dd  = eq / eq.cummax() - 1
            else:
                eq = pd.Series(dtype=float)
                dd = pd.Series(dtype=float)

            results[aname][sname] = dict(
                net_ret=net_ret, eq=eq, dd=dd,
                metrics=calc_trend_metrics(net_ret),
                signal=sig, fast_ma=fm, slow_ma=sm,
                price=price_w, log_ret=log_ret_full.loc[_ds:_de],
            )

    _ASSET_NAMES = _active_names

    if not _ASSET_NAMES:
        _skip_lines = "\n".join(
            f"- **{n}**: no data in this window" for n in _skipped
        )
        st.warning(
            f"**No instruments have data in {trend_ds} → {trend_de}.**\n\n"
            f"{_skip_lines}\n\n"
            "Adjust the date range in the sidebar."
        )
        st.stop()

    if _skipped:
        st.info(
            "**Skipped (no data in window):** " +
            ", ".join(_skipped.keys()) +
            ". These instruments have no prices in the selected date range."
        )

    # ── Page header ───────────────────────────────────────────────────────────
    st.title("📈 Trend Following Dashboard")
    _header_assets = " · ".join(_ASSET_NAMES)
    st.caption(
        f"{_header_assets}  ·  {trend_ds} → {trend_de}  ·  "
        f"Transaction cost: **{tc_bps} bp**  ·  "
        f"MA type: **{'EMA' if use_ema else 'SMA'}**"
    )

    tab_a, tab_b, tab_c, tab_d = st.tabs([
        "📉 Signals & Prices",
        "🔁 Backtest",
        "💼 Portfolio",
        "🔬 Insights",
    ])

    # ═══════════════════════════════════════════════════════════════════════════
    # TAB A — Signals & Prices
    # ═══════════════════════════════════════════════════════════════════════════
    with tab_a:
        st.subheader("Price Chart with MA Lines & Signal Overlay")
        st.caption(
            "Green shading = Long (+1), Red shading = Short (−1). "
            "Select system and asset to inspect."
        )

        with st.expander("📖 How do these signals work? — Plain-language guide", expanded=False):
            st.markdown("""
**Trend following in one sentence:** *ride the wave in whatever direction the market is moving, and flip when it changes.*

---

**Moving Average Crossover systems (10/30, 30/100, 80/160)**

A moving average (MA) smooths out daily price noise by averaging the last N closing prices.
We use two MAs — a *fast* one (shorter window) and a *slow* one (longer window).

> **Signal rule:** If fast MA > slow MA → market is trending UP → go **Long (+1)**.
> If fast MA < slow MA → market is trending DOWN → go **Short (−1)**.

The fast MA reacts quickly to price moves; the slow MA reacts slowly. When the fast
line crosses above the slow line, it's the first sign that a new uptrend may be forming.

*What the chart shows:* the orange dashed line is the fast MA, the purple dotted line
is the slow MA. The crossover points are where the signal flips. Green background =
you're long (betting it goes up). Red background = you're short (betting it goes down).

---

**30-Day Breakout system**

Instead of MAs, this system looks at the *range* of the past 30 trading days.

> **Signal rule:** If today's price > 30-day high (set yesterday) → go **Long (+1)**.
> If today's price < 30-day low (set yesterday) → go **Short (−1)**.
> Otherwise: *hold your current position* (forward-fill).

The breakout system is more patient — it only acts when price breaks out of a
well-established range, capturing the "fat tail" moves that MAs sometimes miss.

---

**What to look for in this chart:**

- **2008 crash period:** Does the signal flip to Short early enough to avoid the worst
  of the drawdown? Slower systems (80/160) tend to stay short longer and ride the recovery.
- **Choppy markets (e.g., 2004–2006):** Fast systems (10/30) generate many more
  signal flips (colour changes). Each flip is a trade — and each trade costs money.
  This is *whiplash* — the enemy of fast systems.
- **Trend persistence:** Long stretches of solid green or solid red are profitable
  regimes for trend followers. Frequent alternating green/red = choppy, costly markets.
            """)

        col_sys, col_asset = st.columns(2)
        sel_sys   = col_sys.selectbox("System",  [s[0] for s in _SYSTEMS], key="ta_sys")
        sel_asset = col_asset.selectbox("Asset", _ASSET_NAMES, key="ta_asset")

        r = results[sel_asset][sel_sys]
        price_s = r["price"]
        sig_s   = r["signal"].reindex(price_s.index)

        fig_a = make_subplots(
            rows=2, cols=1, shared_xaxes=True,
            row_heights=[0.7, 0.3], vertical_spacing=0.04,
        )

        # Signal background shading — one vrect per contiguous run
        def _signal_runs(sig):
            """Yield (start_date, end_date, value) for each contiguous signal block."""
            clean = sig.dropna()
            if clean.empty:
                return
            prev_val  = clean.iloc[0]
            run_start = clean.index[0]
            for dt, val in clean.items():
                if val != prev_val:
                    yield run_start, dt, prev_val
                    run_start = dt
                    prev_val  = val
            yield run_start, clean.index[-1], prev_val

        # add_vrect has unreliable subplot support — use add_shape with
        # yref="y domain" to reliably fill the full height of row 1 only.
        _shade_colours = {1: "rgba(46,125,50,0.25)", -1: "rgba(198,40,40,0.25)"}
        for _s, _e, _v in _signal_runs(sig_s):
            if _v in _shade_colours:
                fig_a.add_shape(
                    type="rect",
                    xref="x", yref="y domain",
                    x0=_s, x1=_e, y0=0, y1=1,
                    fillcolor=_shade_colours[_v],
                    layer="below", line_width=0,
                    row=1, col=1,
                )

        # Price line
        fig_a.add_trace(go.Scatter(
            x=price_s.index, y=price_s,
            name="Price (Syn)", line=dict(color=_ASSET_COLORS[sel_asset], width=1.5),
        ), row=1, col=1)

        # MA lines (if applicable)
        if r["fast_ma"] is not None:
            fast_label = f"Fast MA ({_SYSTEMS[[s[0] for s in _SYSTEMS].index(sel_sys)][1]})"
            slow_label = f"Slow MA ({_SYSTEMS[[s[0] for s in _SYSTEMS].index(sel_sys)][2]})"
            fig_a.add_trace(go.Scatter(
                x=r["fast_ma"].index, y=r["fast_ma"],
                name=fast_label, line=dict(color="#FF6F00", width=1, dash="dash"),
            ), row=1, col=1)
            fig_a.add_trace(go.Scatter(
                x=r["slow_ma"].index, y=r["slow_ma"],
                name=slow_label, line=dict(color="#7B1FA2", width=1, dash="dot"),
            ), row=1, col=1)

        # Signal line
        fig_a.add_trace(go.Scatter(
            x=sig_s.index, y=sig_s,
            name="Signal (±1)", line=dict(color="#37474F", width=1),
            fill="tozeroy", fillcolor="rgba(55,71,79,0.08)",
        ), row=2, col=1)
        fig_a.add_hline(y=0, line_dash="dash", line_color="#9E9E9E",
                        line_width=0.8, row=2, col=1)

        fig_a.update_yaxes(title_text="Index Level", row=1, col=1)
        fig_a.update_yaxes(title_text="Signal", row=2, col=1, tickvals=[-1, 0, 1])
        fig_a.update_layout(
            height=520, hovermode="x unified",
            template="plotly_white",
            legend=dict(orientation="h", y=1.03),
            margin=dict(t=10, b=10),
        )
        st.plotly_chart(fig_a, use_container_width=True)

    # ═══════════════════════════════════════════════════════════════════════════
    # TAB B — Backtest
    # ═══════════════════════════════════════════════════════════════════════════
    with tab_b:
        st.subheader("System Equity Curves & Performance")
        st.caption(
            "Each panel shows one asset. All four systems are overlaid. "
            "First 160 days excluded (80/160 burn-in)."
        )

        with st.expander("📖 How to read these backtests — Plain-language guide", expanded=False):
            st.markdown("""
**What is an equity curve?**

An equity curve shows the growth of $1 invested in a strategy over time.
If the curve ends at **1.35**, the strategy turned $1 into $1.35 — a 35% cumulative return.
A flat curve means the system broke even. A falling curve means it lost money.

---

**How system returns are calculated:**

> *System Return (today) = Yesterday's Signal × Today's Log Return − Transaction Cost*

We use **yesterday's** signal — not today's — to avoid lookahead bias. You can only
trade on a signal you already knew. Today's return is the log return of the synthetic
continuous-contract price.

**Transaction cost** is deducted every time the signal *flips* (from +1 to −1 or vice versa).
Even a small cost (1 bp) adds up significantly for the 10/30 system, which flips
many more times than the 80/160 system.

---

**The burn-in period:**

The 80/160 system needs 160 days of prices before it can produce its first signal.
Reporting performance from day 1 would be misleading — the MA hasn't "warmed up" yet.
So the equity curves only start after the **160-day burn-in** is complete (~August 1999).
All systems use this same start date for a fair comparison.

---

**Reading the Sharpe bar chart:**

The Sharpe Ratio is the classic measure of risk-adjusted return:

> *Sharpe = (Annualised Return) ÷ (Annualised Volatility)*

A Sharpe above **0.5** is considered strong for a systematic strategy. A Sharpe near 0
means the strategy earned a return but it wasn't worth the risk. Negative = lost money
on a risk-adjusted basis.

**Key comparison:** The bar chart lets you spot whether the *slowest* system (80/160)
consistently beats the *fastest* (10/30) after costs — the "Speed Decay" pattern.
If 80/160 has a higher Sharpe across all three assets, that confirms the Winton finding
that slower systems are more robust to noise.

---

**What to look for:**

- Does any single system dominate across all three assets? Or does the best system
  differ by asset? (This is why the Portfolio tab lets you pick the best per asset.)
- Do the equity curves stay relatively smooth, or do they have sharp drops?
  Sharp drops = high drawdown = dangerous for real-world clients who may panic-sell.
- Compare the 2008–2009 period: does the short signal protect the portfolio?
  Trend-following strategies often do well in *crises* — one of their key selling points.
            """)

        # ── Equity curves: one row per asset ─────────────────────────────────
        _SYS_COLORS = {
            "10/30 MA":        "#E65100",
            "30/100 MA":       "#1565C0",
            "80/160 MA":       "#2E7D32",
            "30-Day Breakout": "#7B1FA2",
        }

        fig_b = make_subplots(
            rows=len(_ASSET_NAMES), cols=1,
            shared_xaxes=True,
            subplot_titles=_ASSET_NAMES,
            vertical_spacing=0.08,
        )
        for ai, aname in enumerate(_ASSET_NAMES, start=1):
            for sname, *_ in _SYSTEMS:
                r = results[aname][sname]
                eq = r["eq"]
                fig_b.add_trace(go.Scatter(
                    x=eq.index, y=eq,
                    name=sname if ai == 1 else sname,
                    legendgroup=sname,
                    showlegend=(ai == 1),
                    line=dict(color=_SYS_COLORS[sname], width=1.4),
                ), row=ai, col=1)
            fig_b.update_yaxes(title_text="Equity", row=ai, col=1)

        fig_b.update_layout(
            height=700, hovermode="x unified",
            template="plotly_white",
            legend=dict(orientation="h", y=1.01),
            margin=dict(t=40, b=10),
        )
        st.plotly_chart(fig_b, use_container_width=True)

        # ── Sharpe comparison bar chart ────────────────────────────────────────
        st.markdown("#### Sharpe Ratio by System & Asset")
        sharpe_rows = []
        for aname in _ASSET_NAMES:
            for sname, *_ in _SYSTEMS:
                m = results[aname][sname]["metrics"]
                sharpe_rows.append(dict(Asset=aname, System=sname, Sharpe=m["sharpe"]))
        sharpe_df = pd.DataFrame(sharpe_rows)

        fig_sh = go.Figure()
        for sname, *_ in _SYSTEMS:
            sub = sharpe_df[sharpe_df["System"] == sname]
            fig_sh.add_trace(go.Bar(
                name=sname,
                x=sub["Asset"],
                y=sub["Sharpe"],
                marker_color=_SYS_COLORS[sname],
                text=[f"{v:.2f}" for v in sub["Sharpe"]],
                textposition="outside",
            ))
        fig_sh.add_hline(y=0, line_dash="dash", line_color="#424242", line_width=0.8)
        fig_sh.update_layout(
            barmode="group", height=350, template="plotly_white",
            legend=dict(orientation="h", y=1.04),
            yaxis_title="Annualised Sharpe",
            margin=dict(t=20, b=20),
        )
        st.plotly_chart(fig_sh, use_container_width=True)

        # ── Metrics table ──────────────────────────────────────────────────────
        st.markdown("#### Full Metrics Table")
        met_rows = []
        for aname in _ASSET_NAMES:
            for sname, *_ in _SYSTEMS:
                m = results[aname][sname]["metrics"]
                met_rows.append(dict(
                    Asset=aname, System=sname,
                    **{"Ann. Return": f"{m['ann_ret']:.2%}"},
                    **{"Ann. Vol":    f"{m['ann_vol']:.2%}"},
                    **{"Sharpe":      f"{m['sharpe']:.3f}"},
                    **{"Sortino":     f"{m['sortino']:.3f}"},
                    **{"Max DD":      f"{m['max_dd']:.2%}"},
                ))
        st.dataframe(pd.DataFrame(met_rows), use_container_width=True, hide_index=True)

    # ═══════════════════════════════════════════════════════════════════════════
    # TAB C — Portfolio
    # ═══════════════════════════════════════════════════════════════════════════
    with tab_c:
        st.subheader("Portfolio Aggregator")
        st.caption(
            "Combine the best system per asset into Equal-Weight and "
            "Inverse-Volatility-Weight portfolios."
        )

        with st.expander("📖 Why build a portfolio? — Plain-language guide", expanded=False):
            st.markdown("""
**The core problem with a single system on a single asset:**

Any single strategy has good years and bad years. A 10/30 MA on Euro FX might
outperform for a few years, then underperform when the Euro enters a choppy, range-bound
period. You can't know in advance which system or asset will perform best next year.

**The solution: diversify across uncorrelated signals.**

If Euro FX trend signals are *uncorrelated* with 10-Year Note trend signals, then when
one is losing, the other is likely doing something different — maybe even profiting.
Combining them produces a smoother ride than either alone.

> The mathematical intuition: if two uncorrelated assets both have Sharpe = 0.3,
> combining them equally produces a portfolio with Sharpe ≈ **0.42** — a 40% improvement,
> for free, just through diversification.

---

**Equal Weight (1/3 each asset):**

The simplest possible combination. Each asset's best-system return is weighted equally.
No views on which asset is "better" — pure democracy. The risk is that if one asset
becomes very volatile (e.g., S&P 500 in 2008), it dominates and overwhelms the others.

---

**Inverse Volatility Weight ("Risk Parity"):**

Instead of weighting equally by *capital*, we weight equally by *risk*.

> *Weight for asset i = (1 / trailing 20-day volatility of asset i) ÷ sum of all weights*

If S&P 500 becomes twice as volatile as Euro FX, it gets half the weight.
The "robot" automatically pulls back from the most dangerous asset — no human
judgement required. This is what keeps a systematic manager alive during crises.

**Expected result:** During the 2008 drawdown, the Inverse Vol portfolio should
have a *smaller* maximum drawdown than Equal Weight — because it automatically
reduced S&P 500 exposure as that market became more volatile.

---

**Reading the correlation heatmap:**

Each cell shows the correlation (ρ) between two assets' daily returns.
- **ρ ≈ 0**: uncorrelated — combining them provides maximum diversification benefit.
- **ρ ≈ +1**: highly correlated — moving together, no diversification benefit.
- **ρ ≈ −1**: inversely correlated — when one gains the other loses (rare in trend-following).

If all three assets have near-zero correlations with each other, the combo curve
will be noticeably smoother than any individual equity curve. This is the
*whole point* of building a multi-asset systematic portfolio.
            """)

        st.info(
            f"**Best system selection (set in sidebar):**  "
            f"Euro FX → **{best_uro}** · "
            f"10-Year Note → **{best_ty}** · "
            f"S&P 500 → **{best_sp}**"
        )

        best_rets = {
            aname: results[aname][_BEST_MAP[aname]]["net_ret"]
            for aname in _ASSET_NAMES
        }
        eq_ret, iv_ret = build_portfolio(best_rets)

        eq_eq  = np.exp(eq_ret.cumsum())
        iv_eq  = np.exp(iv_ret.cumsum())
        eq_dd  = eq_eq / eq_eq.cummax() - 1
        iv_dd  = iv_eq / iv_eq.cummax() - 1

        eq_m = calc_trend_metrics(eq_ret)
        iv_m = calc_trend_metrics(iv_ret)

        # KPI strip
        k1, k2, k3, k4, k5, k6 = st.columns(6)
        k1.metric("EW Sharpe",    f"{eq_m['sharpe']:.3f}")
        k2.metric("IV Sharpe",    f"{iv_m['sharpe']:.3f}")
        k3.metric("EW Max DD",    f"{eq_m['max_dd']:.1%}")
        k4.metric("IV Max DD",    f"{iv_m['max_dd']:.1%}")
        k5.metric("EW Ann. Ret",  f"{eq_m['ann_ret']:.1%}")
        k6.metric("IV Ann. Ret",  f"{iv_m['ann_ret']:.1%}")

        # Equity curves
        st.markdown("#### Equal Weight vs Inverse Volatility Weight — Equity Curves")
        fig_c1 = go.Figure()
        for eq_s, name, colour in [
            (eq_eq, "Equal Weight (1/3 each)", "#1565C0"),
            (iv_eq, "Inverse Vol Weight",      "#B71C1C"),
        ]:
            fig_c1.add_trace(go.Scatter(
                x=eq_s.index, y=eq_s, name=name,
                line=dict(color=colour, width=2),
            ))
        fig_c1.update_layout(
            yaxis_title="Cumulative Return", height=380,
            hovermode="x unified", template="plotly_white",
            legend=dict(orientation="h", y=1.04),
            margin=dict(t=10, b=10),
        )
        st.plotly_chart(fig_c1, use_container_width=True)

        # Drawdown chart
        st.markdown("#### Drawdown")
        fig_c2 = go.Figure()
        for dd_s, name, colour, fill in [
            (eq_dd, "Equal Weight",       "#1565C0", "rgba(21,101,192,0.12)"),
            (iv_dd, "Inverse Vol Weight", "#B71C1C", "rgba(183,28,28,0.12)"),
        ]:
            fig_c2.add_trace(go.Scatter(
                x=dd_s.index, y=dd_s * 100, name=name,
                line=dict(color=colour, width=1.2),
                fill="tozeroy", fillcolor=fill,
            ))
        fig_c2.update_layout(
            yaxis_title="Drawdown (%)", height=280,
            hovermode="x unified", template="plotly_white",
            legend=dict(orientation="h", y=1.04),
            margin=dict(t=10, b=10),
        )
        st.plotly_chart(fig_c2, use_container_width=True)

        # Correlation heatmap of best-system returns
        st.markdown("#### Return Correlation — Best System per Asset")
        corr_df = pd.concat(best_rets, axis=1).dropna().corr()
        fig_corr = go.Figure(go.Heatmap(
            z=corr_df.values,
            x=corr_df.columns.tolist(),
            y=corr_df.index.tolist(),
            colorscale="RdBu", zmid=0, zmin=-1, zmax=1,
            text=[[f"{v:.2f}" for v in row] for row in corr_df.values],
            texttemplate="%{text}",
            colorbar=dict(title="ρ"),
        ))
        fig_corr.update_layout(
            height=340, template="plotly_white",
            margin=dict(t=20, b=20),
        )
        st.plotly_chart(fig_corr, use_container_width=True)
        st.caption(
            "Near-zero correlations between assets confirm diversification. "
            "The combo curve should be smoother than any individual equity curve."
        )

    # ═══════════════════════════════════════════════════════════════════════════
    # TAB D — Insights
    # ═══════════════════════════════════════════════════════════════════════════
    with tab_d:
        st.subheader("Strategic Insights")

        ins1, ins2, ins3, ins4 = st.tabs([
            "⚡ Speed Decay",
            "🌐 Diversification",
            "🩸 Pain Table",
            "📐 Sortino vs Sharpe",
        ])

        # ── Insight 1: Speed Decay ─────────────────────────────────────────────
        with ins1:
            st.markdown("#### Speed Decay — Sharpe by System Speed")

            with st.expander("📖 What is Speed Decay and why does it happen? — Plain-language guide", expanded=True):
                st.markdown("""
**The central question:** Does trading faster make more money?

Intuitively, you might think more signals = more opportunities = more profit.
The data — and the Winton research paper — consistently says the opposite.

---

**Why slower systems tend to win:**

**1. Transaction costs compound against fast systems.**
The 10/30 system might flip its signal 40–60 times per year per asset.
At even 1 bp per trade, that's 40–60 bps of annual drag — before you've made a penny.
The 80/160 system might flip 8–12 times per year. Much lower cost leakage.

**2. Noise vs. signal.**
Daily price moves are mostly noise — random fluctuations with no predictive power.
A fast MA reacts to this noise, triggering trades that are quickly reversed.
This is called *whiplash*: you buy on a brief uptick, it reverses, you sell at a loss.
A slow MA ignores short-term noise and only responds to genuine, sustained trends.

**3. The Winton finding:**
Their research showed that raw returns (before costs) are similar across speeds,
but *after costs*, slower systems significantly outperform faster ones.
The 10/30 system has to overcome a much higher transaction-cost hurdle.

---

**Reading the charts:**

- **Sharpe bar chart:** Look for a left-to-right decline — 10/30 should have the lowest
  Sharpe, 80/160 the highest. If it's not monotone, that asset had an unusual regime
  where short-term momentum persisted.
- **Sortino line chart:** If Sortino follows the same pattern as Sharpe, the slow
  system's advantage comes from *both* higher returns and smaller downside moves —
  it's genuinely better, not just less volatile.

**Try it:** Increase the transaction cost in the sidebar to 3 bps.
The fast system's Sharpe should collapse while the slow system's barely moves.
That's the cost sensitivity that makes 10/30 impractical in live trading.
                """)

            speed_rows = []
            for aname in _ASSET_NAMES:
                for sname, *_ in _SYSTEMS:
                    m = results[aname][sname]["metrics"]
                    speed_rows.append(dict(
                        Asset=aname, System=sname,
                        Sharpe=m["sharpe"], Sortino=m["sortino"],
                        **{"Ann. Return": m["ann_ret"]},
                    ))
            speed_df = pd.DataFrame(speed_rows)

            fig_d1 = go.Figure()
            for aname in _ASSET_NAMES:
                sub = speed_df[speed_df["Asset"] == aname]
                fig_d1.add_trace(go.Bar(
                    name=aname,
                    x=sub["System"],
                    y=sub["Sharpe"],
                    marker_color=_ASSET_COLORS[aname],
                    text=[f"{v:.2f}" for v in sub["Sharpe"]],
                    textposition="outside",
                ))
            fig_d1.add_hline(y=0, line_dash="dash", line_color="#424242", line_width=0.8)
            fig_d1.update_layout(
                barmode="group", height=360, template="plotly_white",
                yaxis_title="Sharpe Ratio",
                legend=dict(orientation="h", y=1.04),
                margin=dict(t=20, b=20),
            )
            st.plotly_chart(fig_d1, use_container_width=True)

            # Sortino line plot
            fig_d1b = go.Figure()
            for aname in _ASSET_NAMES:
                sub = speed_df[speed_df["Asset"] == aname]
                fig_d1b.add_trace(go.Scatter(
                    x=sub["System"], y=sub["Sortino"],
                    name=aname, mode="lines+markers",
                    line=dict(color=_ASSET_COLORS[aname], width=2),
                    marker=dict(size=8),
                ))
            fig_d1b.add_hline(y=0, line_dash="dash", line_color="#424242", line_width=0.8)
            fig_d1b.update_layout(
                title="Sortino Ratio by System (higher = better downside management)",
                height=300, template="plotly_white",
                yaxis_title="Sortino",
                legend=dict(orientation="h", y=1.04),
                margin=dict(t=40, b=10),
            )
            st.plotly_chart(fig_d1b, use_container_width=True)

        # ── Insight 2: Diversification ─────────────────────────────────────────
        with ins2:
            st.markdown("#### Diversification — Individual vs Combo Equity Curves")

            with st.expander("📖 Why does combining uncorrelated assets improve the portfolio? — Plain-language guide", expanded=True):
                st.markdown("""
**The intuition: wiggles cancel out.**

Imagine two strategies. Strategy A earns +1% in January and −1% in February.
Strategy B earns −1% in January and +1% in February. Neither is impressive alone.
But combined 50/50, you earn 0% both months — no loss, no gain, but *no volatility*.
A portfolio with no volatility has an *infinite* Sharpe ratio.

In practice, correlations are never perfectly −1. But even moving from ρ = +0.8
to ρ = 0.0 has a dramatic effect on portfolio smoothness.

---

**The free lunch of diversification:**

For N uncorrelated strategies each with Sharpe S, the combined portfolio Sharpe is:

> *Portfolio Sharpe ≈ S × √N*

For 3 strategies each with Sharpe 0.3:
- Combined Sharpe ≈ 0.3 × √3 ≈ **0.52**

That's a significant improvement — achieved without changing any individual strategy.
This is the only genuine *free lunch* in finance.

---

**Why Euro FX, 10-Year Note, and S&P 500?**

These three assets are structurally different:
- **Euro FX** trends are driven by central bank policy divergence (ECB vs. Fed).
- **10-Year Note** trends are driven by inflation expectations and Fed rate cycles.
- **S&P 500** trends are driven by corporate earnings cycles and risk appetite.

These drivers are *largely independent* — an equity bear market doesn't necessarily
cause a bond bull market to end, and currency trends can run in either direction
during both. This is why the correlations between their signals should be near zero.

---

**Reading the charts:**

- **Overlay chart:** The thick grey combo line should be *smoother* than any individual
  dotted line. If individual lines show sharp drops in 2008, the combo should show
  a much smaller dip (if bond trends were positive at the same time).
- **Full correlation matrix:** Look at the cross-asset correlations (e.g., "Eur 80/160 MA"
  vs "S&P 80/160 MA"). Near-zero values confirm the diversification works as intended.
  High values would mean these systems move together — dangerous correlation.
                """)

            fig_d2 = go.Figure()
            for aname in _ASSET_NAMES:
                r = results[aname][_BEST_MAP[aname]]
                indiv_eq = r["eq"]
                fig_d2.add_trace(go.Scatter(
                    x=indiv_eq.index, y=indiv_eq,
                    name=f"{aname} ({_BEST_MAP[aname]})",
                    line=dict(color=_ASSET_COLORS[aname], width=1.2, dash="dot"),
                ))

            # Equal-weight combo
            best_rets_d2 = {aname: results[aname][_BEST_MAP[aname]]["net_ret"]
                            for aname in _ASSET_NAMES}
            eq_ret_d2, _ = build_portfolio(best_rets_d2)
            eq_eq_d2 = np.exp(eq_ret_d2.cumsum())
            fig_d2.add_trace(go.Scatter(
                x=eq_eq_d2.index, y=eq_eq_d2,
                name="Combo (Equal Weight)",
                line=dict(color="#37474F", width=2.5),
            ))
            fig_d2.update_layout(
                yaxis_title="Cumulative Return", height=400,
                hovermode="x unified", template="plotly_white",
                legend=dict(orientation="h", y=1.04),
                margin=dict(t=10, b=10),
            )
            st.plotly_chart(fig_d2, use_container_width=True)

            # Full pairwise correlation heatmap
            st.markdown("#### Full Correlation Matrix of All System Returns")
            all_ret_cols = {}
            for aname in _ASSET_NAMES:
                for sname, *_ in _SYSTEMS:
                    all_ret_cols[f"{aname[:3]} {sname}"] = results[aname][sname]["net_ret"]
            all_corr = pd.concat(all_ret_cols, axis=1).dropna().corr()
            fig_d2b = go.Figure(go.Heatmap(
                z=all_corr.values,
                x=all_corr.columns.tolist(),
                y=all_corr.index.tolist(),
                colorscale="RdBu", zmid=0, zmin=-1, zmax=1,
                text=[[f"{v:.2f}" for v in row] for row in all_corr.values],
                texttemplate="%{text}",
                textfont=dict(size=8),
                colorbar=dict(title="ρ"),
            ))
            fig_d2b.update_layout(
                height=480, template="plotly_white",
                margin=dict(t=20, b=20),
            )
            st.plotly_chart(fig_d2b, use_container_width=True)

        # ── Insight 3: Pain Table ──────────────────────────────────────────────
        with ins3:
            st.markdown("#### Drawdown Pain Table — Top 5 Worst Episodes")

            with st.expander("📖 What is a drawdown and why does it matter so much? — Plain-language guide", expanded=True):
                st.markdown("""
**What is a drawdown?**

A drawdown measures how far the portfolio has fallen from its most recent all-time high.

> *Drawdown (%) = (Current Equity − Peak Equity) / Peak Equity*

If your portfolio peaked at $150 and is now at $120, you're in a −20% drawdown.
The drawdown ends (recovers) when the portfolio surpasses the previous peak — $150.

---

**Why drawdowns are the real test of a strategy:**

Returns are easy to love. Drawdowns are the price you pay for those returns.

A strategy might have an excellent 10-year Sharpe ratio, but if it had a −35% drawdown
at some point, most human investors — and most institutional clients — would have
**withdrawn their money at the bottom**. This is the *behavioural* problem that kills
otherwise good systematic strategies.

The question isn't just "does this strategy work?" — it's "can you stomach it
when it isn't working?"

---

**The 'Rumsfeldian Unknown' column — Recovery Time:**

The most psychologically important number in the table is *how long* recovery took.
A −20% drawdown that recovers in 3 months feels completely different from one that
takes 18 months to recover.

During those 18 months:
- Clients are calling to redeem.
- The manager is being second-guessed by their board.
- The temptation to "override the robot" is at its highest.

The systematic manager's discipline is tested precisely when it looks *most* broken.
The managers who survived — like those at Winton, AHL, Renaissance — did so because
they committed to rules-based execution even during these drawdown periods.

---

**Reading the table and chart:**

- **Duration (days):** Days from peak to trough. Short durations are less psychologically damaging.
- **Recovery (days):** Days from trough back to the old peak. "Not recovered" means
  the portfolio never fully bounced back within the sample period — the worst outcome.
- **The −10% and −20% reference lines** on the chart: Drawdowns below −10% start to
  feel painful to clients; below −20% is where redemptions typically accelerate.

**Try comparing:** Switch between the Equal-Weight Combo and individual assets.
The combo should have both smaller *depth* and shorter *recovery time* than the
worst individual asset — demonstrating the protective effect of diversification.
                """)

            pain_asset = st.selectbox(
                "Inspect portfolio or asset",
                ["Equal-Weight Combo"] + _ASSET_NAMES,
                key="pain_asset",
            )
            if pain_asset == "Equal-Weight Combo":
                _eq_for_pain = np.exp(eq_ret.cumsum())
            else:
                _eq_for_pain = results[pain_asset][_BEST_MAP[pain_asset]]["eq"]

            pain_df = top_drawdowns(_eq_for_pain, n=5)
            if pain_df.empty:
                st.info("No completed drawdown episodes found.")
            else:
                st.dataframe(pain_df, use_container_width=True, hide_index=True)

            # Drawdown chart with episodes highlighted
            _dd_series = _eq_for_pain / _eq_for_pain.cummax() - 1
            fig_pain = go.Figure()
            fig_pain.add_trace(go.Scatter(
                x=_dd_series.index, y=_dd_series * 100,
                name="Drawdown (%)",
                fill="tozeroy", fillcolor="rgba(198,40,40,0.15)",
                line=dict(color="#B71C1C", width=1),
            ))
            fig_pain.add_hline(y=-10, line_dash="dot", line_color="#FF6F00",
                               line_width=0.8,
                               annotation_text="-10%", annotation_position="left")
            fig_pain.add_hline(y=-20, line_dash="dot", line_color="#B71C1C",
                               line_width=0.8,
                               annotation_text="-20%", annotation_position="left")
            fig_pain.update_layout(
                yaxis_title="Drawdown (%)", height=300,
                hovermode="x unified", template="plotly_white",
                margin=dict(t=10, b=10),
            )
            st.plotly_chart(fig_pain, use_container_width=True)

        # ── Insight 4: Sortino vs Sharpe ───────────────────────────────────────
        with ins4:
            st.markdown("#### Fat-Tail Capture — Sortino vs Sharpe Comparison")

            with st.expander("📖 Why does Sortino tell a different story to Sharpe? — Plain-language guide", expanded=True):
                st.markdown("""
**The problem with Sharpe for trend-following strategies:**

The Sharpe ratio uses *total* standard deviation in the denominator — it treats a
+5% day and a −5% day as equally "risky." But for an investor, these are completely
different events. A +5% day is wonderful; a −5% day is painful.

Penalising large *gains* as if they were risk is wrong for strategies designed to
catch fat-tail moves. It systematically understates the quality of breakout systems.

---

**What the Sortino ratio fixes:**

> *Sortino = (Annualised Return) ÷ (Downside Deviation × √252)*

Downside deviation only measures the standard deviation of *negative* daily returns.
Positive days — no matter how large — don't count against you.

For a strategy with symmetric gains and losses, Sharpe ≈ Sortino.
For a strategy that *cuts losses short and lets winners run* (the trend-follower's
mantra), Sortino >> Sharpe. The ratio between them tells you how asymmetric the
return distribution is.

---

**Why breakout systems should show the biggest Sortino/Sharpe gap:**

The 30-Day Breakout system is specifically designed to enter *only* when price breaks
out of its range — i.e., only when a strong trend is already forming. It misses many
small moves (lower raw return), but when it is in a trade, the trade tends to be a
big, fat-tail move.

These large positive returns inflate Sharpe's denominator (standard deviation)
but do NOT inflate Sortino's denominator (downside deviation only).
So the Sortino ratio should be the highest for the Breakout system relative to its Sharpe.

---

**Reading the charts:**

- **Grouped bar chart:** For each system/asset combination, compare the blue (Sharpe)
  and green (Sortino) bar heights. A taller green bar = more asymmetric return distribution.
  If Sortino ≈ Sharpe, the strategy has symmetric wins and losses.
- **Scatter plot:** Points above the diagonal (Sortino = Sharpe line) have asymmetric
  *upside* returns — the good kind. Points on the Breakout row should cluster furthest
  above the diagonal. Points *below* the diagonal would mean the strategy has more
  large losses than large gains — dangerous.

**The practical implication:**
When pitching a trend-following fund to investors, Sortino is a better risk metric
than Sharpe — it doesn't penalise the very large gains that justify the strategy's
occasional drawdowns.
                """)

            sor_rows = []
            for aname in _ASSET_NAMES:
                for sname, *_ in _SYSTEMS:
                    m = results[aname][sname]["metrics"]
                    sor_rows.append(dict(
                        Label=f"{aname[:3]} {sname}",
                        Sharpe=m["sharpe"],
                        Sortino=m["sortino"],
                        System=sname,
                        Asset=aname,
                    ))
            sor_df = pd.DataFrame(sor_rows)

            fig_d4 = go.Figure()
            fig_d4.add_trace(go.Bar(
                name="Sharpe",
                x=sor_df["Label"],
                y=sor_df["Sharpe"],
                marker_color="#1565C0",
                opacity=0.75,
            ))
            fig_d4.add_trace(go.Bar(
                name="Sortino",
                x=sor_df["Label"],
                y=sor_df["Sortino"],
                marker_color="#2E7D32",
                opacity=0.75,
            ))
            fig_d4.add_hline(y=0, line_dash="dash", line_color="#424242", line_width=0.8)
            fig_d4.update_layout(
                barmode="group", height=420, template="plotly_white",
                yaxis_title="Ratio",
                legend=dict(orientation="h", y=1.04),
                xaxis_tickangle=-35,
                margin=dict(t=20, b=60),
            )
            st.plotly_chart(fig_d4, use_container_width=True)

            # Scatter: Sharpe vs Sortino coloured by system type
            fig_d4b = go.Figure()
            for sname, *_ in _SYSTEMS:
                sub = sor_df[sor_df["System"] == sname]
                fig_d4b.add_trace(go.Scatter(
                    x=sub["Sharpe"], y=sub["Sortino"],
                    mode="markers+text",
                    name=sname,
                    text=sub["Asset"].str[:3],
                    textposition="top center",
                    marker=dict(color=_SYS_COLORS[sname], size=12, opacity=0.85),
                ))
            # Diagonal reference line (Sortino = Sharpe)
            diag_range = [sor_df[["Sharpe","Sortino"]].values.min() - 0.1,
                          sor_df[["Sharpe","Sortino"]].values.max() + 0.1]
            fig_d4b.add_trace(go.Scatter(
                x=diag_range, y=diag_range,
                mode="lines", name="Sortino = Sharpe",
                line=dict(color="#9E9E9E", dash="dash", width=1),
            ))
            fig_d4b.update_layout(
                xaxis_title="Sharpe", yaxis_title="Sortino",
                height=380, template="plotly_white",
                legend=dict(orientation="h", y=1.04),
                margin=dict(t=10, b=10),
            )
            st.plotly_chart(fig_d4b, use_container_width=True)
            st.caption(
                "Points above the diagonal = Sortino > Sharpe = system's losses are "
                "small relative to its gains (good asymmetry). "
                "Breakout systems should cluster furthest above the diagonal."
            )

    st.stop()  # ← prevents Vol Analysis pipeline from running

# ─────────────────────────────────────────────────────────────────────────────
# Run pipeline
# ─────────────────────────────────────────────────────────────────────────────
try:
    df_raw, df_clean, qs, burned_head, burned_tail = build_pipeline(
        window, norm_win, n_quantiles,
        str(date_start), str(date_end),
        _raw_df=raw_df,
    )
    df_strat, metrics = compute_strategy(df_clean, long_q, short_q, n_quantiles)
except Exception as e:
    st.error(f"Pipeline error: {e}")
    st.stop()

# ─────────────────────────────────────────────────────────────────────────────
# Header
# ─────────────────────────────────────────────────────────────────────────────
st.title(f"📈 Systematic Volatility Analysis — {active_name}")
st.caption(
    f"{active_name}  ·  {date_start} → {date_end}  ·  "
    f"Analysis window: **{window}d**  ·  Z-score window: **{norm_win}d**  ·  "
    f"Quantiles: **{n_quantiles}**  ·  "
    f"Clean observations: **{len(df_clean):,}**"
)

# ─────────────────────────────────────────────────────────────────────────────
# KPI strip
# ─────────────────────────────────────────────────────────────────────────────
k1, k2, k3, k4, k5, k6 = st.columns(6)
def kpi(col, label, value, fmt="{:.3f}"):
    col.metric(label, fmt.format(value))

kpi(k1, "Information Ratio",  metrics["ir"])
kpi(k2, "Sharpe Ratio",       metrics["sharpe"])
kpi(k3, "Ann. Return",        metrics["ann_ret"],  fmt="{:.1%}")
kpi(k4, "Ann. Volatility",    metrics["ann_std"],  fmt="{:.1%}")
kpi(k5, "Win Rate",           metrics["win_rate"], fmt="{:.1%}")
kpi(k6, "Max Drawdown",       metrics["max_dd"],   fmt="{:.1%}")

st.markdown("---")

# ═════════════════════════════════════════════════════════════════════════════
# SECTION TABS
# ═════════════════════════════════════════════════════════════════════════════
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "📊 Phase 1 · Raw Data",
    "🔧 Phase 2 · Indicators",
    "🔁 Phase 3 · Z-Scores",
    "🗂️ Phase 4 · Quintiles",
    "💼 Phase 5 · Strategy",
    "🌐 Summary · All Instruments",
])

# ─────────────────────────────────────────────────────────────────────────────
# TAB 1 — Raw Data
# ─────────────────────────────────────────────────────────────────────────────
with tab1:
    st.subheader("S&P 500 Price History & Daily Returns")
    st.caption(
        f"Formula: **ret1 = (Closeₜ / Closeₜ₋₁) − 1**  ·  "
        f"First **{burned_head}** rows burned (look-back)  ·  "
        f"Last **{burned_tail}** rows burned (look-ahead)"
    )

    ret_clean_summary = df_raw["ret1"].dropna() * 100
    with st.expander("📖 What are we looking at? — Plain-language summary", expanded=False):
        st.markdown(f"""
**The starting point: price and daily returns.**

We have **{len(df_raw):,} trading days** of S&P 500 closing prices from
**{df_raw['Date'].min().date()}** to **{df_raw['Date'].max().date()}**.

Every other calculation in this analysis is built on top of one simple number —
the **daily return**: how much the index moved up or down compared to the day before.

> *Daily Return = (Today's Price ÷ Yesterday's Price) − 1*

A return of **+1%** means the index rose 1% that day; **−1%** means it fell 1%.

---

**Why does the distribution shape matter?**

If you look at the histogram on the left, you'll notice that the bars around zero are
taller than the red dashed "Normal" curve, and the bars at the extreme left and right are
also slightly taller than the curve. This is called **"fat tails"**.

The **excess kurtosis** here is **{ret_clean_summary.kurt():.1f}**. A perfectly normal
distribution scores **0**. A positive number means extreme crashes (and rallies)
happen *more often* than you'd expect by chance. This is why volatility modelling
matters — normal distribution assumptions systematically underestimate risk.

---

**What gets discarded ("burned")?**

Because later steps need {window} days to calculate a rolling window *and* {norm_win} days
to calculate a Z-score, the first **{burned_head} rows** cannot produce valid indicators.
The last **{burned_tail} rows** are discarded because we can't know the *future* return for
them yet. This leaves **{len(df_clean):,} clean, usable observations**.
        """)


    if show_ret1_on_price:
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                            row_heights=[0.65, 0.35], vertical_spacing=0.04)
        fig.add_trace(go.Scatter(x=df_raw["Date"], y=df_raw["Close"],
                                 name="Close", line=dict(color=PALETTE["price"], width=1.2),
                                 fill="tozeroy", fillcolor="rgba(21,101,192,0.08)"),
                      row=1, col=1)
        fig.add_trace(go.Bar(x=df_raw["Date"], y=df_raw["ret1"]*100,
                             name="Daily Ret (%)",
                             marker_color=np.where(df_raw["ret1"] >= 0,
                                                   PALETTE["ret1"], "#C62828"),
                             showlegend=True),
                      row=2, col=1)
        fig.update_yaxes(title_text="Index Level", row=1, col=1)
        fig.update_yaxes(title_text="Daily Ret (%)", row=2, col=1)
        fig.update_layout(height=500, margin=dict(t=20, b=20))
    else:
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df_raw["Date"], y=df_raw["Close"],
                                 name="Close", line=dict(color=PALETTE["price"], width=1.2),
                                 fill="tozeroy", fillcolor="rgba(21,101,192,0.08)"))
        fig.update_yaxes(title_text="Index Level")
        fig.update_layout(height=380, margin=dict(t=20, b=20))

    fig.update_layout(legend=dict(orientation="h", y=1.02),
                      hovermode="x unified", template="plotly_white")
    st.plotly_chart(fig, use_container_width=True)

    # Distribution
    c1, c2 = st.columns(2)
    with c1:
        ret_clean = df_raw["ret1"].dropna() * 100
        fig_hist = go.Figure()
        fig_hist.add_trace(go.Histogram(x=ret_clean, nbinsx=120,
                                        marker_color=PALETTE["ret1"],
                                        name="Daily returns",
                                        histnorm="probability density"))
        # Normal overlay
        x_norm = np.linspace(ret_clean.min(), ret_clean.max(), 200)
        y_norm = (1/(ret_clean.std()*np.sqrt(2*np.pi))) * np.exp(-0.5*((x_norm-ret_clean.mean())/ret_clean.std())**2)
        fig_hist.add_trace(go.Scatter(x=x_norm, y=y_norm, name="Normal fit",
                                      line=dict(color="#F44336", dash="dash", width=2)))
        fig_hist.update_layout(title="Return Distribution vs Normal",
                               xaxis_title="Daily Return (%)", yaxis_title="Density",
                               height=350, template="plotly_white", margin=dict(t=40, b=20))
        st.plotly_chart(fig_hist, use_container_width=True)
    with c2:
        stats = ret_clean.describe()
        kurt  = ret_clean.kurt()
        skew  = ret_clean.skew()
        st.markdown("#### Descriptive Statistics")
        st.dataframe(pd.DataFrame({
            "Metric": ["Count", "Mean (%)", "Std (%)", "Min (%)", "Max (%)", "Kurtosis", "Skewness"],
            "Value": [f"{len(ret_clean):,}",
                      f"{stats['mean']:.3f}",
                      f"{stats['std']:.3f}",
                      f"{stats['min']:.2f}",
                      f"{stats['max']:.2f}",
                      f"{kurt:.2f}",
                      f"{skew:.2f}"]
        }), use_container_width=True, hide_index=True)
        st.info(f"Excess kurtosis of **{kurt:.1f}** (Normal = 0) confirms fat tails — "
                "extreme moves are far more common than a normal distribution predicts.")

# ─────────────────────────────────────────────────────────────────────────────
# TAB 2 — Indicators
# ─────────────────────────────────────────────────────────────────────────────
with tab2:
    st.subheader("Engineered Indicators")

    with st.expander("📖 What are these indicators? — Plain-language summary", expanded=False):
        avg_vol = df_raw["vol20"].dropna().mean() * 100
        avg_ret20 = df_raw["ret20"].dropna().mean() * 100
        st.markdown(f"""
**From daily returns, we build three "summary" measures over a {window}-day window.**

Each one answers a different question about the market:

---

**1. vol20 — How nervous is the market right now?**

We take the standard deviation of the last {window} daily returns.
Standard deviation is just a measure of how spread-out the returns are.
If the market is calm, daily moves cluster tightly around zero — low vol.
If the market is panicking, returns swing wildly — high vol.

> Over the selected period, average vol20 is **{avg_vol:.2f}%**.

Think of vol20 as a "turbulence gauge" on an aeroplane. A reading near the
average means smooth air; a spike means severe turbulence is happening right now.

---

**2. ret20 — How has the market done over the past {window} days?**

This is simply the percentage change in price over the last {window} trading days.
It tells you whether the *recent past* has been a good or bad period for the index.

> Average trailing {window}-day return over the selected period: **{avg_ret20:+.2f}%**.

---

**3. fret20 — How will the market do over the *next* {window} days?**

This is the same as ret20, but shifted {window} days forward in time. On any given
day, fret20 tells you what the return *actually turned out to be* over the following
{window} days. We can only compute this in hindsight — which is exactly why it
burns the last {window} rows and why it's so valuable for testing signals.

> **The key question of this whole analysis:** does knowing vol20 today help
> predict fret20 tomorrow?

---

**Overlay tip:** Toggle *"vol20 overlay on ret20 chart"* in the sidebar to see
how spikes in volatility line up with swings in the 20-day return — you'll notice
that high-vol spikes almost always coincide with large negative ret20 readings.
        """)

    formulas = {
        "vol20":  f"vol20 = std(ret1, window={window}d)",
        "ret20":  f"ret20 = pct_change({window}d)  [trailing]",
        "fret20": f"fret20 = ret20.shift(−{window})  [future / look-ahead]",
    }
    c1, c2, c3 = st.columns(3)
    for col, (k, v) in zip([c1, c2, c3], formulas.items()):
        col.info(f"**{k}** · {v}")

    # ── vol20 chart ──────────────────────────────────────────────────────────
    st.markdown("#### Rolling Volatility (vol20)")
    fig_v = go.Figure()
    fig_v.add_trace(go.Scatter(x=df_raw["Date"], y=df_raw["vol20"]*100,
                               name="vol20 (%)", line=dict(color=PALETTE["vol20"], width=1),
                               fill="tozeroy", fillcolor="rgba(123,31,162,0.10)"))
    fig_v.update_layout(yaxis_title="Volatility (%)", height=300,
                        hovermode="x unified", template="plotly_white",
                        margin=dict(t=10, b=10))
    st.plotly_chart(fig_v, use_container_width=True)

    # ── ret20 and fret20 (optionally overlaid) ────────────────────────────────
    st.markdown("#### Historical & Future 20-Day Returns")
    fig_r = go.Figure()
    fig_r.add_trace(go.Scatter(x=df_raw["Date"], y=df_raw["ret20"]*100,
                               name="ret20 — trailing (%)",
                               line=dict(color=PALETTE["ret20"], width=0.9)))
    if show_fret_on_ret20:
        fig_r.add_trace(go.Scatter(x=df_raw["Date"], y=df_raw["fret20"]*100,
                                   name="fret20 — future (%)",
                                   line=dict(color=PALETTE["fret20"], width=0.9,
                                             dash="dot")))
    if show_vol_on_ret20:
        fig_r.add_trace(go.Scatter(x=df_raw["Date"], y=df_raw["vol20"]*100,
                                   name="vol20 (%)", yaxis="y2",
                                   line=dict(color=PALETTE["vol20"], width=0.7,
                                             dash="dash"), opacity=0.6))
        fig_r.update_layout(yaxis2=dict(title="vol20 (%)", overlaying="y",
                                        side="right", showgrid=False))

    fig_r.add_hline(y=0, line_dash="dash", line_color="#424242", line_width=0.8)
    fig_r.update_layout(yaxis_title="Return (%)", height=320,
                        hovermode="x unified", template="plotly_white",
                        legend=dict(orientation="h", y=1.04),
                        margin=dict(t=10, b=10))
    st.plotly_chart(fig_r, use_container_width=True)

    st.caption(
        f"**Lead-lag intuition:** fret20 is simply ret20 shifted {window} days into the future. "
        "Wherever you see ret20 today, fret20 shows what actually happened next."
    )

# ─────────────────────────────────────────────────────────────────────────────
# TAB 3 — Z-Scores
# ─────────────────────────────────────────────────────────────────────────────
with tab3:
    st.subheader("Z-Score Normalisation")

    with st.expander("📖 Why do we normalise? — Plain-language summary", expanded=False):
        zvol_mean = df_clean["zvol20"].mean()
        zvol_std  = df_clean["zvol20"].std()
        st.markdown(f"""
**The problem: a "high" volatility number in 1965 means something very different
from a "high" volatility number in 1998.**

Market regimes shift over decades. The absolute level of volatility in the calm
1960s was structurally lower than in the turbulent 1990s. If we compare raw
numbers across those eras, we'd be mixing apples and oranges.

**The fix: Z-score each indicator relative to the recent past.**

> *Z = (Today's Value − Rolling {norm_win}-Day Average) ÷ Rolling {norm_win}-Day Std Dev*

A Z-score of **0** means "exactly average for this era."
A Z-score of **+2** means "2 standard deviations above what's been normal recently — unusually high."
A Z-score of **−1** means "1 standard deviation below normal — unusually calm."

After Z-scoring, the three indicators are **directly comparable** at any point in time,
regardless of the market regime.

---

**What to look for in the charts:**

- **Dual-axis chart (vol20 vs zvol20):** Notice how the raw vol20 line drifts upward
  over decades, while zvol20 oscillates around zero throughout — that's the normalisation
  working. The Z-score catches *relative* spikes even when the absolute level is low.

- **All three Z-scores overlaid:** When zvol20 spikes up, zret20 almost always dips
  simultaneously — they move in opposite directions. This is the concurrent relationship.
  Now look at what zfret20 does *after* a zvol20 spike — this is the lead-lag signal.

- **Scatter (zvol20 vs zfret20):** Each dot is one trading day. Colour shows which
  quintile it falls in. Notice that the blue dots (low vol, left side) sit slightly
  *below* zero on the y-axis, while red dots (high vol, right side) sit slightly
  *above* zero. That pattern — high vol predicting positive future returns — is the
  entire basis for the trading strategy in Phase 5.

---

After Z-scoring, the mean of zvol20 across the clean dataset is **{zvol_mean:.3f}**
and the standard deviation is **{zvol_std:.3f}** (both should be close to 0 and 1
respectively, confirming the normalisation is working correctly).
        """)

    st.info(
        f"**Formula:** Z = (Value − μ₍{norm_win}d₎) / σ₍{norm_win}d₎   ·   "
        "Removes regime bias so that the 1970s low-vol era and the 1990s high-vol era "
        "are on the same scale."
    )

    # ── Raw vs Z-scored vol ──────────────────────────────────────────────────
    st.markdown("#### vol20 (raw) vs zvol20 (normalised)")
    fig_zd = make_subplots(specs=[[{"secondary_y": True}]])
    if show_raw_on_z:
        fig_zd.add_trace(go.Scatter(x=df_clean["Date"], y=df_clean["vol20"]*100,
                                    name="vol20 (raw %)", opacity=0.45,
                                    line=dict(color=PALETTE["vol20"], width=0.8)),
                         secondary_y=False)
    fig_zd.add_trace(go.Scatter(x=df_clean["Date"], y=df_clean["zvol20"],
                                name="zvol20 (Z-score)",
                                line=dict(color="#FF6F00", width=1.1)),
                     secondary_y=True)
    fig_zd.add_hline(y=0, line_dash="dash", line_color="#424242", line_width=0.7,
                     secondary_y=True)
    fig_zd.update_yaxes(title_text="vol20 (%)", secondary_y=False)
    fig_zd.update_yaxes(title_text="Z-score", secondary_y=True)
    fig_zd.update_layout(height=300, hovermode="x unified", template="plotly_white",
                         legend=dict(orientation="h", y=1.04), margin=dict(t=10, b=10))
    st.plotly_chart(fig_zd, use_container_width=True)

    # ── All 3 Z-scores overlaid ──────────────────────────────────────────────
    st.markdown("#### All Three Z-Scores Overlaid")
    fig_za = go.Figure()
    for col, color, name in [
        ("zvol20",  PALETTE["zvol20"],  "zvol20 — normalised volatility"),
        ("zret20",  PALETTE["zret20"],  "zret20 — concurrent return"),
        ("zfret20", PALETTE["zfret20"], "zfret20 — future return"),
    ]:
        fig_za.add_trace(go.Scatter(x=df_clean["Date"], y=df_clean[col],
                                    name=name, line=dict(color=color, width=0.9)))
    fig_za.add_hline(y=0, line_dash="dash", line_color="#424242", line_width=0.7)
    fig_za.update_layout(yaxis_title="Z-score", height=320,
                         hovermode="x unified", template="plotly_white",
                         legend=dict(orientation="h", y=1.04), margin=dict(t=10, b=10))
    st.plotly_chart(fig_za, use_container_width=True)

    # ── Scatter zvol20 vs zfret20 ─────────────────────────────────────────────
    st.markdown("#### Scatter: zvol20 vs zfret20 (coloured by quintile)")
    fig_sc = go.Figure()
    for q_val in sorted(df_strat["quintile"].unique()):
        mask = df_strat["quintile"] == q_val
        idx  = q_val - 1
        color = PALETTE["q"][idx] if idx < len(PALETTE["q"]) else "#888888"
        fig_sc.add_trace(go.Scatter(
            x=df_strat.loc[mask, "zvol20"],
            y=df_strat.loc[mask, "zfret20"],
            mode="markers",
            name=f"Q{q_val}",
            marker=dict(color=color, size=3, opacity=0.4),
        ))
    fig_sc.add_hline(y=0, line_dash="dash", line_color="#424242", line_width=0.7)
    fig_sc.add_vline(x=0, line_dash="dash", line_color="#424242", line_width=0.7)
    fig_sc.update_layout(xaxis_title="zvol20", yaxis_title="zfret20",
                         height=380, template="plotly_white",
                         legend=dict(orientation="h", y=1.04), margin=dict(t=10, b=10))
    st.plotly_chart(fig_sc, use_container_width=True)

    st.caption(
        "**Mean-reversion pattern:** Q5 (high vol, right side) clusters above zero on zfret20, "
        "while Q1 (low vol, left side) clusters below zero — high-vol regimes tend to "
        "be followed by positive returns."
    )

# ─────────────────────────────────────────────────────────────────────────────
# TAB 4 — Quintiles
# ─────────────────────────────────────────────────────────────────────────────
with tab4:
    st.subheader("Quintile (Quantile) Analysis")
    st.caption(
        "The full clean dataset is **sorted by zvol20** and split into equal-sized buckets. "
        "Each bar shows the average Z-score for that bucket."
    )

    q1_fret = qs.loc[qs["quintile"]==1, "avg_zfret20"].values[0]
    q_top_fret = qs.loc[qs["quintile"]==n_quantiles, "avg_zfret20"].values[0]
    q1_ret  = qs.loc[qs["quintile"]==1, "avg_zret20"].values[0]
    q_top_ret  = qs.loc[qs["quintile"]==n_quantiles, "avg_zret20"].values[0]
    with st.expander("📖 What do the quintiles tell us? — Plain-language summary", expanded=False):
        st.markdown(f"""
**Sorting and bucketing: finding the pattern across the full history.**

We take all **{len(df_clean):,}** clean trading days, sort them from the *calmest*
(lowest zvol20) to the *most volatile* (highest zvol20), and split them into
**{n_quantiles} equal-sized groups** called quintiles.

- **Q1** = the calmest {100//n_quantiles}% of days in history
- **Q{n_quantiles}** = the most volatile {100//n_quantiles}% of days in history

Each bucket gets an average score for all three Z-score indicators.
This strips away the time dimension and asks: *"Across all of history, what tends
to happen to returns when volatility is at a certain relative level?"*

---

**Reading the three bar charts:**

**Chart 1 — Average zvol20:** This just confirms the bucketing worked correctly.
Each bar should be higher than the one to its left (monotone increase). If it's not,
something went wrong with the data.

**Chart 2 — Concurrent zret20:** This shows what recent returns looked like *at the
same time* as each vol level. The pattern here is almost always the same:
- Low vol (Q1) → recent returns were **good** (avg zret20 = **{q1_ret:+.3f}**)
- High vol (Q{n_quantiles}) → recent returns were **bad** (avg zret20 = **{q_top_ret:+.3f}**)

This makes intuitive sense: volatility spikes *because* the market is falling.

**Chart 3 — Future zfret20 (the key chart):** This shows what returns looked like
*over the following {window} days* — after each vol reading. The pattern reverses:
- Low vol (Q1) → future returns tend to be **negative** (avg zfret20 = **{q1_fret:+.3f}**)
- High vol (Q{n_quantiles}) → future returns tend to be **positive** (avg zfret20 = **{q_top_fret:+.3f}**)

**This is the mean-reversion signal.** Periods of high volatility (panic) tend to
overshoot — prices fall too far, then bounce. Periods of calm (low vol, rising prices)
tend to overshoot the other way — and then stall or pull back.

---

**Try adjusting the number of quantiles in the sidebar.** More buckets give you finer
resolution on where the signal is strongest. Fewer buckets are noisier but more robust.
        """)


    q_colors = [PALETTE["q"][min(i, len(PALETTE["q"])-1)] for i in range(n_quantiles)]
    x_labels = [f"Q{q}" for q in qs["quintile"]]

    c1, c2, c3 = st.columns(3)
    charts = [
        (c1, "avg_zvol20",  "Average zvol20",  "Mean Z-score of volatility — confirms monotone bucketing"),
        (c2, "avg_zret20",  "Concurrent zret20","Co-occurring returns: high vol = recent bad returns"),
        (c3, "avg_zfret20", "Future zfret20",   "Lead-lag: what returns look like after each vol regime"),
    ]
    for col, field, title, caption in charts:
        with col:
            vals = qs[field].tolist()
            fig_bar = go.Figure(go.Bar(
                x=x_labels, y=vals,
                marker_color=q_colors,
                text=[f"{v:+.3f}" for v in vals],
                textposition="outside",
            ))
            fig_bar.add_hline(y=0, line_dash="dash", line_color="#424242", line_width=0.8)
            fig_bar.update_layout(title=title, yaxis_title="Mean Z-score",
                                  height=350, template="plotly_white",
                                  margin=dict(t=40, b=20),
                                  showlegend=False)
            st.plotly_chart(fig_bar, use_container_width=True)
            st.caption(caption)

    # Summary table
    st.markdown("#### Full Quintile Summary Table")
    display_qs = qs.copy()
    display_qs.columns = ["Quintile", "Count", "Avg zvol20", "Avg zret20 (Concurrent)", "Avg zfret20 (Future)"]
    for c in ["Avg zvol20", "Avg zret20 (Concurrent)", "Avg zfret20 (Future)"]:
        display_qs[c] = display_qs[c].map("{:+.4f}".format)
    st.dataframe(display_qs, use_container_width=True, hide_index=True)

# ─────────────────────────────────────────────────────────────────────────────
# TAB 5 — Strategy
# ─────────────────────────────────────────────────────────────────────────────
with tab5:
    st.subheader("Strategy Evaluation")

    m = metrics
    ir_colour   = "🟢" if m["ir"]  > 0.5 else ("🟡" if m["ir"]  > 0.2 else "🔴")
    wr_colour   = "🟢" if m["win_rate"] > 0.55 else ("🟡" if m["win_rate"] > 0.45 else "🔴")
    dd_colour   = "🟢" if m["max_dd"] > -0.10 else ("🟡" if m["max_dd"] > -0.20 else "🔴")
    with st.expander("📖 How does the strategy work and what do the metrics mean? — Plain-language summary", expanded=False):
        st.markdown(f"""
**Turning the quintile signal into a trading rule.**

The findings from Phase 4 suggest a simple rule:
- When volatility is **abnormally high** (Q{long_q}) → go **long** (buy the market),
  because it tends to mean-revert upward over the next {window} days.
- When volatility is **abnormally low** (Q{short_q}) → go **short** (bet against the market),
  because calm periods tend to stall or reverse.
- All other days → stay **flat** (no position).

Use the **Long quantile** and **Short quantile** selectors in the sidebar to test
different combinations. The current setup is **Long Q{long_q} / Short Q{short_q}**.

---

**What each metric tells you:**

| Metric | Current value | What it means |
|---|---|---|
| Information Ratio (IR) | {ir_colour} **{m["ir"]:.3f}** | Return per unit of risk, ignoring any risk-free rate. Above 0.5 is strong; 0.2–0.5 is moderate; below 0 means the strategy is losing. |
| Sharpe Ratio | {ir_colour} **{m["sharpe"]:.3f}** | Same as IR when risk-free rate = 0%. Would diverge if you set a non-zero rf benchmark. |
| Ann. Return | **{m["ann_ret"]:.1%}** | Average yearly gain if this signal were traded continuously. |
| Ann. Volatility | **{m["ann_std"]:.1%}** | How much the strategy's returns vary year-to-year. Lower is steadier. |
| Win Rate | {wr_colour} **{m["win_rate"]:.1%}** | Percentage of active trades that were profitable. Above 50% means more wins than losses. |
| Max Drawdown | {dd_colour} **{m["max_dd"]:.1%}** | The worst peak-to-trough loss experienced. A smaller negative number is better. |

---

**Reading the equity curve:**

The curve shows cumulative wealth starting at 1.0. A curve that ends at 2.0 means
the strategy doubled the initial investment over the period. Compare the **orange
strategy line** to the **grey buy-and-hold benchmark** — if orange finishes higher,
the strategy outperformed simply holding the market.

The **rolling IR panel** (toggle in sidebar) shows whether the signal was consistently
strong or only worked in certain eras. A line consistently above the green 0.5 threshold
is a robust signal; one that dips frequently suggests regime-dependence.

---

**Reading the heatmap:**

The decade × quintile heatmap answers: *"Does the pattern hold across different
eras, or did it only work in the 1990s?"* Green cells (positive future returns) in
Q{n_quantiles} across multiple decades give you confidence the signal is structural,
not a historical accident. Red cells in Q{n_quantiles} for any decade are a warning sign.

---

**Things to try in the sidebar:**
- Narrow the **date range** to a specific decade to see how the IR changes era by era.
- Slide the **analysis window** down to 5 days (very short-term) or up to 63 days
  (one quarter) to see how the holding period changes the signal strength.
- Increase the **Z-score window** to 500 days to apply a much longer memory for
  "normal" — the signal often weakens because the Z-score reacts more slowly.
        """)

    st.info(
        f"**Signal:** Long **Q{long_q}** · Short **Q{short_q}** · "
        f"Applied to the {window}-day forward return (fret20)  \n"
        f"**IR** = (μ × 252) / (σ × √252)  ·  "
        f"**Sharpe** = ((μ − rf) × 252) / (σ × √252)  where rf = 0%"
    )

    # KPI row (repeated for this tab with more detail)
    k1, k2, k3, k4, k5, k6 = st.columns(6)
    m = metrics
    k1.metric("Information Ratio", f"{m['ir']:.3f}")
    k2.metric("Sharpe Ratio",      f"{m['sharpe']:.3f}")
    k3.metric("Ann. Return",       f"{m['ann_ret']:.1%}")
    k4.metric("Ann. Volatility",   f"{m['ann_std']:.1%}")
    k5.metric("Win Rate",          f"{m['win_rate']:.1%}")
    k6.metric("Max Drawdown",      f"{m['max_dd']:.1%}")

    # ── Equity curve ─────────────────────────────────────────────────────────
    st.markdown("#### Cumulative Equity Curve")
    fig_eq = make_subplots(rows=2 if show_rolling_ir else 1, cols=1,
                           shared_xaxes=True,
                           row_heights=[0.65, 0.35] if show_rolling_ir else [1],
                           vertical_spacing=0.06)

    fig_eq.add_trace(go.Scatter(x=df_strat["Date"], y=df_strat["cum_bh"],
                                name="Buy-and-Hold (fret20 benchmark)",
                                line=dict(color=PALETTE["bh"], width=1.2, dash="dot")),
                     row=1, col=1)
    fig_eq.add_trace(go.Scatter(x=df_strat["Date"], y=df_strat["cum_strat"],
                                name=f"Strategy (Long Q{long_q} / Short Q{short_q})",
                                line=dict(color=PALETTE["strat"], width=1.5)),
                     row=1, col=1)
    fig_eq.update_yaxes(title_text="Cumulative Wealth", row=1, col=1)

    if show_rolling_ir:
        fig_eq.add_trace(go.Scatter(x=df_strat["Date"], y=df_strat["rolling_ir"],
                                    name="Rolling IR (60-obs)",
                                    line=dict(color="#1565C0", width=1.1)),
                         row=2, col=1)
        fig_eq.add_hline(y=0, line_dash="dash", line_color="#424242",
                         line_width=0.7, row=2, col=1)
        fig_eq.add_hline(y=0.5, line_dash="dot", line_color="#2E7D32",
                         line_width=0.8, row=2, col=1,
                         annotation_text="IR = 0.5", annotation_position="right")
        fig_eq.update_yaxes(title_text="Rolling IR", row=2, col=1)

    fig_eq.update_layout(height=500 if show_rolling_ir else 380,
                         hovermode="x unified", template="plotly_white",
                         legend=dict(orientation="h", y=1.04),
                         margin=dict(t=10, b=10))
    st.plotly_chart(fig_eq, use_container_width=True)

    # ── Strategy return distribution ──────────────────────────────────────────
    st.markdown("#### Strategy Return Distribution")
    c1, c2 = st.columns([2, 1])
    with c1:
        active_rets = df_strat.loc[df_strat["signal"] != 0, "strat_ret"] * 100
        fig_sd = go.Figure()
        fig_sd.add_trace(go.Histogram(x=active_rets, nbinsx=80,
                                      marker_color=PALETTE["strat"],
                                      name="Strategy returns",
                                      histnorm="probability density"))
        # Normal overlay
        if len(active_rets) > 10:
            x_n = np.linspace(active_rets.min(), active_rets.max(), 200)
            y_n = (1/(active_rets.std()*np.sqrt(2*np.pi))) * \
                  np.exp(-0.5*((x_n - active_rets.mean()) / active_rets.std())**2)
            fig_sd.add_trace(go.Scatter(x=x_n, y=y_n, name="Normal fit",
                                        line=dict(color="#1565C0", dash="dash", width=2)))
        fig_sd.add_vline(x=0, line_dash="dash", line_color="#424242")
        fig_sd.update_layout(xaxis_title="20-Day Return (%)", yaxis_title="Density",
                             height=320, template="plotly_white",
                             legend=dict(orientation="h", y=1.04),
                             margin=dict(t=10, b=10))
        st.plotly_chart(fig_sd, use_container_width=True)
    with c2:
        st.markdown("#### Metrics Breakdown")
        st.dataframe(pd.DataFrame({
            "Metric": ["Active obs", "Ann. Return", "Ann. Volatility",
                       "Info. Ratio", "Sharpe Ratio", "Win Rate", "Max Drawdown"],
            "Value": [
                f"{m['n_active']:,}",
                f"{m['ann_ret']:.2%}",
                f"{m['ann_std']:.2%}",
                f"{m['ir']:.3f}",
                f"{m['sharpe']:.3f}",
                f"{m['win_rate']:.1%}",
                f"{m['max_dd']:.2%}",
            ]
        }), use_container_width=True, hide_index=True)
        st.caption(
            "**IR** measures risk-adjusted return ignoring risk-free rate. "
            "**Sharpe** subtracts rf (set to 0% here). "
            "Both collapse to the same value when rf = 0."
        )

    # ── Quintile return heatmap ───────────────────────────────────────────────
    st.markdown("#### Average Forward Return by Quintile vs Time Decade")
    df_strat["decade"] = (df_strat["Date"].dt.year // 10 * 10).astype(str) + "s"
    heat = (df_strat.groupby(["decade", "quintile"], observed=True)["fret20"]
            .mean().unstack("quintile") * 100)
    heat.columns = [f"Q{c}" for c in heat.columns]

    fig_heat = go.Figure(go.Heatmap(
        z=heat.values,
        x=heat.columns.tolist(),
        y=heat.index.tolist(),
        colorscale="RdYlGn",
        text=[[f"{v:.2f}%" for v in row] for row in heat.values],
        texttemplate="%{text}",
        colorbar=dict(title="Avg fret20 (%)"),
    ))
    fig_heat.update_layout(xaxis_title="Volatility Quintile",
                           yaxis_title="Decade",
                           height=300, template="plotly_white",
                           margin=dict(t=10, b=10))
    st.plotly_chart(fig_heat, use_container_width=True)
    st.caption(
        "Avg 20-day forward return (%) per quintile per decade. "
        "Green = positive, Red = negative. "
        "Shows whether the lead-lag signal is consistent across time."
    )

# ─────────────────────────────────────────────────────────────────────────────
# TAB 6 — Summary: All Instruments
# ─────────────────────────────────────────────────────────────────────────────
with tab6:
    st.subheader("🌐 All Instruments — Cross-Portfolio Summary")
    st.caption(
        f"Scans `{DATA_DIR}` on every render. "
        "Drop a new CSV in that folder and refresh — it appears here automatically. "
        f"Analysis window: **{window}d** · Z-score window: **{norm_win}d** · "
        f"Long Q{long_q} / Short Q{short_q}"
    )

    @st.cache_data(ttl=60)
    def compute_summary_row(label: str, _df: pd.DataFrame,
                            window: int, norm_win: int, n_quantiles: int,
                            long_q: int, short_q: int) -> dict:
        """Run the full pipeline on one instrument and return metrics + quintile data."""
        try:
            _, dc, qs_raw, _, _ = build_pipeline(window, norm_win, n_quantiles,
                                                  str(_df["Date"].min().date()),
                                                  str(_df["Date"].max().date()),
                                                  _raw_df=_df)
            _, m = compute_strategy(dc, long_q, short_q, n_quantiles)

            # Quintile summary (for sector-level aggregation)
            qs_out = qs_raw[["quintile", "avg_zvol20", "avg_zret20", "avg_zfret20"]].copy()
            qs_out["label"] = label

            # Decade × quintile data
            labels_q = list(range(1, n_quantiles + 1))
            dc2 = dc.copy()
            dc2["quintile"] = pd.qcut(dc2["zvol20"], q=n_quantiles,
                                      labels=labels_q, duplicates="drop").astype(int)
            dc2["decade"] = (dc2["Date"].dt.year // 10 * 10).astype(str) + "s"
            decade_out = (dc2.groupby(["decade", "quintile"], observed=True)["fret20"]
                         .mean().reset_index())
            decade_out["label"] = label

            return dict(
                label      = label,
                rows       = len(_df),
                date_from  = _df["Date"].min().date(),
                date_to    = _df["Date"].max().date(),
                years      = round((_df["Date"].max() - _df["Date"].min()).days / 365.25, 1),
                clean_rows = len(dc),
                ir         = m["ir"],
                sharpe     = m["sharpe"],
                ann_ret    = m["ann_ret"],
                ann_std    = m["ann_std"],
                win_rate   = m["win_rate"],
                max_dd     = m["max_dd"],
                qs_df      = qs_out,
                decade_df  = decade_out,
            )
        except Exception as e:
            return dict(label=label, rows=len(_df), error=str(e))

    # ── Collect rows ──────────────────────────────────────────────────────────
    # Always re-scan the folder so newly dropped CSVs appear without restart
    all_on_disk = list_saved_instruments()
    # Merge with in-memory catalogue (in case something wasn't saved to disk)
    all_instruments = {**all_on_disk}
    for k, v in st.session_state.catalogue.items():
        if k not in all_instruments and k != "S&P 500 (built-in)":
            all_instruments[k] = v
    # Always include the built-in
    all_instruments["S&P 500 (built-in)"] = load_sp500_excel()

    meta = load_metadata()

    with st.spinner("Computing metrics for all instruments…"):
        rows = []
        for lbl, idf in all_instruments.items():
            row = compute_summary_row(lbl, idf, window, norm_win, n_quantiles, long_q, short_q)
            row["sector"] = meta.get(lbl, {}).get("sector", "Unclassified")
            rows.append(row)

    good = [r for r in rows if "error" not in r]
    bad  = [r for r in rows if "error" in r]

    if bad:
        with st.expander(f"⚠️ {len(bad)} instrument(s) failed to compute", expanded=False):
            for r in bad:
                st.warning(f"**{r['label']}**: {r['error']}")

    if not good:
        st.info("No instruments with enough data yet. Add some in the sidebar.")
        st.stop()

    summary_df = pd.DataFrame(good)
    summary_df = summary_df.sort_values(["sector", "ir"], ascending=[True, False]).reset_index(drop=True)

    # ── Sector filter ─────────────────────────────────────────────────────────
    all_sectors = sorted(summary_df["sector"].unique().tolist())
    sel_sectors = st.multiselect("Filter by sector", all_sectors, default=all_sectors)
    view = summary_df[summary_df["sector"].isin(sel_sectors)].copy()

    # ── KPI strip — portfolio-wide averages ───────────────────────────────────
    st.markdown("#### Portfolio-wide averages (across all visible instruments)")
    a1, a2, a3, a4, a5, a6 = st.columns(6)
    a1.metric("Instruments",    len(view))
    a2.metric("Avg IR",         f"{view['ir'].mean():.3f}")
    a3.metric("Avg Sharpe",     f"{view['sharpe'].mean():.3f}")
    a4.metric("Avg Ann. Return",f"{view['ann_ret'].mean():.1%}")
    a5.metric("Avg Win Rate",   f"{view['win_rate'].mean():.1%}")
    a6.metric("Avg Max DD",     f"{view['max_dd'].mean():.1%}")

    st.markdown("---")

    # ── Comparison bar charts ─────────────────────────────────────────────────
    st.markdown("#### Strategy Metrics Comparison")
    chart_cols = st.columns(2)

    def sector_color(s):
        return SECTOR_COLOURS.get(s, "#9E9E9E")

    bar_metrics = [
        ("ir",      "Information Ratio",  chart_cols[0]),
        ("sharpe",  "Sharpe Ratio",       chart_cols[1]),
        ("ann_ret", "Ann. Return",        chart_cols[0]),
        ("ann_std", "Ann. Volatility",    chart_cols[1]),
        ("win_rate","Win Rate",           chart_cols[0]),
        ("max_dd",  "Max Drawdown",       chart_cols[1]),
    ]
    for metric, title, col in bar_metrics:
        sorted_view = view.sort_values(metric, ascending=(metric == "max_dd"))
        colours = [sector_color(s) for s in sorted_view["sector"]]
        fig_bar = go.Figure(go.Bar(
            x=sorted_view["label"],
            y=sorted_view[metric],
            marker_color=colours,
            text=[f"{v:.2f}" if metric not in ("ann_ret","ann_std","win_rate","max_dd")
                  else f"{v:.1%}" for v in sorted_view[metric]],
            textposition="outside",
            customdata=sorted_view["sector"],
            hovertemplate="%{x}<br>Sector: %{customdata}<br>" + title + ": %{y:.3f}<extra></extra>",
        ))
        fig_bar.add_hline(y=0, line_dash="dash", line_color="#424242", line_width=0.8)
        fig_bar.update_layout(
            title=title, height=320, template="plotly_white",
            showlegend=False, margin=dict(t=40, b=20),
            yaxis_tickformat=".1%" if metric in ("ann_ret","ann_std","win_rate","max_dd") else ".2f",
        )
        col.plotly_chart(fig_bar, use_container_width=True)

    st.markdown("---")

    # ── IR scatter: Ann. Return vs Ann. Vol (bubble = IR, colour = sector) ────
    st.markdown("#### Risk / Return Map  *(bubble size = |IR|, colour = sector)*")
    fig_rr = go.Figure()
    for sec in all_sectors:
        sub = view[view["sector"] == sec]
        if sub.empty:
            continue
        fig_rr.add_trace(go.Scatter(
            x=sub["ann_std"],
            y=sub["ann_ret"],
            mode="markers+text",
            name=sec,
            text=sub["label"],
            textposition="top center",
            textfont=dict(size=9),
            marker=dict(
                size=np.clip(sub["ir"].abs() * 40, 8, 60),
                color=sector_color(sec),
                opacity=0.75,
                line=dict(width=1, color="white"),
            ),
            hovertemplate=(
                "<b>%{text}</b><br>Sector: " + sec +
                "<br>Ann. Vol: %{x:.1%}<br>Ann. Return: %{y:.1%}<extra></extra>"
            ),
        ))
    fig_rr.add_hline(y=0, line_dash="dash", line_color="#424242", line_width=0.7)
    fig_rr.update_layout(
        xaxis_title="Annualised Volatility", yaxis_title="Annualised Return",
        xaxis_tickformat=".0%", yaxis_tickformat=".0%",
        height=480, template="plotly_white",
        legend=dict(orientation="v", x=1.01, y=1),
        margin=dict(t=10, b=20, r=160),
    )
    st.plotly_chart(fig_rr, use_container_width=True)

    st.markdown("---")

    # ── Sector-average IR grouped bar ─────────────────────────────────────────
    st.markdown("#### Average IR by Sector")
    sec_avg = (view.groupby("sector")[["ir","sharpe","win_rate","ann_ret"]]
               .mean().reset_index().sort_values("ir", ascending=False))
    fig_sec = go.Figure()
    for col_name, display in [("ir","IR"), ("sharpe","Sharpe"), ("win_rate","Win Rate")]:
        fig_sec.add_trace(go.Bar(
            name=display,
            x=sec_avg["sector"],
            y=sec_avg[col_name],
            text=[f"{v:.2f}" for v in sec_avg[col_name]],
            textposition="outside",
        ))
    fig_sec.add_hline(y=0, line_dash="dash", line_color="#424242", line_width=0.8)
    fig_sec.update_layout(
        barmode="group", height=380, template="plotly_white",
        legend=dict(orientation="h", y=1.06),
        margin=dict(t=20, b=20),
        yaxis_title="Score",
    )
    st.plotly_chart(fig_sec, use_container_width=True)

    st.markdown("---")

    # ── Quintile profiles by sector ───────────────────────────────────────────
    st.markdown("#### Quintile Profiles by Sector")
    st.caption(
        "Each bar is the **sector average** of that Z-score metric across all "
        "instruments in that sector. Compares how different sectors behave "
        "at each vol quintile level."
    )

    # Aggregate quintile data across all good rows, join sector
    all_qs = pd.concat(
        [r["qs_df"].assign(sector=r["sector"]) for r in good if "qs_df" in r],
        ignore_index=True
    )
    sec_qs = (all_qs.groupby(["sector", "quintile"], observed=True)
              [["avg_zvol20", "avg_zret20", "avg_zfret20"]]
              .mean().reset_index())
    sec_qs["quintile"] = sec_qs["quintile"].astype(int)

    q_metric_tabs = st.tabs([
        "📊 avg zvol20 — Normalised Volatility",
        "📈 avg zret20 — Concurrent Return",
        "🔮 avg zfret20 — Future Return (Lead-Lag)",
    ])
    q_metric_fields = ["avg_zvol20", "avg_zret20", "avg_zfret20"]

    for qtab, field in zip(q_metric_tabs, q_metric_fields):
        with qtab:
            pivot = sec_qs.pivot(index="sector", columns="quintile", values=field)
            pivot.columns = [f"Q{c}" for c in pivot.columns]
            pivot = pivot.reindex(index=[s for s in SECTORS if s in pivot.index])

            fig_qsec = go.Figure()
            q_bar_colours = ["#1565C0", "#5C9BD6", "#90A4AE", "#EF9A9A", "#C62828"]
            for i, col_q in enumerate(pivot.columns):
                colour = q_bar_colours[min(i, len(q_bar_colours) - 1)]
                fig_qsec.add_trace(go.Bar(
                    name=col_q,
                    x=pivot.index.tolist(),
                    y=pivot[col_q].tolist(),
                    marker_color=colour,
                    text=[f"{v:+.3f}" if not np.isnan(v) else "" for v in pivot[col_q]],
                    textposition="outside",
                ))
            fig_qsec.add_hline(y=0, line_dash="dash", line_color="#424242", line_width=0.8)
            fig_qsec.update_layout(
                barmode="group",
                height=420,
                template="plotly_white",
                yaxis_title="Mean Z-score",
                xaxis_title="Sector",
                legend=dict(orientation="h", y=1.06),
                margin=dict(t=20, b=20),
            )
            st.plotly_chart(fig_qsec, use_container_width=True)

            # Also show per-instrument lines so you can see dispersion within sector
            with st.expander("Show per-instrument lines within each sector", expanded=False):
                sectors_present = sorted(all_qs["sector"].unique())
                sel = st.selectbox("Sector", sectors_present,
                                   key=f"qline_sector_{field}")
                sub_instr = all_qs[all_qs["sector"] == sel]
                fig_lines = go.Figure()
                for instr_lbl in sub_instr["label"].unique():
                    instr_data = sub_instr[sub_instr["label"] == instr_lbl].sort_values("quintile")
                    fig_lines.add_trace(go.Scatter(
                        x=[f"Q{q}" for q in instr_data["quintile"]],
                        y=instr_data[field],
                        mode="lines+markers",
                        name=instr_lbl,
                        line=dict(width=1.5),
                        marker=dict(size=6),
                    ))
                fig_lines.add_hline(y=0, line_dash="dash", line_color="#424242", line_width=0.7)
                fig_lines.update_layout(
                    yaxis_title="Mean Z-score",
                    xaxis_title="Quintile",
                    height=320,
                    template="plotly_white",
                    legend=dict(orientation="h", y=1.06),
                    margin=dict(t=10, b=10),
                )
                st.plotly_chart(fig_lines, use_container_width=True)

    st.markdown("---")

    # ── Decade × Quintile heatmap by sector ───────────────────────────────────
    st.markdown("#### Average Forward Return by Quintile × Decade — by Sector")
    st.caption(
        "Shows whether the vol → future-return signal is consistent across "
        "different time decades, broken down by sector. "
        "Green = positive future return, Red = negative."
    )

    all_decade = pd.concat(
        [r["decade_df"].assign(sector=r["sector"]) for r in good if "decade_df" in r],
        ignore_index=True
    )
    sec_decade = (all_decade.groupby(["sector", "decade", "quintile"], observed=True)["fret20"]
                  .mean().reset_index())

    sectors_with_data = sorted(sec_decade["sector"].unique())
    n_cols = 2
    sector_chunks = [sectors_with_data[i:i+n_cols] for i in range(0, len(sectors_with_data), n_cols)]

    for chunk in sector_chunks:
        heat_cols = st.columns(len(chunk))
        for col_idx, sec in enumerate(chunk):
            sub = sec_decade[sec_decade["sector"] == sec].copy()
            if sub.empty:
                continue
            pivot_h = sub.pivot(index="decade", columns="quintile", values="fret20") * 100
            pivot_h = pivot_h.sort_index()
            pivot_h.columns = [f"Q{c}" for c in pivot_h.columns]

            text_vals = [[f"{v:.2f}%" if not np.isnan(v) else "" for v in row]
                         for row in pivot_h.values]
            fig_h = go.Figure(go.Heatmap(
                z=pivot_h.values,
                x=pivot_h.columns.tolist(),
                y=pivot_h.index.tolist(),
                colorscale="RdYlGn",
                zmid=0,
                text=text_vals,
                texttemplate="%{text}",
                textfont=dict(size=9),
                colorbar=dict(title="%", thickness=12, len=0.8),
            ))
            fig_h.update_layout(
                title=dict(text=sec, font=dict(size=11, color="#1A237E")),
                xaxis_title="Quintile",
                yaxis_title="Decade",
                height=280,
                template="plotly_white",
                margin=dict(t=40, b=20, l=10, r=10),
            )
            heat_cols[col_idx].plotly_chart(fig_h, use_container_width=True)

    st.markdown("---")

    # ── Full table ────────────────────────────────────────────────────────────
    st.markdown("#### Full Instruments Table")
    display_cols = ["label","sector","years","clean_rows","ir","sharpe",
                    "ann_ret","ann_std","win_rate","max_dd"]
    tbl = view[display_cols].copy()
    tbl.columns = ["Instrument","Sector","Years","Clean Obs",
                   "IR","Sharpe","Ann. Return","Ann. Vol","Win Rate","Max DD"]
    # Format
    for c in ["Ann. Return","Ann. Vol","Win Rate","Max DD"]:
        tbl[c] = tbl[c].map("{:.1%}".format)
    for c in ["IR","Sharpe"]:
        tbl[c] = tbl[c].map("{:.3f}".format)

    def highlight_ir(val):
        try:
            v = float(val)
            if v >= 0.5:  return "background-color:#C8E6C9"
            if v >= 0.2:  return "background-color:#FFF9C4"
            if v <  0:    return "background-color:#FFCDD2"
        except Exception:
            pass
        return ""

    styled = tbl.style.applymap(highlight_ir, subset=["IR"])
    st.dataframe(styled, use_container_width=True, hide_index=True)

    # ── Download button ───────────────────────────────────────────────────────
    csv_bytes = tbl.to_csv(index=False).encode()
    st.download_button("⬇️ Download summary CSV", csv_bytes,
                       "vol_summary.csv", "text/csv")
