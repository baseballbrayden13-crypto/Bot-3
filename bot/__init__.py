"""Day trading bot package. Loads .env on import if python-dotenv is installed."""
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass
