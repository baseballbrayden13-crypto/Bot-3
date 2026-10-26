"""Animated "avatar" window that shows what the bot is doing, live.

Run:  pythonw -m bot.avatar   (or double-click "Bot Avatar" on the Desktop)

Read-only: it reads trades.log and your Alpaca paper account, never places
or changes orders. Starts a tiny web page on http://127.0.0.1:8765 and opens
it in an Edge app window. It quits by itself a minute after you close the window.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .config import Settings

PORT = 8765
ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "trades.log"
PAGE = Path(__file__).with_name("avatar_page.html")
IDLE_QUIT_SECONDS = 90

LINE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ (\w+) (.*)$")
RULES = [
    ("ai", re.compile(r"^(\w+) AI (approved|rejected) \(([\d.]+)\): (.*)$")),
    ("buy", re.compile(r"^BUY (\w+) x(\d+) @~([\d.]+) stop ([\d.]+) target ([\d.]+) \| (.*)$")),
    ("exit", re.compile(r"^EXIT (\w+): (.*)$")),
    ("flatten", re.compile(r"^Flattening all positions: (.*)$")),
    ("newday", re.compile(r"^New day \S+, starting equity \$([\d.]+)$")),
    ("start", re.compile(r"^Connected to Alpaca (\w+) account$")),
    ("watching", re.compile(r"^Watching (.*) on (\d+)-min bars")),
    ("stopped", re.compile(r"^Stopped\.")),
    ("review_fail", re.compile(r"^AI review failed")),
    ("error", re.compile(r"^Error in loop")),
]

_cache: dict[str, tuple[float, object]] = {}
_last_hit = time.time()


def cached(key: str, ttl: float, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    try:
        val = fn()
    except Exception as e:  # keep the page alive if Alpaca hiccups
        val = {"error": str(e)[:200]}
    _cache[key] = (time.time(), val)
    return val


def log_events() -> list[dict]:
    """Today's interesting lines from trades.log, turned into events."""
    if not LOG.exists():
        return []
    today = datetime.now().strftime("%Y-%m-%d")
    events = []
    with LOG.open(encoding="utf-8", errors="replace") as f:
        for n, raw in enumerate(f):
            m = LINE.match(raw.rstrip())
            if not m or not m.group(1).startswith(today):
                continue
            stamp, _level, msg = m.groups()
            for kind, rx in RULES:
                r = rx.match(msg)
                if not r:
                    continue
                ev = {"id": f"log{n}", "t": stamp.replace(" ", "T"), "kind": kind}
                g = r.groups()
                if kind == "ai":
                    ev.update(symbol=g[0], approved=g[1] == "approved", confidence=float(g[2]), reason=g[3])
                elif kind == "buy":
                    ev.update(symbol=g[0], qty=int(g[1]), price=float(g[2]), stop=float(g[3]), target=float(g[4]), reason=g[5])
                elif kind == "exit":
                    ev.update(symbol=g[0], reason=g[1])
                elif kind == "flatten":
                    ev.update(reason=g[0])
                elif kind == "newday":
                    ev.update(equity=float(g[0]))
                elif kind == "watching":
                    ev.update(symbols=g[0])
                events.append(ev)
                break
    return events


def _client():
    from alpaca.trading.client import TradingClient

    cfg = Settings()
    return TradingClient(cfg.alpaca_key, cfg.alpaca_secret, paper=not cfg.is_live)


def account() -> dict:
    c = _client()
    a = c.get_account()
    equity, last = float(a.equity), float(a.last_equity)
    positions = [
        {
            "symbol": p.symbol,
            "qty": float(p.qty),
            "avg": float(p.avg_entry_price),
            "price": float(p.current_price or 0),
            "upl": float(p.unrealized_pl or 0),
            "uplpc": float(p.unrealized_plpc or 0) * 100,
        }
        for p in c.get_all_positions()
    ]
    clock = c.get_clock()
    return {
        "equity": equity,
        "day_pnl": equity - last,
        "day_pct": (equity - last) / last * 100 if last else 0,
        "positions": positions,
        "market_open": bool(clock.is_open),
        "paper": not Settings().is_live,
    }


def fill_events() -> list[dict]:
    """Today's filled orders at Alpaca. Sells come from here, because stop-loss and
    take-profit fills happen at the broker and never show up in trades.log."""
    from alpaca.trading.enums import QueryOrderStatus
    from alpaca.trading.requests import GetOrdersRequest

    midnight = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    orders = _client().get_orders(
        GetOrdersRequest(status=QueryOrderStatus.CLOSED, after=midnight.astimezone(timezone.utc), limit=200, nested=True)
    )
    flat = []
    for o in orders:
        flat.append(o)
        flat.extend(o.legs or [])
    fills = sorted((o for o in flat if o.filled_at and o.filled_avg_price), key=lambda o: o.filled_at)
    last_buy: dict[str, float] = {}
    events = []
    for o in fills:
        side = str(o.side.value if hasattr(o.side, "value") else o.side).lower()
        price, qty = float(o.filled_avg_price), float(o.filled_qty)
        t = o.filled_at.astimezone().strftime("%Y-%m-%dT%H:%M:%S")
        if side == "buy":
            last_buy[o.symbol] = price
            events.append({"id": f"fill{o.id}", "t": t, "kind": "filled", "symbol": o.symbol, "qty": qty, "price": price})
            continue
        otype = str(o.order_type.value if hasattr(o.order_type, "value") else o.order_type).lower()
        how = {"limit": "target", "stop": "stop", "stop_limit": "stop"}.get(otype, "closed")
        entry = last_buy.get(o.symbol)
        pnl = (price - entry) * qty if entry else None
        events.append({"id": f"fill{o.id}", "t": t, "kind": "sold", "symbol": o.symbol, "qty": qty, "price": price, "how": how, "pnl": pnl})
    return events


def bot_running() -> bool:
    """Is a `python -m bot.live` process alive on this PC?"""
    if sys.platform != "win32":
        return True
    cmd = "(Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" | Where-Object { $_.CommandLine -like '*bot.live*' }).Count"
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command", cmd],
        capture_output=True, text=True, timeout=15, creationflags=0x08000000,  # no console window
    ).stdout.strip()
    return out not in ("", "0")


def state() -> dict:
    acct = cached("acct", 10, account)
    fills = cached("fills", 15, fill_events)
    events = log_events() + (fills if isinstance(fills, list) else [])
    events.sort(key=lambda e: e["t"])
    return {
        "now": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "account": acct,
        "bot_running": cached("running", 20, bot_running),
        "symbols": Settings().symbols,
        "bar_minutes": Settings().bar_minutes,
        "events": events[-60:],
    }


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        global _last_hit
        _last_hit = time.time()
        if self.path.startswith("/state"):
            body, ctype = json.dumps(state()).encode(), "application/json"
        elif self.path in ("/", "/index.html"):
            body, ctype = PAGE.read_bytes(), "text/html; charset=utf-8"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # keep quiet
        pass


def open_window(url: str) -> None:
    edge = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe"
    if edge.exists():
        subprocess.Popen([str(edge), f"--app={url}", "--window-size=480,900"])
    else:
        webbrowser.open(url)


def main() -> None:
    os.chdir(ROOT)
    url = f"http://127.0.0.1:{PORT}/"
    try:
        server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError:  # already running: just open another window
        open_window(url)
        return
    threading.Thread(target=server.serve_forever, daemon=True).start()
    open_window(url)
    while time.time() - _last_hit < IDLE_QUIT_SECONDS:
        time.sleep(5)
    server.shutdown()


if __name__ == "__main__":
    main()
