@echo off
title Trading bot (paper)
cd /d "C:\Users\baseb\Downloads\trading-bot\trading-bot"
echo Paper trading bot. Leave this window open while the market is open (9:30am-4pm Eastern).
echo Close this window to stop it.
echo.
.venv\Scripts\python.exe -W ignore -m bot.live
pause
