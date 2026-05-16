import uuid
import sqlite3
from datetime import datetime, timezone


class Store:
    def __init__(self, db_path: str, turso_url: str = "", auth_token: str = ""):
        self._path = db_path
        self._turso_url = turso_url
        self._auth_token = auth_token
        self._conn = None

    def _get_conn(self):
        if self._conn is None:
            if self._turso_url:
                from db.turso import TursoConnection
                self._conn = TursoConnection(self._turso_url, self._auth_token)
            else:
                self._conn = sqlite3.connect(self._path, check_same_thread=False)
        return self._conn

    def _sync(self):
        pass  # no-op: Turso HTTP is always up-to-date; sqlite3 needs no sync

    def initialize(self):
        conn = self._get_conn()
        statements = [
            """CREATE TABLE IF NOT EXISTS patients (
                id TEXT PRIMARY KEY, name TEXT, created_at TEXT NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS reports (
                id TEXT PRIMARY KEY,
                patient_id TEXT NOT NULL REFERENCES patients(id),
                source_file TEXT, ingested_at TEXT NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS parameters (
                id TEXT PRIMARY KEY,
                report_id TEXT NOT NULL REFERENCES reports(id),
                patient_id TEXT NOT NULL REFERENCES patients(id),
                name TEXT NOT NULL, raw_name TEXT, unit TEXT,
                organ TEXT, ref_min REAL, ref_max REAL)""",
            """CREATE TABLE IF NOT EXISTS readings (
                id TEXT PRIMARY KEY,
                parameter_id TEXT NOT NULL REFERENCES parameters(id),
                result_date TEXT, value REAL, status TEXT)""",
            """CREATE TABLE IF NOT EXISTS xp_log (
                id TEXT PRIMARY KEY,
                patient_id TEXT NOT NULL REFERENCES patients(id),
                event TEXT, xp_awarded INTEGER, created_at TEXT NOT NULL)""",
        ]
        for stmt in statements:
            conn.execute(stmt)
        conn.commit()
        self._sync()

    def create_patient(self, name: str | None = None) -> str:
        pid = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        conn = self._get_conn()
        conn.execute("INSERT INTO patients (id, name, created_at) VALUES (?, ?, ?)", (pid, name, now))
        conn.commit()
        self._sync()
        return pid

    def save_report(self, patient_id: str, source_file: str, parameters: list[dict]) -> str:
        rid = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO reports (id, patient_id, source_file, ingested_at) VALUES (?, ?, ?, ?)",
            (rid, patient_id, source_file, now),
        )
        for p in parameters:
            cur = conn.execute(
                "SELECT id FROM parameters WHERE patient_id = ? AND name = ?",
                (patient_id, p["name"]),
            )
            row = cur.fetchone()
            if row:
                param_id = row[0]
                # Update reference range to latest values
                conn.execute(
                    "UPDATE parameters SET ref_min = ?, ref_max = ?, organ = ? WHERE id = ?",
                    (p.get("ref_min"), p.get("ref_max"), p.get("organ", "other"), param_id),
                )
            else:
                param_id = str(uuid.uuid4())
                conn.execute(
                    """INSERT INTO parameters
                       (id, report_id, patient_id, name, raw_name, unit, organ, ref_min, ref_max)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (param_id, rid, patient_id,
                     p["name"], p.get("raw_name", p["name"]), p.get("unit", ""),
                     p.get("organ", "other"), p.get("ref_min"), p.get("ref_max")),
                )
            for r in p.get("readings", []):
                conn.execute(
                    "INSERT INTO readings (id, parameter_id, result_date, value, status) VALUES (?, ?, ?, ?, ?)",
                    (str(uuid.uuid4()), param_id, r["date"], r["value"], r["status"]),
                )
        conn.commit()
        self._sync()
        return rid

    def get_parameters_for_organ(self, patient_id: str, organ: str) -> list[dict]:
        conn = self._get_conn()
        cur = conn.execute(
            "SELECT id, name, raw_name, unit, organ, ref_min, ref_max FROM parameters WHERE patient_id = ? AND organ = ?",
            (patient_id, organ),
        )
        rows = cur.fetchall()
        result = []
        for row in rows:
            param = dict(zip([d[0] for d in cur.description], row))
            rcur = conn.execute(
                "SELECT id, result_date, value, status FROM readings WHERE parameter_id = ? ORDER BY result_date DESC",
                (param["id"],),
            )
            param["readings"] = [dict(zip([d[0] for d in rcur.description], r)) for r in rcur.fetchall()]
            result.append(param)
        return result

    def get_all_parameters(self, patient_id: str) -> list[dict]:
        conn = self._get_conn()
        cur = conn.execute(
            "SELECT DISTINCT organ FROM parameters WHERE patient_id = ?", (patient_id,)
        )
        organs = [row[0] for row in cur.fetchall()]
        result = []
        for organ in organs:
            result.extend(self.get_parameters_for_organ(patient_id, organ))
        return result

    def get_latest_report(self, patient_id: str) -> dict | None:
        cur = self._get_conn().execute(
            "SELECT id, patient_id, source_file, ingested_at FROM reports WHERE patient_id = ? ORDER BY ingested_at DESC LIMIT 1",
            (patient_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return dict(zip([d[0] for d in cur.description], row))

    def log_xp(self, patient_id: str, event: str, xp: int):
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO xp_log (id, patient_id, event, xp_awarded, created_at) VALUES (?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), patient_id, event, xp, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        self._sync()

    def get_xp_total(self, patient_id: str) -> int:
        cur = self._get_conn().execute(
            "SELECT SUM(xp_awarded) FROM xp_log WHERE patient_id = ?", (patient_id,)
        )
        row = cur.fetchone()
        return int(row[0] or 0)

    def get_parameter_trends(
        self, patient_id: str, organs: list[str] | None = None, lookback: int = 5
    ) -> list[dict]:
        """Return trend data for every parameter across the given organs (all if None)."""
        from core.scorer import trend_series, compute_trend
        if organs:
            organ_list = organs
        else:
            organ_list = [r["organ"] for r in self.get_organ_summaries(patient_id)]
        result = []
        for organ in organ_list:
            for p in self.get_parameters_for_organ(patient_id, organ):
                series = trend_series(p["readings"], p["ref_min"], p["ref_max"], lookback)
                direction = compute_trend(p["readings"], p["ref_min"], p["ref_max"], lookback)
                result.append({
                    "name": p["name"],
                    "organ": organ,
                    "unit": p.get("unit", ""),
                    "ref_min": p["ref_min"],
                    "ref_max": p["ref_max"],
                    "direction": direction,
                    "series": series,
                    "latest_value": p["readings"][0]["value"] if p["readings"] else None,
                    "latest_status": p["readings"][0]["status"] if p["readings"] else None,
                })
        return result

    def get_organ_summaries(self, patient_id: str) -> list[dict]:
        cur = self._get_conn().execute(
            "SELECT DISTINCT organ FROM parameters WHERE patient_id = ? AND organ != 'other'",
            (patient_id,),
        )
        return [{"organ": row[0]} for row in cur.fetchall()]
