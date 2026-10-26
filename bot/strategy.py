"""Indicators and entry/exit signals.

Default strategy: intraday trend-following, long only.
  Enter long when the fast EMA crosses above the slow EMA, price is above
  the session VWAP, and RSI is between 50 and 70 (momentum, not overbought).
  Exit on an ATR stop, an ATR profit target, or a bearish EMA cross.

This is a starting point to test, not a proven edge.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import Settings


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def rsi(close: pd.Series, n: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def atr(df: pd.DataFrame, n: int) -> pd.Series:
    prev_close = df["close"].shift()
    tr = pd.concat(
        [df["high"] - df["low"], (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def session_vwap(df: pd.DataFrame) -> pd.Series:
    """VWAP that resets each trading day. Index must be tz-aware timestamps."""
    typical = (df["high"] + df["low"] + df["close"]) / 3
    day = df.index.tz_convert("America/New_York").date
    pv = (typical * df["volume"]).groupby(day).cumsum()
    vol = df["volume"].groupby(day).cumsum()
    return pv / vol.replace(0, np.nan)


def add_indicators(df: pd.DataFrame, cfg: Settings) -> pd.DataFrame:
    out = df.copy()
    out["ema_fast"] = ema(out["close"], cfg.ema_fast)
    out["ema_slow"] = ema(out["close"], cfg.ema_slow)
    out["rsi"] = rsi(out["close"], cfg.rsi_period)
    out["atr"] = atr(out, cfg.atr_period)
    out["vwap"] = session_vwap(out)
    above = out["ema_fast"] > out["ema_slow"]
    out["cross_up"] = above & ~above.shift(1, fill_value=False)
    out["cross_down"] = ~above & above.shift(1, fill_value=False)
    out = _add_opening_range(out, cfg.orb_minutes, cfg.orb_max_per_day)
    return out


def _add_opening_range(out: pd.DataFrame, minutes: int, max_per_day: int = 1) -> pd.DataFrame:
    """High/low of the first `minutes` of each session, filled in only once that window has closed."""
    et = out.index.tz_convert("America/New_York")
    day = et.date
    mins_in = (et.hour * 60 + et.minute) - (9 * 60 + 30)
    in_range = mins_in < minutes
    out["or_high"] = out["high"].where(in_range).groupby(day).transform("max").where(~in_range)
    out["or_low"] = out["low"].where(in_range).groupby(day).transform("min").where(~in_range)
    above = (out["close"] > out["or_high"]).fillna(False)
    prev_above = above.groupby(day).shift(fill_value=False).astype(bool)
    cross = above & ~prev_above  # a close back above the range high after being at or below it
    out["orb_break"] = cross & (cross.astype(int).groupby(day).cumsum() <= max_per_day)
    return out


@dataclass
class Signal:
    symbol: str
    side: str  # "buy" or "sell"
    price: float
    stop: float
    target: float
    reason: str


def entry_signal(symbol: str, bars: pd.DataFrame, cfg: Settings) -> Signal | None:
    """Look at the last completed bar of indicator-enriched data."""
    if cfg.strategy == "orb":
        return orb_signal(symbol, bars, cfg)
    if len(bars) < cfg.ema_slow + 2:
        return None
    row = bars.iloc[-1]
    if not (row["cross_up"] and row["close"] > row["vwap"] and 50 <= row["rsi"] <= 70):
        return None
    price = float(row["close"])
    a = float(row["atr"])
    if a <= 0 or np.isnan(a):
        return None
    return Signal(
        symbol=symbol,
        side="buy",
        price=price,
        stop=price - cfg.stop_atr * a,
        target=price + cfg.target_atr * a,
        reason=f"EMA{cfg.ema_fast}/{cfg.ema_slow} cross up, above VWAP, RSI {row['rsi']:.0f}",
    )


def orb_signal(symbol: str, bars: pd.DataFrame, cfg: Settings) -> Signal | None:
    """Opening-range breakout: buy the first close above the opening range high.
    Stop at the opening range low, target at orb_target_r times the risk."""
    row = bars.iloc[-1]
    if not row["orb_break"]:
        return None
    if cfg.orb_last_entry:
        h, m = map(int, cfg.orb_last_entry.split(":"))
        et = bars.index[-1].tz_convert("America/New_York")
        if et.hour * 60 + et.minute >= h * 60 + m:
            return None
    price = float(row["close"])
    stop = float(row["or_low"])
    if not price > stop:
        return None
    return Signal(
        symbol=symbol,
        side="buy",
        price=price,
        stop=stop,
        target=price + cfg.orb_target_r * (price - stop),
        reason=f"broke {cfg.orb_minutes}-min opening range high {row['or_high']:.2f}",
    )


def market_ok(market_bars: pd.DataFrame | None) -> bool:
    """True when the market symbol's last close is above its session VWAP. No data = don't trade."""
    if market_bars is None or market_bars.empty:
        return False
    row = market_bars.iloc[-1]
    return bool(row["close"] > row["vwap"])


def exit_on_trend_break(bars: pd.DataFrame, cfg: Settings | None = None) -> bool:
    if cfg is not None and cfg.strategy == "orb":
        return False  # ORB holds until stop, target, or end of day
    return bool(bars.iloc[-1]["cross_down"])
