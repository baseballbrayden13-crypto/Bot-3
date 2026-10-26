"""Paste your Alpaca paper keys into .env without opening the file. Input is hidden."""
from getpass import getpass
from pathlib import Path

env = Path(__file__).with_name(".env")
key = getpass("Paste your Alpaca API key (hidden), then press Enter: ").strip()
secret = getpass("Paste your Alpaca secret key (hidden), then press Enter: ").strip()

lines = []
for line in env.read_text().splitlines():
    if line.startswith("ALPACA_API_KEY="):
        line = f"ALPACA_API_KEY={key}"
    elif line.startswith("ALPACA_SECRET_KEY="):
        line = f"ALPACA_SECRET_KEY={secret}"
    lines.append(line)
env.write_text("\n".join(lines) + "\n")
print("Saved. Tell Claude you're done.")
