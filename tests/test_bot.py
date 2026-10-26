from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from bot.backtest import run_backtest
from bot.config import Settings
from bot.risk import RiskManager
from bot.strategy import add_indicators, rsi

ET = ZoneInfo("America/New_York")


def synthetic_bars(days=10, seed=0, drift=0.0):
    rng = np.random.default_rng(seed)
    idx = []
    for d in pd.bdate_range("2026-03-02", periods=days):
        start = pd.Timestamp(d.date()).tz_localize(ET) + pd.Timedelta(hours=9, minutes=30)
        idx += list(pd.date_range(start, periods=78, freq="5min"))
    idx = pd.DatetimeIndex(idx).tz_convert("UTC")
    close = 100 * np.exp(np.cumsum(rng.normal(drift, 0.002, len(idx))))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) * (1 + rng.uniform(0, 0.001, len(idx)))
    low = np.minimum(open_, close) * (1 - rng.uniform(0, 0.001, len(idx)))
    vol = rng.integers(1_000, 10_000, len(idx))
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": vol}, index=idx)


def test_rsi_bounds():
    r = rsi(synthetic_bars()["close"], 14)
    assert r.between(0, 100).all()


def test_indicators_have_no_lookahead():
    df = synthetic_bars()
    full = add_indicators(df, Settings())
    partial = add_indicators(df.iloc[:200], Settings())
    pd.testing.assert_frame_equal(full.iloc[:200], partial)


def test_position_size_respects_risk_and_cap():
    cfg = Settings()
    rm = RiskManager(cfg)
    qty = rm.position_size(equity=25_000, price=100, stop=98)  # $2 risk/share
    assert qty * 2 <= 25_000 * cfg.risk_per_trade + 1e-9
    assert qty * 100 <= 25_000 * cfg.max_position_pct
    assert rm.position_size(25_000, 100, 101) == 0  # stop above price is invalid


def test_daily_loss_halts_trading():
    rm = RiskManager(Settings())
    rm.new_day(datetime(2026, 3, 2).date(), 10_000)
    rm.check_daily_loss(9_790)
    assert rm.halted
    ok, why = rm.can_enter("SPY", datetime(2026, 3, 2, 11, 0, tzinfo=ET))
    assert not ok and "daily loss" in why


def test_entry_window():
    rm = RiskManager(Settings())
    assert not rm.in_entry_window(datetime(2026, 3, 2, 9, 35, tzinfo=ET))
    assert rm.in_entry_window(datetime(2026, 3, 2, 11, 0, tzinfo=ET))
    assert rm.must_flatten(datetime(2026, 3, 2, 15, 55, tzinfo=ET))


def test_backtest_runs_and_ends_flat():
    frames = {"AAA": synthetic_bars(seed=1), "BBB": synthetic_bars(seed=2)}
    res = run_backtest(frames, Settings(), 25_000)
    log = res["trade_log"]
    if len(log):
        # every trade closes the same day (no overnight holds)
        same_day = log["entry_time"].dt.tz_convert(ET).dt.date == log["exit_time"].dt.tz_convert(ET).dt.date
        assert same_day.all()
    assert abs(res["final_equity"] - (25_000 + (log["pnl"].sum() if len(log) else 0))) < 1e-6


def test_market_filter_blocks_entries_when_market_weak(monkeypatch):
    monkeypatch.setenv("MARKET_FILTER", "MKT")
    frames = {"AAA": synthetic_bars(seed=1)}
    weak = synthetic_bars(seed=3, drift=-0.002)  # steadily falling, so stays below VWAP
    filtered = run_backtest(frames, Settings(), 25_000, market=weak)
    no_market_data = run_backtest(frames, Settings(), 25_000, market=None)
    monkeypatch.delenv("MARKET_FILTER")
    baseline = run_backtest(frames, Settings(), 25_000)
    assert filtered["trades"] < baseline["trades"]
    assert no_market_data["trades"] == 0  # filter on but no market data means no entries


def test_orb_breaks_at_most_once_a_day_and_after_the_range():
    df = add_indicators(synthetic_bars(days=10, seed=4), Settings())
    breaks = df[df["orb_break"]]
    days = breaks.index.tz_convert(ET).date
    assert len(set(days)) == len(days)  # once per day
    et = breaks.index.tz_convert(ET)
    assert ((et.hour * 60 + et.minute) >= 9 * 60 + 45).all()  # only after the 15-min range closes


def test_orb_max_per_day_allows_repeat_breakouts(monkeypatch):
    monkeypatch.setenv("ORB_MAX_PER_DAY", "3")
    df = add_indicators(synthetic_bars(days=10, seed=4), Settings())
    per_day = df[df["orb_break"]].groupby(df[df["orb_break"]].index.tz_convert(ET).date).size()
    assert per_day.max() <= 3
    one = add_indicators(synthetic_bars(days=10, seed=4), Settings(orb_max_per_day=1))
    assert one["orb_break"].sum() <= df["orb_break"].sum()


def test_orb_backtest_runs(monkeypatch):
    monkeypatch.setenv("STRATEGY", "orb")
    res = run_backtest({"AAA": synthetic_bars(seed=1)}, Settings(), 25_000)
    assert set(res["trade_log"].get("exit_reason", [])) <= {"stop", "target", "end of day", "end of test", "daily loss halt"}


def test_report_pairs_buys_with_sells():
    from types import SimpleNamespace as O

    from bot.report import round_trips

    t = pd.Timestamp("2026-10-23 14:00", tz="UTC")
    orders = [
        O(symbol="SPY", side="OrderSide.BUY", filled_qty="10", filled_avg_price="100", filled_at=t, order_type="market"),
        O(symbol="SPY", side="OrderSide.SELL", filled_qty="10", filled_avg_price="101", filled_at=t + pd.Timedelta("1h"),
          order_type="OrderType.LIMIT"),
        O(symbol="AAPL", side="OrderSide.BUY", filled_qty="5", filled_avg_price="200", filled_at=t, order_type="market"),
        O(symbol="AAPL", side="OrderSide.SELL", filled_qty="5", filled_avg_price="198", filled_at=t + pd.Timedelta("2h"),
          order_type="OrderType.STOP"),
    ]
    trips = {r["symbol"]: r for r in round_trips(orders)}
    assert trips["SPY"]["pnl"] == 10 and trips["SPY"]["exit_reason"] == "target"
    assert trips["AAPL"]["pnl"] == -10 and trips["AAPL"]["exit_reason"] == "stop"


def test_live_requires_both_flags(monkeypatch):
    monkeypatch.setenv("LIVE_TRADING", "true")
    monkeypatch.delenv("LIVE_TRADING_CONFIRM", raising=False)
    assert not Settings().is_live
    monkeypatch.setenv("LIVE_TRADING_CONFIRM", "I_UNDERSTAND_REAL_MONEY")
    assert Settings().is_live
