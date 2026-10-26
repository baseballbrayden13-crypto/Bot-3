---
name: strategy-change
description: Rules for changing the bot's trading logic or risk limits. Use whenever editing bot/strategy.py, bot/risk.py, bot/backtest.py, bot/ai_review.py, or strategy/risk settings in bot/config.py, or when the user wants to tune, improve, or add a strategy.
---

# Changing the strategy or risk rules

## Hard rules

- **Never touch live-trading switches.** Do not set or change `LIVE_TRADING` or `LIVE_TRADING_CONFIRM`, and do not weaken the paper/live check in `bot/broker.py`.
- **Never read out, edit, or commit `.env`.** It holds API keys. Put new settings in `bot/config.py` with a safe default and document them in `.env.example`.
- **Keep risk limits at least as strict** unless the user explicitly asks to loosen one: ~0.5% risk per trade, 20% max position, 3 open positions, 10 trades/day, −2% daily halt, no entries in the first 15 minutes, flat 10 minutes before the close.
- **No lookahead.** Signals may only use bars up to and including the current one. The backtest fills at the next bar's open plus slippage; keep it that way.
- The backtest and live loop must share the same strategy and risk code. Don't add logic to only one of them.

## Workflow

1. **Baseline first.** Before editing, run the `backtest` skill with the current code and save it, e.g. `--out backtest_trades_before.csv`.
2. **Make the change.** Prefer adding a new setting with the old behaviour as the default, so it can be compared and switched off.
3. **Test.** Run `.venv/Scripts/python -m pytest`. Add a test in `tests/test_bot.py` for new signal or risk logic.
4. **Backtest again** with the same source, days and symbols, `--out backtest_trades_after.csv`. Show before vs after side by side: trades, win rate, profit factor, return, max drawdown.
5. **Check on unseen data.** If settings were tuned, test on a period that was not used for tuning (e.g. tune on the older half, check on the most recent months). If the gain disappears, say so: it was fit to the past.
6. **Update docs.** If behaviour changed, update the tables in `README.md` and the `BACKTEST` expectations in `bot/report.py` so weekly reports compare against the right numbers.

## When reporting

Be honest about weak results: a small gain over few trades, or a profit factor near 1.0, is not an edge. Don't recommend going live based on a backtest.
