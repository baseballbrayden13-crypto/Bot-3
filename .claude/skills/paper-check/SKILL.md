---
name: paper-check
description: Check how the bot is doing in paper trading. Use when the user asks how the bot is doing, whether it's running, what it traded, why it didn't trade, or wants a weekly report or a comparison of paper results with the backtest.
---

# Paper-trading check

Read-only: this skill looks at the bot, it never places, cancels, or closes orders and never changes `.env`.

## 1. Is it running?

The bot is started by the Windows scheduled task **"Trading bot (paper)"** (or `Start trading bot.bat`), which runs `python -m bot.live`.

```powershell
Get-ScheduledTask -TaskName "Trading bot (paper)" | Get-ScheduledTaskInfo
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Select-Object ProcessId,CreationDate,CommandLine
```

Report the last run time and result, and whether a `bot.live` process is alive. Market hours are 9:30–16:00 ET on weekdays; not running outside them is normal.

## 2. What happened?

Read the tail of `trades.log` (e.g. last 150 lines). Lines look like `2026-10-23 09:29:37,354 INFO <message>`. Summarize, per day:

- Startup lines (`Connected to Alpaca PAPER account` — flag loudly if it ever says LIVE).
- Signals, orders, fills, exits.
- `AI rejected (<confidence>): <reason>` lines from the Claude reviewer — count them per symbol and give the main reasons.
- Any `WARNING`/`ERROR` lines or tracebacks, and days with no log lines at all on a weekday.

Skip the `HTTP Request:` noise.

## 3. Weekly report

```bash
.venv/Scripts/python -m bot.report --days 7
```

This pulls filled orders from Alpaca, pairs them into round trips, counts reviewer approvals/rejections, compares against the backtest numbers in `BACKTEST` in `bot/report.py`, and writes `reports/weekly_<date>.txt`. Read that file and summarize it. Earlier reports in `reports/` show the trend.

## 4. Compare with the backtest

Compare paper trades/day, win rate and profit factor against the backtest (the `BACKTEST` dict in `bot/report.py`, or a recent `backtest_trades_*.csv`). Point out:

- Far fewer trades than expected → check whether the reviewer is rejecting most signals or the bot wasn't running.
- With fewer than ~30 paper trades, the comparison is noise; say so.
- Don't suggest going live; the README asks for a long, positive paper record over 100+ trades first.
