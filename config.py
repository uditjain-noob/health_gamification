import os
from pathlib import Path

GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", "")
LLM_MODEL: str = os.getenv("LLM_MODEL", "gemini-2.0-flash")

# Turso / libsql config
# For local dev: set DB_PATH only (no TURSO_URL needed)
# For Turso cloud: set TURSO_URL + TURSO_AUTH_TOKEN (DB_PATH used as local replica file)
DB_PATH: str = os.getenv("DB_PATH", "healthquest.db")
TURSO_URL: str = os.getenv("TURSO_URL", "")
TURSO_AUTH_TOKEN: str = os.getenv("TURSO_AUTH_TOKEN", "")

DATA_DIR: Path = Path(__file__).parent / "data"

# Singletons — populated lazily on first call
_store = None
_client = None

def get_store():
    global _store
    if _store is None:
        from db.store import Store
        _store = Store(db_path=DB_PATH, turso_url=TURSO_URL, auth_token=TURSO_AUTH_TOKEN)
        _store.initialize()
    return _store

def get_client():
    global _client
    if _client is None:
        from llm.gemini import GeminiClient
        _client = GeminiClient(api_key=GOOGLE_API_KEY, model=LLM_MODEL)
    return _client
