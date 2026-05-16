"""
Turso HTTP client with a sqlite3-compatible interface.

Replaces libsql_experimental for cloud Turso connections.
Each execute() sends one HTTP request (auto-commit semantics).
"""
import httpx


def _encode_arg(v):
    if v is None:
        return {"type": "null"}
    if isinstance(v, bool):
        return {"type": "integer", "value": "1" if v else "0"}
    if isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        return {"type": "float", "value": str(v)}
    return {"type": "text", "value": str(v)}


def _decode(cell):
    t = cell.get("type")
    if t == "null":
        return None
    if t == "integer":
        return int(cell["value"])
    if t == "float":
        return float(cell["value"])
    return cell.get("value")


class TursoCursor:
    def __init__(self, cols, rows):
        self.description = [(c["name"], None, None, None, None, None, None) for c in cols]
        self.rowcount = len(rows)
        self._rows = [tuple(_decode(cell) for cell in row) for row in rows]
        self._pos = 0

    def fetchone(self):
        if self._pos >= len(self._rows):
            return None
        row = self._rows[self._pos]
        self._pos += 1
        return row

    def fetchall(self):
        rows = self._rows[self._pos:]
        self._pos = len(self._rows)
        return rows


_EMPTY_CURSOR = TursoCursor([], [])


class TursoConnection:
    """
    Wraps Turso's HTTP pipeline API with a sqlite3-style interface.

    Each execute() is a single pipeline request. commit() is a no-op —
    writes are auto-committed per request. This trades strict atomicity
    for simplicity; acceptable for an ingest-style workload.
    """

    def __init__(self, url: str, auth_token: str):
        base = url.replace("libsql://", "https://")
        self._url = f"{base}/v2/pipeline"
        self._headers = {
            "Authorization": f"Bearer {auth_token}",
            "Content-Type": "application/json",
        }
        self._client = httpx.Client(timeout=30.0)

    def execute(self, sql: str, params=()) -> TursoCursor:
        requests = [
            {
                "type": "execute",
                "stmt": {"sql": sql, "args": [_encode_arg(p) for p in params]},
            },
            {"type": "close"},
        ]
        resp = self._client.post(
            self._url, json={"requests": requests}, headers=self._headers
        )
        resp.raise_for_status()
        result = resp.json()["results"][0]
        if result["type"] == "error":
            raise Exception(f"Turso error: {result['error']['message']}")
        res = result["response"]["result"]
        return TursoCursor(res["cols"], res["rows"])

    def commit(self):
        pass  # auto-committed per execute

    def close(self):
        self._client.close()

    def sync(self):
        pass  # no local replica to sync
