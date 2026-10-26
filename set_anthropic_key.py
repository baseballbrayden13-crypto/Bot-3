"""Paste your Anthropic API key into .env without opening the file. Input is hidden."""
from getpass import getpass
from pathlib import Path

env = Path(__file__).with_name(".env")
key = getpass("Paste your Anthropic API key (hidden), then press Enter: ").strip()

lines, found = [], False
for line in env.read_text().splitlines():
    if line.startswith("ANTHROPIC_API_KEY="):
        line, found = f"ANTHROPIC_API_KEY={key}", True
    lines.append(line)
if not found:
    lines.append(f"ANTHROPIC_API_KEY={key}")
env.write_text("\n".join(lines) + "\n")
print("Saved. Tell Claude you're done.")
