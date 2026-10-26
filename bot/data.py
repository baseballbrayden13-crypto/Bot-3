"""Historical intraday bars. Columns: open, high, low, close, volume; tz-aware UTC index."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from .config import Settings


def _regular_hours(df: pd.DataFrame) -> pd.DataFrame:
    et = df.index.tz_convert("America/New_York")
    mins = et.hour * 60 + et.minute
    return df[(mins >= 9 * 60 + 30) & (mins < 16 * 60)]


def from_alpaca(symbol: str, days: int, cfg: Settings, realtime: bool = False) -> pd.DataFrame:
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

    client = StockHistoricalDataClient(cfg.alpaca_key, cfg.alpaca_secret)
    req = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame(cfg.bar_minutes, TimeFrameUnit.Minute),
        start=datetime.now(timezone.utc) - timedelta(days=days),
        # The free plan allows real-time IEX bars; for backtests stay clear of the latest 15 min.
        end=None if realtime else datetime.now(timezone.utc) - timedelta(minutes=16),
        feed="iex",
    )
    df = client.get_stock_bars(req).df
    if df.empty:
        return df
    df = df.xs(symbol, level="symbol")[["open", "high", "low", "close", "volume"]]
    return _regular_hours(df)


def from_yfinance(symbol: str, days: int, cfg: Settings) -> pd.DataFrame:
    """No API key needed. Yahoo only serves ~60 days of 5-minute bars."""
    import yfinance as yf

    df = yf.download(
        symbol, period=f"{min(days, 59)}d", interval=f"{cfg.bar_minutes}m",
        progress=False, auto_adjust=False, multi_level_index=False,
    )
    if df.empty:
        return df
    df = df.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return _regular_hours(df)


def load_bars(symbol: str, days: int, cfg: Settings, source: str = "yfinance") -> pd.DataFrame:
    if source == "alpaca":
        return from_alpaca(symbol, days, cfg)
    if source == "yfinance":
        return from_yfinance(symbol, days, cfg)
    if source.endswith(".csv"):
        df = pd.read_csv(source, index_col=0, parse_dates=True)
        df.index = pd.to_datetime(df.index, utc=True)
        return df
    raise ValueError(f"unknown data source {source}")
